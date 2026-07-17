from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from wildfireops.decision.explanations import explain_result
from wildfireops.decision.optimizer import (
    CandidateRoute,
    OptimizationRequest,
    OptimizationResult,
    solve_allocation,
)
from wildfireops.decision.risk import (
    RiskConfig,
    normalize_risk_inputs,
    score_risk,
    serialize_risk_breakdown,
)
from wildfireops.domain.observations import (
    NormalizedObservation,
    WeatherObservation,
    freeze_json_object,
)
from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.geospatial.exposure import ExposedAssetExposure
from wildfireops.geospatial.road_graph import (
    RoadGraph,
    RouteResult,
    compute_route,
    nearest_road_node,
)


@dataclass(frozen=True, slots=True)
class RecommendationRequest:
    max_response_minutes: int = 30
    max_solver_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    source_name: object
    source_record_id: object
    observation_kind: object
    observed_at: object
    longitude: object
    latitude: object
    confidence: object
    intensity: object
    wind_speed_mps: object
    wind_direction_degrees: object
    temperature_celsius: object
    raw_payload: object


@dataclass(frozen=True, slots=True)
class RecommendationContext:
    version_id: UUID
    scenario_id: UUID
    scenario_version: int
    latest_scenario_version: int
    incident_id: UUID
    snapshot_id: UUID
    snapshot_version: int
    latest_snapshot_version: int
    source_versions: object
    incident_state: object
    asset_state: object
    resource_state: object
    graph_version: str
    road_closures: tuple[str, ...]
    weather_overrides: tuple[tuple[float, float], ...]
    resource_overrides: tuple[tuple[str, bool], ...]
    observations: tuple[ObservationRecord, ...]


@dataclass(frozen=True, slots=True)
class StoredRecommendationAssignment:
    resource_id: str
    destination_id: str
    route: Mapping[str, object]
    travel_minutes: float
    capacity: int


@dataclass(frozen=True, slots=True)
class StoredRecommendation:
    id: UUID
    scenario_version_id: UUID
    incident_snapshot_id: UUID
    input_version: str
    source_versions: Mapping[str, object]
    graph_version: str
    risk_version: str
    algorithm_version: str
    solver_status: str
    runtime_milliseconds: int
    request_inputs: Mapping[str, object]
    objective_components: Mapping[str, object]
    uncovered_destination_ids: tuple[str, ...]
    explanation: Mapping[str, object]
    assignments: tuple[StoredRecommendationAssignment, ...]


@dataclass(frozen=True, slots=True)
class RecommendationWrite:
    scenario_version_id: UUID
    incident_snapshot_id: UUID
    idempotency_key_id: UUID
    input_version: str
    source_versions: dict[str, object]
    graph_version: str
    risk_version: str
    algorithm_version: str
    solver_status: str
    runtime_milliseconds: int
    request_inputs: dict[str, object]
    objective_components: dict[str, object]
    uncovered_destination_ids: tuple[str, ...]
    explanation: dict[str, object]
    assignments: tuple[StoredRecommendationAssignment, ...]


class RecommendationRepository(Protocol):
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

    async def acquire_incident_refresh_lock(self) -> None: ...

    async def load_context(self, version_id: UUID) -> RecommendationContext | None: ...

    async def store(
        self, recommendation: RecommendationWrite
    ) -> StoredRecommendation: ...

    async def get(self, recommendation_id: UUID) -> StoredRecommendation | None: ...


class RecommendationError(ValueError):
    """Base class for transport-neutral recommendation failures."""


class RecommendationNotFound(RecommendationError):
    code = "scenario_version_not_found"


class RecommendationInputsInvalid(RecommendationError):
    code = "recommendation_inputs_invalid"


class RecommendationScenarioStale(RecommendationError):
    code = "scenario_stale"


class RecommendationIdempotencyConflict(RecommendationError):
    code = "idempotency_conflict"


class RecommendationService:
    def __init__(
        self,
        *,
        graphs: Mapping[str, RoadGraph],
        risk_config: RiskConfig,
        repository: RecommendationRepository,
    ) -> None:
        self._graphs = MappingProxyType(dict(graphs))
        self._risk_config = risk_config
        self._repository = repository

    async def generate(
        self,
        version_id: str,
        request: RecommendationRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StoredRecommendation:
        parsed_id = _identifier(version_id, RecommendationNotFound)
        normalized = _recommendation_request(request)
        actor = _nonblank(actor_id, "actor_id")
        key = _nonblank(idempotency_key, "idempotency_key")
        request_hash = _digest(
            {
                "max_response_minutes": normalized.max_response_minutes,
                "max_solver_seconds": normalized.max_solver_seconds,
                "actor_id": actor,
            }
        )
        claim = await self._repository.claim_idempotency(
            scope=f"scenario-version:{parsed_id}:recommendation",
            key=key,
            request_hash=request_hash,
        )
        if not claim.created:
            if claim.request_hash != request_hash:
                raise RecommendationIdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            if claim.response_type != "recommendation" or claim.response_id is None:
                raise RuntimeError("idempotency response is incomplete")
            stored = await self._repository.get(claim.response_id)
            if stored is None:
                raise RuntimeError("idempotency response does not exist")
            return stored

        await self._repository.acquire_incident_refresh_lock()
        context = await self._repository.load_context(parsed_id)
        if context is None:
            raise RecommendationNotFound("scenario version was not found")
        if (
            context.scenario_version != context.latest_scenario_version
            or context.snapshot_version != context.latest_snapshot_version
        ):
            raise RecommendationScenarioStale(
                "scenario version or incident snapshot is not current"
            )
        graph = self._graphs.get(context.graph_version)
        if graph is None or graph.graph_version != context.graph_version:
            raise RecommendationInputsInvalid("pinned road graph is unavailable")

        try:
            source_versions = _json_object(context.source_versions, "source_versions")
            incident_state = _json_object(context.incident_state, "incident_state")
            assets = _exposures(context.asset_state)
            resources = _resources(context.resource_state, context.resource_overrides)
            detections, weather = _observations(
                source_versions,
                incident_state,
                context.observations,
                context.weather_overrides,
            )
            reference_at = _utc_timestamp(
                incident_state.get("reference_at"),
                "incident_state.reference_at",
            )
            incident_longitude, incident_latitude = _representative_point(
                incident_state.get("geometry_geojson"),
                "incident_state.geometry_geojson",
            )
            exposure = _json_object(
                incident_state.get("exposure"),
                "incident_state.exposure",
            )
            normalized_risk = normalize_risk_inputs(
                exposures=assets,
                detections=detections,
                weather_observations=weather,
                incident_longitude=incident_longitude,
                incident_latitude=incident_latitude,
                reference_at=reference_at,
                exposure_buffer_meters=_finite_number(
                    exposure.get("buffer_meters"),
                    "incident_state.exposure.buffer_meters",
                ),
                config=self._risk_config,
            )
            risk = score_risk(normalized_risk.factors, self._risk_config)
            demands = _demands(assets, risk.score)
            routes = _candidate_routes(
                graph,
                resources,
                demands,
                context.road_closures,
            )
            result = solve_allocation(
                OptimizationRequest(
                    resources=resources,
                    demands=demands,
                    routes=routes,
                    max_response_minutes=normalized.max_response_minutes,
                    max_solver_seconds=normalized.max_solver_seconds,
                )
            )
        except RecommendationInputsInvalid:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise RecommendationInputsInvalid(str(error)) from error

        risk_payload = serialize_risk_breakdown(
            risk,
            normalized_risk.raw_evidence,
        )
        staleness = _staleness_payload(context, source_versions)
        input_version = recommendation_input_version(context)
        route_map = {
            (route.resource_id, route.destination_id): route.route for route in routes
        }
        request_inputs: dict[str, object] = {
            "scenario_version_id": str(context.version_id),
            "incident_snapshot_id": str(context.snapshot_id),
            "staleness": staleness,
            "resources": [_resource_payload(item) for item in resources],
            "demands": [_demand_payload(item) for item in demands],
            "overlays": {
                "closed_edge_ids": list(context.road_closures),
                "weather": [
                    {
                        "wind_speed_mps": speed,
                        "wind_direction_degrees": direction,
                    }
                    for speed, direction in context.weather_overrides
                ],
                "resources": [
                    {"resource_id": resource_id, "available": available}
                    for resource_id, available in context.resource_overrides
                ],
            },
            "limits": {
                "max_response_minutes": normalized.max_response_minutes,
                "max_solver_seconds": normalized.max_solver_seconds,
            },
            "risk_breakdown": risk_payload,
            "candidate_routes": [
                {
                    "resource_id": item.resource_id,
                    "destination_id": item.destination_id,
                    "route": _route_payload(item.route),
                }
                for item in routes
            ],
            "binding_constraints": list(result.binding_constraints),
        }
        explanation = explain_result(result)
        write = RecommendationWrite(
            scenario_version_id=context.version_id,
            incident_snapshot_id=context.snapshot_id,
            idempotency_key_id=claim.id,
            input_version=input_version,
            source_versions=source_versions,
            graph_version=context.graph_version,
            risk_version=self._risk_config.algorithm_version,
            algorithm_version=result.algorithm_version,
            solver_status=result.status,
            runtime_milliseconds=result.runtime_milliseconds,
            request_inputs=request_inputs,
            objective_components=_objective_components(result),
            uncovered_destination_ids=result.uncovered_destination_ids,
            explanation=explanation,
            assignments=tuple(
                StoredRecommendationAssignment(
                    resource_id=item.resource_id,
                    destination_id=item.destination_id,
                    route=_route_payload(
                        route_map[(item.resource_id, item.destination_id)]
                    ),
                    travel_minutes=item.travel_minutes,
                    capacity=item.capacity,
                )
                for item in result.assignments
            ),
        )
        stored = await self._repository.store(write)
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="recommendation",
            response_id=stored.id,
        )
        return stored


def _recommendation_request(value: object) -> RecommendationRequest:
    if not isinstance(value, RecommendationRequest):
        raise RecommendationInputsInvalid("request is invalid")
    minutes = value.max_response_minutes
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise RecommendationInputsInvalid(
            "max_response_minutes must be a nonnegative integer"
        )
    seconds = value.max_solver_seconds
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, int | float)
        or not isfinite(float(seconds))
        or seconds <= 0
    ):
        raise RecommendationInputsInvalid(
            "max_solver_seconds must be a finite positive number"
        )
    return RecommendationRequest(minutes, float(seconds))


def _observations(
    source_versions: Mapping[str, object],
    incident_state: Mapping[str, object],
    records: tuple[ObservationRecord, ...],
    weather_overrides: tuple[tuple[float, float], ...],
) -> tuple[tuple[NormalizedObservation, ...], tuple[WeatherObservation, ...]]:
    inputs = source_versions.get("observation_inputs")
    if not isinstance(inputs, list):
        raise RecommendationInputsInvalid(
            "source_versions observation_inputs is invalid"
        )
    expected: dict[tuple[str, str], str | None] = {}
    pinned_latest: dict[str, datetime] = {}
    for raw in inputs:
        item = _json_object(raw, "source_versions observation input")
        source_name = _nonblank(item.get("source_name"), "source_name")
        source_version = item.get("source_version")
        if source_version is not None:
            source_version = _nonblank(source_version, "source_version")
        record_ids = item.get("record_ids")
        if not isinstance(record_ids, list) or not record_ids:
            raise RecommendationInputsInvalid("record_ids must be a nonempty list")
        normalized_ids = tuple(_nonblank(value, "record_id") for value in record_ids)
        if len(set(normalized_ids)) != len(normalized_ids):
            raise RecommendationInputsInvalid("record_ids contain duplicates")
        for record_id in normalized_ids:
            pair = (source_name, record_id)
            if pair in expected:
                raise RecommendationInputsInvalid("source observation is pinned twice")
            expected[pair] = source_version
        pinned_latest[source_name] = _utc_timestamp(
            item.get("latest_observed_at"),
            "latest_observed_at",
        )

    selected: dict[tuple[str, str], ObservationRecord] = {}
    for record in records:
        if not isinstance(record.source_name, str) or not isinstance(
            record.source_record_id, str
        ):
            continue
        pair = (record.source_name, record.source_record_id)
        if pair in expected:
            if pair in selected:
                raise RecommendationInputsInvalid("pinned observation is duplicated")
            selected[pair] = record
    if set(selected) != set(expected):
        raise RecommendationInputsInvalid("pinned observation is missing")

    by_source: dict[str, list[datetime]] = {}
    detections: list[NormalizedObservation] = []
    weather: list[WeatherObservation] = []
    for pair in sorted(selected):
        record = selected[pair]
        source_name, record_id = pair
        observed_at = _utc_timestamp(record.observed_at, "observed_at")
        by_source.setdefault(source_name, []).append(observed_at)
        payload = _json_object(record.raw_payload, "raw_payload")
        expected_version = expected[pair]
        if (
            expected_version is not None
            and payload.get("source_version") != expected_version
        ):
            raise RecommendationInputsInvalid("pinned source version does not match")
        longitude = _finite_number(record.longitude, "observation longitude")
        latitude = _finite_number(record.latitude, "observation latitude")
        if record.observation_kind == "fire":
            detections.append(
                NormalizedObservation(
                    source_name=source_name,
                    source_record_id=record_id,
                    observed_at=observed_at,
                    longitude=longitude,
                    latitude=latitude,
                    confidence=_unit_interval(record.confidence, "confidence"),
                    intensity=(
                        None
                        if record.intensity is None
                        else _finite_number(record.intensity, "intensity")
                    ),
                    raw_payload=freeze_json_object(payload),
                )
            )
        elif record.observation_kind == "weather":
            weather.append(
                WeatherObservation(
                    source_name=source_name,
                    source_record_id=record_id,
                    observed_at=observed_at,
                    longitude=longitude,
                    latitude=latitude,
                    wind_speed_mps=_finite_nonnegative(
                        record.wind_speed_mps,
                        "wind_speed_mps",
                    ),
                    wind_direction_degrees=_direction(record.wind_direction_degrees),
                    temperature_celsius=(
                        None
                        if record.temperature_celsius is None
                        else _finite_number(
                            record.temperature_celsius,
                            "temperature_celsius",
                        )
                    ),
                    raw_payload=freeze_json_object(payload),
                )
            )
        else:
            raise RecommendationInputsInvalid("pinned observation kind is invalid")
    for source_name, timestamps in by_source.items():
        if max(timestamps) != pinned_latest[source_name]:
            raise RecommendationInputsInvalid(
                "pinned latest_observed_at does not match"
            )

    identities = incident_state.get("detection_identities")
    if not isinstance(identities, list) or any(
        not isinstance(item, str) or not item.strip() for item in identities
    ):
        raise RecommendationInputsInvalid("detection identities are invalid")
    if {item.identity for item in detections} != set(identities):
        raise RecommendationInputsInvalid("pinned detections do not match snapshot")
    if len(weather) > 1 or len(weather_overrides) > 1:
        raise RecommendationInputsInvalid("multiple weather inputs are not supported")
    if weather_overrides:
        if not weather:
            raise RecommendationInputsInvalid("weather override has no pinned weather")
        speed, direction = weather_overrides[0]
        weather[0] = replace(
            weather[0],
            wind_speed_mps=_finite_nonnegative(speed, "wind_speed_mps"),
            wind_direction_degrees=_direction(direction),
        )
    return tuple(detections), tuple(weather)


def _exposures(value: object) -> tuple[ExposedAssetExposure, ...]:
    if not isinstance(value, list):
        raise RecommendationInputsInvalid("asset_state must be a list")
    exposures: list[ExposedAssetExposure] = []
    for raw in value:
        item = _json_object(raw, "asset_state item")
        exposures.append(
            ExposedAssetExposure(
                asset_id=_nonblank(item.get("asset_id"), "asset_id"),
                asset_kind=_nonblank(item.get("asset_kind"), "asset_kind"),
                name=_nonblank(item.get("name"), "asset name"),
                population=_optional_integer(item.get("population"), "population"),
                capacity=_optional_integer(item.get("capacity"), "capacity"),
                source_name=_optional_string(item.get("source_name"), "source_name"),
                source_version=_optional_string(
                    item.get("source_version"),
                    "source_version",
                ),
                geometry_geojson=freeze_json_object(
                    _json_object(
                        item.get("geometry_geojson"),
                        "asset geometry_geojson",
                    )
                ),
                raw_metadata=freeze_json_object(
                    _json_object(
                        item.get("raw_metadata"),
                        "asset raw_metadata",
                    )
                ),
                distance_meters=_finite_nonnegative(
                    item.get("distance_meters"),
                    "distance_meters",
                ),
                bearing_degrees=(
                    None
                    if item.get("bearing_degrees") is None
                    else _direction(item.get("bearing_degrees"))
                ),
            )
        )
    if len({item.asset_id for item in exposures}) != len(exposures):
        raise RecommendationInputsInvalid("asset_state contains duplicate IDs")
    return tuple(sorted(exposures, key=lambda item: item.asset_id))


def _resources(
    value: object,
    overrides: tuple[tuple[str, bool], ...],
) -> tuple[ResourceUnit, ...]:
    if not isinstance(value, list):
        raise RecommendationInputsInvalid("resource_state must be a list")
    available_overrides = dict(overrides)
    resources: list[ResourceUnit] = []
    for raw in value:
        item = _json_object(raw, "resource_state item")
        resource_id = _nonblank(item.get("resource_id"), "resource_id")
        _nonblank(item.get("resource_type"), "resource_type")
        _nonblank(item.get("status"), "resource status")
        _json_object(item.get("raw_metadata"), "resource raw_metadata")
        capabilities = item.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise RecommendationInputsInvalid("resource capabilities are required")
        capability_values = tuple(
            _nonblank(capability, "resource capability") for capability in capabilities
        )
        if len(set(capability_values)) != len(capability_values):
            raise RecommendationInputsInvalid("resource capabilities are duplicated")
        normalized_capabilities = frozenset(capability_values)
        capacity = _positive_integer(item.get("capacity"), "resource capacity")
        available = item.get("available")
        if not isinstance(available, bool):
            raise RecommendationInputsInvalid("resource available must be a boolean")
        longitude, latitude = _representative_point(
            item.get("geometry_geojson"),
            "resource geometry_geojson",
        )
        resources.append(
            ResourceUnit(
                resource_id=resource_id,
                capabilities=normalized_capabilities,
                capacity=capacity,
                available=available_overrides.get(resource_id, available),
                longitude=longitude,
                latitude=latitude,
            )
        )
    ids = {item.resource_id for item in resources}
    if len(ids) != len(resources) or set(available_overrides) - ids:
        raise RecommendationInputsInvalid("resource state or overrides are invalid")
    return tuple(sorted(resources, key=lambda item: item.resource_id))


def _demands(
    exposures: tuple[ExposedAssetExposure, ...],
    weighted_risk: float,
) -> tuple[DemandPoint, ...]:
    demands: list[DemandPoint] = []
    for exposure in exposures:
        metadata = _json_object(exposure.raw_metadata, "asset raw_metadata")
        demand = _json_object(metadata.get("demand"), "asset demand")
        longitude, latitude = _representative_point(
            exposure.geometry_geojson,
            "asset geometry_geojson",
        )
        demands.append(
            DemandPoint(
                destination_id=exposure.asset_id,
                required_capability=_nonblank(
                    demand.get("required_capability"),
                    "required_capability",
                ),
                required_capacity=_positive_integer(
                    demand.get("required_capacity"),
                    "required_capacity",
                ),
                weighted_risk=weighted_risk,
                longitude=longitude,
                latitude=latitude,
            )
        )
    return tuple(demands)


def _candidate_routes(
    graph: RoadGraph,
    resources: tuple[ResourceUnit, ...],
    demands: tuple[DemandPoint, ...],
    closed_edge_ids: tuple[str, ...],
) -> tuple[CandidateRoute, ...]:
    resource_nodes = {
        item.resource_id: nearest_road_node(graph, item.longitude, item.latitude)
        for item in resources
    }
    demand_nodes = {
        item.destination_id: nearest_road_node(graph, item.longitude, item.latitude)
        for item in demands
    }
    return tuple(
        CandidateRoute(
            resource_id=resource.resource_id,
            destination_id=demand.destination_id,
            route=compute_route(
                graph,
                resource_nodes[resource.resource_id],
                demand_nodes[demand.destination_id],
                closed_edge_ids,
            ),
        )
        for resource in resources
        for demand in demands
    )


def _staleness_payload(
    context: RecommendationContext,
    source_versions: Mapping[str, object],
) -> dict[str, object]:
    snapshot_digest = _digest(
        {
            "source_versions": source_versions,
            "incident_state": context.incident_state,
            "asset_state": context.asset_state,
            "resource_state": context.resource_state,
        }
    )
    return {
        "scenario_version_id": str(context.version_id),
        "overlays": {
            "road_closures": list(context.road_closures),
            "weather_overrides": [list(item) for item in context.weather_overrides],
            "resource_overrides": [list(item) for item in context.resource_overrides],
        },
        "incident_snapshot_id": str(context.snapshot_id),
        "incident_snapshot_version": context.snapshot_version,
        "incident_snapshot_digest": snapshot_digest,
        "graph_version": context.graph_version,
        "risk_version": "risk-v1",
        "allocation_version": "allocation-v1",
    }


def recommendation_input_version(context: RecommendationContext) -> str:
    source_versions = _json_object(context.source_versions, "source_versions")
    return _digest(_staleness_payload(context, source_versions))


def _route_payload(route: RouteResult) -> dict[str, object]:
    return {
        "status": route.status.value,
        "edge_ids": list(route.edge_ids),
        "distance_meters": route.distance_meters,
        "travel_minutes": route.travel_minutes,
        "graph_version": route.graph_version,
        "closure_hash": route.closure_hash,
    }


def _objective_components(result: OptimizationResult) -> dict[str, object]:
    return {
        "travel_cost": result.travel_cost,
        "uncovered_risk_penalty": result.uncovered_risk_penalty,
        "objective_value": result.objective_value,
    }


def _resource_payload(resource: ResourceUnit) -> dict[str, object]:
    return {
        "resource_id": resource.resource_id,
        "capabilities": sorted(resource.capabilities),
        "capacity": resource.capacity,
        "available": resource.available,
        "longitude": resource.longitude,
        "latitude": resource.latitude,
    }


def _demand_payload(demand: DemandPoint) -> dict[str, object]:
    return {
        "destination_id": demand.destination_id,
        "required_capability": demand.required_capability,
        "required_capacity": demand.required_capacity,
        "weighted_risk": demand.weighted_risk,
        "longitude": demand.longitude,
        "latitude": demand.latitude,
    }


def _representative_point(value: object, field: str) -> tuple[float, float]:
    geometry = _json_object(value, field)
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point":
        if not isinstance(coordinates, list | tuple) or len(coordinates) < 2:
            raise RecommendationInputsInvalid(f"{field} is invalid")
        return (
            _coordinate(coordinates[0], "longitude", -180, 180),
            _coordinate(coordinates[1], "latitude", -90, 90),
        )
    points = tuple(_coordinate_pairs(coordinates))
    if not points:
        raise RecommendationInputsInvalid(f"{field} has no coordinates")
    longitude = sum(item[0] for item in points) / len(points)
    latitude = sum(item[1] for item in points) / len(points)
    return longitude, latitude


def _coordinate_pairs(value: object) -> Sequence[tuple[float, float]]:
    if isinstance(value, list | tuple):
        if len(value) >= 2 and all(isinstance(item, int | float) for item in value[:2]):
            return (
                (
                    _coordinate(value[0], "longitude", -180, 180),
                    _coordinate(value[1], "latitude", -90, 90),
                ),
            )
        points: list[tuple[float, float]] = []
        for item in value:
            points.extend(_coordinate_pairs(item))
        return points
    return ()


def _identifier(value: object, error_type: type[RecommendationError]) -> UUID:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise error_type("resource was not found") from None


def _digest(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RecommendationInputsInvalid("snapshot JSON is invalid") from error
    return sha256(encoded).hexdigest()


def _json_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RecommendationInputsInvalid(f"{field} must be an object")
    return {str(key): _json_value(item, field) for key, item in value.items()}


def _json_value(value: object, field: str) -> object:
    if isinstance(value, Mapping):
        return _json_object(value, field)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item, field) for item in value]
    if isinstance(value, float) and not isfinite(value):
        raise RecommendationInputsInvalid(f"{field} contains a non-finite number")
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise RecommendationInputsInvalid(f"{field} contains an invalid value")


def _utc_timestamp(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise RecommendationInputsInvalid(
                f"{field} must be a UTC timestamp"
            ) from None
    else:
        raise RecommendationInputsInvalid(f"{field} must be a UTC timestamp")
    if parsed.utcoffset() != timedelta(0):
        raise RecommendationInputsInvalid(f"{field} must be a UTC timestamp")
    return parsed


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationInputsInvalid(f"{field} must be a nonblank string")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _nonblank(value, field)


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecommendationInputsInvalid(f"{field} must be null or an integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RecommendationInputsInvalid(f"{field} must be a positive integer")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RecommendationInputsInvalid(f"{field} must be a finite number")
    parsed = float(value)
    if not isfinite(parsed):
        raise RecommendationInputsInvalid(f"{field} must be a finite number")
    return parsed


def _finite_nonnegative(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if parsed < 0:
        raise RecommendationInputsInvalid(f"{field} must be nonnegative")
    return parsed


def _unit_interval(value: object, field: str) -> float:
    parsed = _finite_number(value, field)
    if not 0 <= parsed <= 1:
        raise RecommendationInputsInvalid(f"{field} must be between zero and one")
    return parsed


def _direction(value: object) -> float:
    parsed = _finite_number(value, "wind_direction_degrees")
    if not 0 <= parsed < 360:
        raise RecommendationInputsInvalid("wind_direction_degrees is invalid")
    return parsed


def _coordinate(value: object, field: str, low: float, high: float) -> float:
    parsed = _finite_number(value, field)
    if not low <= parsed <= high:
        raise RecommendationInputsInvalid(f"{field} is outside valid range")
    return parsed
