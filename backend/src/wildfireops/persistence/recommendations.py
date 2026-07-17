from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.decision.recommendations import (
    ObservationRecord,
    RecommendationContext,
    RecommendationWrite,
    StoredRecommendation,
    StoredRecommendationAssignment,
)
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.persistence.decision_models import (
    IncidentSnapshotModel,
    RecommendationAssignmentModel,
    RecommendationModel,
    ScenarioModel,
    ScenarioResourceOverrideModel,
    ScenarioRoadClosureModel,
    ScenarioVersionModel,
    ScenarioWeatherOverrideModel,
)
from wildfireops.persistence.incidents import acquire_incident_refresh_lock
from wildfireops.persistence.observed_models import SourceObservationModel
from wildfireops.persistence.scenarios import ScenarioRepository


class RecommendationRepository:
    """Session-bound adapter; the application owns its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._idempotency = ScenarioRepository(session)

    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim:
        return await self._idempotency.claim_idempotency(
            scope=scope,
            key=key,
            request_hash=request_hash,
        )

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None:
        await self._idempotency.complete_idempotency(
            claim_id=claim_id,
            response_type=response_type,
            response_id=response_id,
        )

    async def acquire_incident_refresh_lock(self) -> None:
        await acquire_incident_refresh_lock(self._session)

    async def load_context(self, version_id: UUID) -> RecommendationContext | None:
        version = await self._session.get(ScenarioVersionModel, version_id)
        if version is None or version.graph_version is None:
            return None
        locked_scenario_id = await self._session.scalar(
            select(ScenarioModel.id)
            .where(ScenarioModel.id == version.scenario_id)
            .with_for_update()
        )
        if locked_scenario_id is None:
            return None
        snapshot = await self._session.get(
            IncidentSnapshotModel,
            version.incident_snapshot_id,
        )
        if snapshot is None:
            return None
        latest_scenario_version = await self._session.scalar(
            select(func.max(ScenarioVersionModel.version)).where(
                ScenarioVersionModel.scenario_id == version.scenario_id
            )
        )
        latest_snapshot_version = await self._session.scalar(
            select(func.max(IncidentSnapshotModel.snapshot_version)).where(
                IncidentSnapshotModel.incident_id == version.incident_id
            )
        )
        if latest_scenario_version is None or latest_snapshot_version is None:
            return None
        road_closures = tuple(
            await self._session.scalars(
                select(ScenarioRoadClosureModel.edge_id)
                .where(ScenarioRoadClosureModel.scenario_version_id == version.id)
                .order_by(ScenarioRoadClosureModel.edge_id)
            )
        )
        weather_rows = (
            await self._session.execute(
                select(
                    ScenarioWeatherOverrideModel.wind_speed_mps,
                    ScenarioWeatherOverrideModel.wind_direction_degrees,
                )
                .where(ScenarioWeatherOverrideModel.scenario_version_id == version.id)
                .order_by(
                    ScenarioWeatherOverrideModel.wind_speed_mps,
                    ScenarioWeatherOverrideModel.wind_direction_degrees,
                )
            )
        ).all()
        resource_rows = (
            await self._session.execute(
                select(
                    ScenarioResourceOverrideModel.resource_id,
                    ScenarioResourceOverrideModel.available,
                )
                .where(ScenarioResourceOverrideModel.scenario_version_id == version.id)
                .order_by(ScenarioResourceOverrideModel.resource_id)
            )
        ).all()
        observation_pairs = _observation_pairs(snapshot.source_versions)
        observation_rows = (
            (
                await self._session.execute(
                    select(
                        SourceObservationModel.source_name,
                        SourceObservationModel.source_record_id,
                        SourceObservationModel.observation_kind,
                        SourceObservationModel.observed_at,
                        func.ST_X(SourceObservationModel.geometry).label("longitude"),
                        func.ST_Y(SourceObservationModel.geometry).label("latitude"),
                        SourceObservationModel.confidence,
                        SourceObservationModel.intensity,
                        SourceObservationModel.wind_speed_mps,
                        SourceObservationModel.wind_direction_degrees,
                        SourceObservationModel.temperature_celsius,
                        SourceObservationModel.raw_payload,
                    )
                    .where(
                        tuple_(
                            SourceObservationModel.source_name,
                            SourceObservationModel.source_record_id,
                        ).in_(observation_pairs)
                    )
                    .order_by(
                        SourceObservationModel.source_name,
                        SourceObservationModel.source_record_id,
                    )
                )
            ).all()
            if observation_pairs
            else ()
        )
        return RecommendationContext(
            version_id=version.id,
            scenario_id=version.scenario_id,
            scenario_version=version.version,
            latest_scenario_version=latest_scenario_version,
            incident_id=version.incident_id,
            snapshot_id=snapshot.id,
            snapshot_version=snapshot.snapshot_version,
            latest_snapshot_version=latest_snapshot_version,
            source_versions=snapshot.source_versions,
            incident_state=snapshot.incident_state,
            asset_state=snapshot.asset_state,
            resource_state=snapshot.resource_state,
            graph_version=version.graph_version,
            road_closures=road_closures,
            weather_overrides=tuple(
                (row.wind_speed_mps, row.wind_direction_degrees) for row in weather_rows
            ),
            resource_overrides=tuple(
                (row.resource_id, row.available) for row in resource_rows
            ),
            observations=tuple(
                ObservationRecord(
                    source_name=row.source_name,
                    source_record_id=row.source_record_id,
                    observation_kind=row.observation_kind,
                    observed_at=row.observed_at,
                    longitude=row.longitude,
                    latitude=row.latitude,
                    confidence=row.confidence,
                    intensity=row.intensity,
                    wind_speed_mps=row.wind_speed_mps,
                    wind_direction_degrees=row.wind_direction_degrees,
                    temperature_celsius=row.temperature_celsius,
                    raw_payload=row.raw_payload,
                )
                for row in observation_rows
            ),
        )

    async def store(self, write: RecommendationWrite) -> StoredRecommendation:
        model = RecommendationModel(
            scenario_version_id=write.scenario_version_id,
            idempotency_key_id=write.idempotency_key_id,
            input_version=write.input_version,
            source_versions=write.source_versions,
            graph_version=write.graph_version,
            risk_version=write.risk_version,
            algorithm_version=write.algorithm_version,
            solver_status=write.solver_status,
            runtime_milliseconds=write.runtime_milliseconds,
            request_inputs=write.request_inputs,
            objective_components=write.objective_components,
            uncovered_destination_ids=list(write.uncovered_destination_ids),
            explanation=write.explanation,
        )
        self._session.add(model)
        await self._session.flush()
        self._session.add_all(
            [
                RecommendationAssignmentModel(
                    recommendation_id=model.id,
                    resource_id=item.resource_id,
                    destination_id=item.destination_id,
                    route=dict(item.route),
                    travel_minutes=item.travel_minutes,
                    capacity=item.capacity,
                )
                for item in write.assignments
            ]
        )
        await self._session.flush()
        stored = await self.get(model.id)
        if stored is None:
            raise RuntimeError("created recommendation could not be loaded")
        return stored

    async def get(self, recommendation_id: UUID) -> StoredRecommendation | None:
        model = await self._session.get(RecommendationModel, recommendation_id)
        if model is None:
            return None
        version = await self._session.get(
            ScenarioVersionModel,
            model.scenario_version_id,
        )
        if version is None:
            raise RuntimeError("recommendation scenario version does not exist")
        rows = (
            await self._session.scalars(
                select(RecommendationAssignmentModel)
                .where(RecommendationAssignmentModel.recommendation_id == model.id)
                .order_by(
                    RecommendationAssignmentModel.resource_id,
                    RecommendationAssignmentModel.destination_id,
                )
            )
        ).all()
        return StoredRecommendation(
            id=model.id,
            scenario_version_id=model.scenario_version_id,
            incident_snapshot_id=version.incident_snapshot_id,
            input_version=model.input_version,
            source_versions=model.source_versions,
            graph_version=model.graph_version,
            risk_version=model.risk_version,
            algorithm_version=model.algorithm_version,
            solver_status=model.solver_status,
            runtime_milliseconds=model.runtime_milliseconds,
            request_inputs=model.request_inputs,
            objective_components=model.objective_components,
            uncovered_destination_ids=tuple(
                str(item) for item in model.uncovered_destination_ids
            ),
            explanation=model.explanation,
            assignments=tuple(
                StoredRecommendationAssignment(
                    resource_id=row.resource_id,
                    destination_id=row.destination_id,
                    route=row.route,
                    travel_minutes=row.travel_minutes,
                    capacity=row.capacity,
                )
                for row in rows
            ),
        )


def _observation_pairs(source_versions: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(source_versions, dict):
        return ()
    inputs = source_versions.get("observation_inputs")
    if not isinstance(inputs, list):
        return ()
    pairs: list[tuple[str, str]] = []
    for raw in inputs:
        if not isinstance(raw, dict):
            return ()
        source_name = raw.get("source_name")
        record_ids = raw.get("record_ids")
        if (
            not isinstance(source_name, str)
            or not source_name.strip()
            or not isinstance(record_ids, list)
            or not record_ids
        ):
            return ()
        for record_id in record_ids:
            if not isinstance(record_id, str) or not record_id.strip():
                return ()
            pairs.append((source_name.strip(), record_id.strip()))
    return tuple(pairs)
