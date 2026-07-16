from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from wildfireops.domain.scenarios import (
    ResourceOverride,
    RoadClosure,
    WeatherOverride,
)
from wildfireops.domain.scenario_versions import (
    IdempotencyClaim,
    PinnedIncidentSnapshot,
    PinnedSnapshotInvalid,
    StoredScenarioVersion,
)
from wildfireops.geospatial.road_graph import RoadGraph


class ScenarioRepository(Protocol):
    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim: ...

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None: ...

    async def lock_incident(self, incident_id: UUID) -> bool: ...

    async def latest_snapshot(
        self,
        incident_id: UUID,
    ) -> PinnedIncidentSnapshot | None: ...

    async def create(
        self,
        *,
        incident_id: UUID,
        snapshot_id: UUID,
        graph_version: str,
        name: str | None,
        objective: str,
        author_id: str,
        algorithm_config_version: str,
    ) -> StoredScenarioVersion: ...

    async def lock_scenario(self, scenario_id: UUID) -> bool: ...

    async def latest_version(
        self,
        scenario_id: UUID,
    ) -> StoredScenarioVersion | None: ...

    async def add_version(
        self,
        *,
        previous: StoredScenarioVersion,
        created_by: str,
        road_closures: tuple[RoadClosure, ...],
        weather_overrides: tuple[WeatherOverride, ...],
        resource_overrides: tuple[ResourceOverride, ...],
    ) -> StoredScenarioVersion: ...

    async def get_version(
        self,
        version_id: UUID,
    ) -> StoredScenarioVersion | None: ...

    async def get_snapshot(
        self,
        snapshot_id: UUID,
    ) -> PinnedIncidentSnapshot | None: ...


class ScenarioError(ValueError):
    """Base class for transport-neutral scenario command failures."""


class ScenarioNotFound(ScenarioError):
    code = "scenario_not_found"


class ScenarioValidationError(ScenarioError):
    code = "scenario_invalid"


class IdempotencyConflict(ScenarioError):
    code = "idempotency_conflict"

    def __init__(self) -> None:
        super().__init__("idempotency key was already used with a different request")


class ScenarioService:
    def __init__(
        self,
        *,
        graphs: Mapping[str, RoadGraph],
        repository: ScenarioRepository,
    ) -> None:
        graph_map = dict(graphs)
        for version, graph in graph_map.items():
            if version != graph.graph_version:
                raise ValueError("graph registry key must match graph_version")
        self._graphs = MappingProxyType(graph_map)
        self._repository = repository

    async def create(
        self,
        *,
        incident_id: UUID,
        graph_version: str,
        name: str | None,
        objective: str,
        author_id: str,
        algorithm_config_version: str,
        idempotency_key: str,
    ) -> StoredScenarioVersion:
        if not isinstance(incident_id, UUID):
            raise ScenarioValidationError("incident_id must be a UUID")
        graph_version = _nonblank(graph_version, "graph_version")
        if graph_version not in self._graphs:
            raise ScenarioValidationError("graph_version is not available")
        normalized_name = _optional_nonblank(name, "name")
        normalized_objective = _nonblank(
            objective,
            "objective",
            maximum_length=None,
        )
        normalized_author = _nonblank(author_id, "author_id")
        normalized_algorithm = _nonblank(
            algorithm_config_version,
            "algorithm_config_version",
        )
        normalized_key = _idempotency_key(idempotency_key)
        request_hash = _request_hash(
            {
                "incident_id": str(incident_id),
                "graph_version": graph_version,
                "name": normalized_name,
                "objective": normalized_objective,
                "author_id": normalized_author,
                "algorithm_config_version": normalized_algorithm,
            }
        )
        claim = await self._repository.claim_idempotency(
            scope=f"incident:{incident_id}:scenario:create",
            key=normalized_key,
            request_hash=request_hash,
        )
        replayed = await self._resolve_replay(claim, request_hash)
        if replayed is not None:
            return replayed

        if not await self._repository.lock_incident(incident_id):
            raise ScenarioNotFound("incident does not exist")
        try:
            snapshot = await self._repository.latest_snapshot(incident_id)
        except PinnedSnapshotInvalid as error:
            raise ScenarioValidationError(str(error)) from error
        if snapshot is None:
            raise ScenarioValidationError("incident has no snapshot")
        stored = await self._repository.create(
            incident_id=incident_id,
            snapshot_id=snapshot.id,
            graph_version=graph_version,
            name=normalized_name,
            objective=normalized_objective,
            author_id=normalized_author,
            algorithm_config_version=normalized_algorithm,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="scenario_version",
            response_id=stored.version_id,
        )
        return stored

    async def add_version(
        self,
        *,
        scenario_id: UUID,
        created_by: str,
        idempotency_key: str,
        road_closures: tuple[RoadClosure, ...] | None = None,
        weather_overrides: tuple[WeatherOverride, ...] | None = None,
        resource_overrides: tuple[ResourceOverride, ...] | None = None,
    ) -> StoredScenarioVersion:
        if not isinstance(scenario_id, UUID):
            raise ScenarioValidationError("scenario_id must be a UUID")
        normalized_author = _nonblank(created_by, "created_by")
        normalized_key = _idempotency_key(idempotency_key)
        normalized_roads = _road_replacements(road_closures)
        normalized_weather = _weather_replacements(weather_overrides)
        normalized_resources = _resource_replacements(resource_overrides)
        request_hash = _request_hash(
            {
                "created_by": normalized_author,
                "road_closures": _road_payload(normalized_roads),
                "weather_overrides": _weather_payload(normalized_weather),
                "resource_overrides": _resource_payload(normalized_resources),
            }
        )
        claim = await self._repository.claim_idempotency(
            scope=f"scenario:{scenario_id}:version:add",
            key=normalized_key,
            request_hash=request_hash,
        )
        replayed = await self._resolve_replay(claim, request_hash)
        if replayed is not None:
            return replayed

        if not await self._repository.lock_scenario(scenario_id):
            raise ScenarioNotFound("scenario does not exist")
        previous = await self._repository.latest_version(scenario_id)
        if previous is None:
            raise RuntimeError("scenario has no pinned version")
        effective_roads = (
            previous.scenario.road_closures
            if normalized_roads is None
            else normalized_roads
        )
        effective_weather = (
            previous.scenario.weather_overrides
            if normalized_weather is None
            else normalized_weather
        )
        effective_resources = (
            previous.scenario.resource_overrides
            if normalized_resources is None
            else normalized_resources
        )
        graph = self._graphs.get(previous.graph_version)
        if graph is None:
            raise ScenarioValidationError("pinned graph_version is not available")
        unknown_edges = sorted(
            {closure.edge_id for closure in effective_roads} - graph.edge_ids
        )
        if unknown_edges:
            raise ScenarioValidationError(
                f"road closure is not in pinned graph: {unknown_edges[0]}"
            )
        try:
            snapshot = await self._repository.get_snapshot(
                UUID(previous.scenario.incident_snapshot_id)
            )
        except PinnedSnapshotInvalid as error:
            raise ScenarioValidationError(str(error)) from error
        if snapshot is None:
            raise RuntimeError("pinned incident snapshot does not exist")
        unknown_resources = sorted(
            {override.resource_id for override in effective_resources}
            - snapshot.resource_ids
        )
        if unknown_resources:
            raise ScenarioValidationError(
                f"resource override is not in pinned snapshot: {unknown_resources[0]}"
            )

        stored = await self._repository.add_version(
            previous=previous,
            created_by=normalized_author,
            road_closures=effective_roads,
            weather_overrides=effective_weather,
            resource_overrides=effective_resources,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="scenario_version",
            response_id=stored.version_id,
        )
        return stored

    async def _resolve_replay(
        self,
        claim: IdempotencyClaim,
        request_hash: str,
    ) -> StoredScenarioVersion | None:
        if claim.created:
            return None
        if claim.request_hash != request_hash:
            raise IdempotencyConflict()
        if claim.response_type != "scenario_version" or claim.response_id is None:
            raise RuntimeError("idempotency response is incomplete")
        response = await self._repository.get_version(claim.response_id)
        if response is None:
            raise RuntimeError("idempotency response does not exist")
        return response


def _road_payload(
    value: tuple[RoadClosure, ...] | None,
) -> list[dict[str, object]] | None:
    if value is None:
        return None
    return [{"edge_id": item.edge_id} for item in value]


def _weather_payload(
    value: tuple[WeatherOverride, ...] | None,
) -> list[dict[str, object]] | None:
    if value is None:
        return None
    return [
        {
            "wind_speed_mps": item.wind_speed_mps,
            "wind_direction_degrees": item.wind_direction_degrees,
        }
        for item in value
    ]


def _resource_payload(
    value: tuple[ResourceOverride, ...] | None,
) -> list[dict[str, object]] | None:
    if value is None:
        return None
    return [
        {"resource_id": item.resource_id, "available": item.available} for item in value
    ]


def _nonblank(
    value: object,
    field: str,
    *,
    maximum_length: int | None = 255,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioValidationError(f"{field} must be a nonblank string")
    normalized = value.strip()
    if maximum_length is not None and len(normalized) > maximum_length:
        raise ScenarioValidationError(
            f"{field} must not exceed {maximum_length} characters"
        )
    return normalized


def _optional_nonblank(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonblank(value, field)


def _idempotency_key(value: object) -> str:
    return _nonblank(value, "idempotency_key")


def _road_replacements(
    value: tuple[RoadClosure, ...] | None,
) -> tuple[RoadClosure, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise ScenarioValidationError("road_closures must be a tuple or None")
    normalized = tuple(
        sorted(
            (
                RoadClosure(_nonblank(item.edge_id, "road closure edge_id"))
                for item in value
            ),
            key=lambda item: item.edge_id,
        )
    )
    _reject_duplicate_ids(
        (item.edge_id for item in normalized),
        "road closure edge_id",
    )
    return normalized


def _weather_replacements(
    value: tuple[WeatherOverride, ...] | None,
) -> tuple[WeatherOverride, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise ScenarioValidationError("weather_overrides must be a tuple or None")
    normalized: list[WeatherOverride] = []
    for item in value:
        speed = _finite_number(item.wind_speed_mps, "wind_speed_mps")
        direction = _finite_number(
            item.wind_direction_degrees,
            "wind_direction_degrees",
        )
        try:
            normalized.append(WeatherOverride(speed, direction))
        except ValueError as error:
            raise ScenarioValidationError(str(error)) from error
    return tuple(
        sorted(
            normalized,
            key=lambda item: (
                item.wind_speed_mps,
                item.wind_direction_degrees,
            ),
        )
    )


def _resource_replacements(
    value: tuple[ResourceOverride, ...] | None,
) -> tuple[ResourceOverride, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise ScenarioValidationError("resource_overrides must be a tuple or None")
    normalized: list[ResourceOverride] = []
    for item in value:
        if not isinstance(item.available, bool):
            raise ScenarioValidationError("resource available must be a boolean")
        normalized.append(
            ResourceOverride(
                _nonblank(item.resource_id, "resource override resource_id"),
                item.available,
            )
        )
    ordered = tuple(sorted(normalized, key=lambda item: item.resource_id))
    _reject_duplicate_ids(
        (item.resource_id for item in ordered),
        "resource override resource_id",
    )
    return ordered


def _reject_duplicate_ids(values: Iterable[str], field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ScenarioValidationError(f"duplicate {field}: {value}")
        seen.add(value)


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScenarioValidationError(f"{field} must be a finite number")
    parsed = float(value)
    if not isfinite(parsed):
        raise ScenarioValidationError(f"{field} must be a finite number")
    return 0.0 if parsed == 0 else parsed


def _request_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
