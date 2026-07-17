from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.clustering import (
    ClusteringConfig,
    DetectionCluster,
    cluster_detections,
)
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.ingestion.quarantine import write_quarantine
from wildfireops.decision.risk import RiskConfig, default_risk_config
from wildfireops.persistence.exposures import refresh_exposure_and_risk
from wildfireops.persistence.incidents import (
    acquire_incident_refresh_lock,
    load_current_fire_detections,
    refresh_incidents,
)
from wildfireops.persistence.observations import ObservationRepository
from wildfireops.persistence.observed_models import SourceStatusModel
from wildfireops.persistence.notifications import (
    notify_ingestion_success,
    notify_source_status,
)
from wildfireops.sources.base import SourceAdapter
from wildfireops.sources.http import SourceUnavailable


type SessionFactory = Callable[[], AsyncSession]
type UtcClock = Callable[[], datetime]
type IncidentRefresher = Callable[
    [AsyncSession, tuple[DetectionCluster, ...], float], Awaitable[None]
]


class ExposureRiskRefresher(Protocol):
    def __call__(
        self,
        session: AsyncSession,
        *,
        reference_at: datetime,
        exposure_config: ExposureConfig,
        risk_config: RiskConfig,
        clustering_algorithm_version: str,
    ) -> Awaitable[tuple[UUID, ...]]: ...


@dataclass(frozen=True, slots=True)
class IngestionRun:
    source_name: str
    accepted: int
    deduplicated: int
    quarantined: int
    outcome: str


class IngestionService:
    def __init__(
        self,
        session_factory: SessionFactory,
        clustering_config: ClusteringConfig,
        *,
        observation_repository: ObservationRepository | None = None,
        incident_refresher: IncidentRefresher = refresh_incidents,
        exposure_risk_refresher: ExposureRiskRefresher = refresh_exposure_and_risk,
        exposure_config: ExposureConfig = ExposureConfig(),
        risk_config: RiskConfig | None = None,
        clock: UtcClock = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clustering_config = clustering_config
        self._observation_repository = observation_repository or ObservationRepository()
        self._incident_refresher = incident_refresher
        self._exposure_risk_refresher = exposure_risk_refresher
        self._exposure_config = exposure_config
        self._risk_config = risk_config or default_risk_config()
        self._clock = clock

    async def run_source(self, adapter: SourceAdapter) -> IngestionRun:
        attempted_at = _require_utc(self._clock(), "ingestion clock")
        status_attempted_at = attempted_at
        try:
            batch = await adapter.fetch()
        except Exception as error:
            return await self._record_fetch_failure(
                source_name=adapter.source_name,
                attempted_at=attempted_at,
                error=error,
            )

        async with self._session_factory() as session:
            try:
                await acquire_incident_refresh_lock(session)
                fire_observations: list[NormalizedObservation] = []
                weather_observations: list[WeatherObservation] = []
                for observation in batch.observations:
                    if isinstance(observation, NormalizedObservation):
                        fire_observations.append(observation)
                    elif isinstance(observation, WeatherObservation):
                        weather_observations.append(observation)
                    else:
                        raise TypeError(
                            "unsupported observation type: "
                            f"{type(observation).__name__}"
                        )
                stats = await self._observation_repository.upsert_many(
                    session,
                    (*fire_observations, *weather_observations),
                )
                quarantined = await write_quarantine(session, batch.failures)
                reference_at = await _resolve_operational_reference(
                    session,
                    explicit_reference_at=batch.reference_at,
                    attempted_at=attempted_at,
                )
                status_attempted_at = reference_at
                current_detections = await load_current_fire_detections(
                    session,
                    reference_at=reference_at,
                    temporal_window_seconds=(
                        self._clustering_config.temporal_window_seconds
                    ),
                )
                clusters = cluster_detections(
                    current_detections,
                    self._clustering_config,
                )
                await self._incident_refresher(
                    session,
                    clusters,
                    self._clustering_config.spatial_radius_meters,
                )
                snapshot_ids = await self._exposure_risk_refresher(
                    session,
                    reference_at=reference_at,
                    exposure_config=self._exposure_config,
                    risk_config=self._risk_config,
                    clustering_algorithm_version=(
                        self._clustering_config.algorithm_version
                    ),
                )
                await _record_source_success(
                    session,
                    source_name=adapter.source_name,
                    attempted_at=status_attempted_at,
                    accepted=stats.inserted,
                    deduplicated=stats.deduplicated,
                    quarantined=quarantined,
                )
                await notify_ingestion_success(
                    session,
                    snapshot_ids=snapshot_ids,
                    source_name=adapter.source_name,
                )
                await session.commit()
            except Exception as error:
                try:
                    await session.rollback()
                except Exception:
                    pass
                try:
                    await self._record_processing_failure(
                        source_name=adapter.source_name,
                        attempted_at=status_attempted_at,
                        error=error,
                    )
                except Exception:
                    pass
                raise

        return IngestionRun(
            source_name=adapter.source_name,
            accepted=stats.inserted,
            deduplicated=stats.deduplicated,
            quarantined=quarantined,
            outcome="success",
        )

    async def _record_processing_failure(
        self,
        *,
        source_name: str,
        attempted_at: datetime,
        error: Exception,
    ) -> None:
        async with self._session_factory() as session:
            try:
                await acquire_incident_refresh_lock(session)
                await _record_source_failure(
                    session,
                    source_name=source_name,
                    attempted_at=attempted_at,
                    error_message=_sanitized_error_message(error),
                )
                await notify_source_status(session, source_name=source_name)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _record_fetch_failure(
        self,
        *,
        source_name: str,
        attempted_at: datetime,
        error: Exception,
    ) -> IngestionRun:
        error_message = _sanitized_error_message(error)
        async with self._session_factory() as session:
            try:
                await acquire_incident_refresh_lock(session)
                await _record_source_failure(
                    session,
                    source_name=source_name,
                    attempted_at=attempted_at,
                    error_message=error_message,
                )
                await notify_source_status(session, source_name=source_name)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return IngestionRun(
            source_name=source_name,
            accepted=0,
            deduplicated=0,
            quarantined=0,
            outcome="failed",
        )


async def _record_source_success(
    session: AsyncSession,
    *,
    source_name: str,
    attempted_at: datetime,
    accepted: int,
    deduplicated: int,
    quarantined: int,
) -> None:
    values = {
        "source_name": source_name,
        "outcome": "success",
        "last_attempted_at": attempted_at,
        "last_success_at": attempted_at,
        "accepted_count": accepted,
        "deduplicated_count": deduplicated,
        "quarantined_count": quarantined,
        "error_message": None,
    }
    statement = (
        insert(SourceStatusModel)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["source_name"],
            set_={**values, "updated_at": func.now()},
        )
    )
    await session.execute(statement)


async def _resolve_operational_reference(
    session: AsyncSession,
    *,
    explicit_reference_at: datetime | None,
    attempted_at: datetime,
) -> datetime:
    if explicit_reference_at is not None:
        return explicit_reference_at
    prior_attempted_at, prior_success_at = (
        await session.execute(
            select(
                func.max(SourceStatusModel.last_attempted_at),
                func.max(SourceStatusModel.last_success_at),
            )
        )
    ).one()
    candidates = [attempted_at]
    if prior_attempted_at is not None:
        candidates.append(_require_utc(prior_attempted_at, "source status"))
    if prior_success_at is not None:
        candidates.append(_require_utc(prior_success_at, "source status"))
    return max(candidates)


def _require_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must return UTC")
    return value


def _sanitized_error_message(error: Exception) -> str:
    return str(error) if isinstance(error, SourceUnavailable) else type(error).__name__


async def _record_source_failure(
    session: AsyncSession,
    *,
    source_name: str,
    attempted_at: datetime,
    error_message: str,
) -> None:
    insert_values = {
        "source_name": source_name,
        "outcome": "failed",
        "last_attempted_at": attempted_at,
        "last_success_at": None,
        "accepted_count": 0,
        "deduplicated_count": 0,
        "quarantined_count": 0,
        "error_message": error_message,
    }
    update_values = {
        key: value
        for key, value in insert_values.items()
        if key not in {"source_name", "last_success_at"}
    }
    update_values["updated_at"] = func.now()
    statement = (
        insert(SourceStatusModel)
        .values(**insert_values)
        .on_conflict_do_update(
            index_elements=["source_name"],
            set_=update_values,
        )
    )
    await session.execute(statement)
