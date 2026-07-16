from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.scenarios import (
    ResourceOverride,
    RoadClosure,
    ScenarioVersion,
    WeatherOverride,
)
from wildfireops.domain.scenario_versions import (
    IdempotencyClaim,
    PinnedIncidentSnapshot,
    PinnedSnapshotInvalid,
    StoredScenarioVersion,
)
from wildfireops.persistence.decision_models import (
    IdempotencyKeyModel,
    IncidentSnapshotModel,
    ScenarioModel,
    ScenarioResourceOverrideModel,
    ScenarioRoadClosureModel,
    ScenarioVersionModel,
    ScenarioWeatherOverrideModel,
)
from wildfireops.persistence.observed_models import WildfireIncidentModel


class ScenarioRepository:
    """Session-bound SQLAlchemy adapter; the caller owns commit and rollback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim:
        claim_id = uuid4()
        created_id = await self._session.scalar(
            insert(IdempotencyKeyModel)
            .values(
                id=claim_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
            )
            .on_conflict_do_nothing(
                index_elements=(
                    IdempotencyKeyModel.scope,
                    IdempotencyKeyModel.key,
                )
            )
            .returning(IdempotencyKeyModel.id)
        )
        if created_id is not None:
            return IdempotencyClaim(
                id=created_id,
                request_hash=request_hash,
                response_type=None,
                response_id=None,
                created=True,
            )

        existing = await self._session.scalar(
            select(IdempotencyKeyModel)
            .where(
                IdempotencyKeyModel.scope == scope,
                IdempotencyKeyModel.key == key,
            )
            .with_for_update()
        )
        if existing is None:
            raise RuntimeError("idempotency claim disappeared after conflict")
        return IdempotencyClaim(
            id=existing.id,
            request_hash=existing.request_hash,
            response_type=existing.response_type,
            response_id=existing.response_id,
            created=False,
        )

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None:
        await self._session.execute(
            update(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.id == claim_id)
            .values(response_type=response_type, response_id=response_id)
        )

    async def lock_incident(self, incident_id: UUID) -> bool:
        locked_id = await self._session.scalar(
            select(WildfireIncidentModel.id)
            .where(WildfireIncidentModel.id == incident_id)
            .with_for_update()
        )
        return locked_id is not None

    async def latest_snapshot(
        self,
        incident_id: UUID,
    ) -> PinnedIncidentSnapshot | None:
        snapshot = await self._session.scalar(
            select(IncidentSnapshotModel)
            .where(IncidentSnapshotModel.incident_id == incident_id)
            .order_by(IncidentSnapshotModel.snapshot_version.desc())
            .limit(1)
        )
        return _snapshot(snapshot)

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
    ) -> StoredScenarioVersion:
        scenario = ScenarioModel(
            incident_id=incident_id,
            name=name,
            objective=objective,
            author_id=author_id,
            algorithm_config_version=algorithm_config_version,
        )
        self._session.add(scenario)
        await self._session.flush()
        version = ScenarioVersionModel(
            scenario_id=scenario.id,
            incident_id=incident_id,
            version=1,
            incident_snapshot_id=snapshot_id,
            graph_version=graph_version,
            created_by=author_id,
        )
        self._session.add(version)
        await self._session.flush()
        stored = await self.get_version(version.id)
        if stored is None:
            raise RuntimeError("created scenario version could not be loaded")
        return stored

    async def lock_scenario(self, scenario_id: UUID) -> bool:
        locked_id = await self._session.scalar(
            select(ScenarioModel.id)
            .where(ScenarioModel.id == scenario_id)
            .with_for_update()
        )
        return locked_id is not None

    async def latest_version(
        self,
        scenario_id: UUID,
    ) -> StoredScenarioVersion | None:
        version_id = await self._session.scalar(
            select(ScenarioVersionModel.id)
            .where(ScenarioVersionModel.scenario_id == scenario_id)
            .order_by(ScenarioVersionModel.version.desc())
            .limit(1)
        )
        return None if version_id is None else await self.get_version(version_id)

    async def add_version(
        self,
        *,
        previous: StoredScenarioVersion,
        created_by: str,
        road_closures: tuple[RoadClosure, ...],
        weather_overrides: tuple[WeatherOverride, ...],
        resource_overrides: tuple[ResourceOverride, ...],
    ) -> StoredScenarioVersion:
        previous_model = await self._session.get(
            ScenarioVersionModel,
            previous.version_id,
        )
        if previous_model is None:
            raise RuntimeError("previous scenario version does not exist")
        version = ScenarioVersionModel(
            scenario_id=previous_model.scenario_id,
            incident_id=previous_model.incident_id,
            version=previous_model.version + 1,
            incident_snapshot_id=previous_model.incident_snapshot_id,
            graph_version=previous.graph_version,
            created_by=created_by,
        )
        self._session.add(version)
        await self._session.flush()
        self._session.add_all(
            [
                ScenarioRoadClosureModel(
                    scenario_version_id=version.id,
                    edge_id=closure.edge_id,
                )
                for closure in road_closures
            ]
        )
        self._session.add_all(
            [
                ScenarioWeatherOverrideModel(
                    scenario_version_id=version.id,
                    wind_speed_mps=override.wind_speed_mps,
                    wind_direction_degrees=override.wind_direction_degrees,
                )
                for override in weather_overrides
            ]
        )
        self._session.add_all(
            [
                ScenarioResourceOverrideModel(
                    scenario_version_id=version.id,
                    resource_id=override.resource_id,
                    available=override.available,
                )
                for override in resource_overrides
            ]
        )
        await self._session.flush()
        stored = await self.get_version(version.id)
        if stored is None:
            raise RuntimeError("created scenario version could not be loaded")
        return stored

    async def get_version(
        self,
        version_id: UUID,
    ) -> StoredScenarioVersion | None:
        version = await self._session.get(ScenarioVersionModel, version_id)
        if version is None or version.graph_version is None:
            return None
        road_rows = (
            await self._session.scalars(
                select(ScenarioRoadClosureModel)
                .where(ScenarioRoadClosureModel.scenario_version_id == version.id)
                .order_by(ScenarioRoadClosureModel.edge_id)
            )
        ).all()
        weather_rows = (
            await self._session.scalars(
                select(ScenarioWeatherOverrideModel).where(
                    ScenarioWeatherOverrideModel.scenario_version_id == version.id
                )
            )
        ).all()
        resource_rows = (
            await self._session.scalars(
                select(ScenarioResourceOverrideModel)
                .where(ScenarioResourceOverrideModel.scenario_version_id == version.id)
                .order_by(ScenarioResourceOverrideModel.resource_id)
            )
        ).all()
        weather = tuple(
            sorted(
                (
                    WeatherOverride(
                        row.wind_speed_mps,
                        row.wind_direction_degrees,
                    )
                    for row in weather_rows
                ),
                key=lambda item: (
                    item.wind_speed_mps,
                    item.wind_direction_degrees,
                ),
            )
        )
        scenario = ScenarioVersion(
            scenario_id=str(version.scenario_id),
            version=version.version,
            incident_snapshot_id=str(version.incident_snapshot_id),
            road_closures=tuple(RoadClosure(row.edge_id) for row in road_rows),
            weather_overrides=weather,
            resource_overrides=tuple(
                ResourceOverride(row.resource_id, row.available)
                for row in resource_rows
            ),
        )
        return StoredScenarioVersion(
            version_id=version.id,
            incident_id=version.incident_id,
            graph_version=version.graph_version,
            scenario=scenario,
        )

    async def get_snapshot(
        self,
        snapshot_id: UUID,
    ) -> PinnedIncidentSnapshot | None:
        return _snapshot(await self._session.get(IncidentSnapshotModel, snapshot_id))


def _snapshot(
    model: IncidentSnapshotModel | None,
) -> PinnedIncidentSnapshot | None:
    if model is None:
        return None
    state = model.resource_state
    if not isinstance(state, list):
        raise PinnedSnapshotInvalid("pinned snapshot resource_state is malformed")
    resource_ids: set[str] = set()
    for item in state:
        if not isinstance(item, Mapping):
            raise PinnedSnapshotInvalid("pinned snapshot resource_state is malformed")
        resource_id = item.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise PinnedSnapshotInvalid("pinned snapshot resource_state is malformed")
        normalized = resource_id.strip()
        if normalized in resource_ids:
            raise PinnedSnapshotInvalid("pinned snapshot resource_state is malformed")
        resource_ids.add(normalized)
    return PinnedIncidentSnapshot(
        id=model.id,
        resource_ids=frozenset(resource_ids),
    )
