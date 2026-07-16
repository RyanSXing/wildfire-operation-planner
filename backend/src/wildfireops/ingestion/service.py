from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.clustering import (
    ClusteringConfig,
    DetectionCluster,
    cluster_detections,
)
from wildfireops.ingestion.quarantine import write_quarantine
from wildfireops.persistence.incidents import (
    acquire_incident_refresh_lock,
    load_current_fire_detections,
    refresh_incidents,
)
from wildfireops.persistence.observations import ObservationRepository
from wildfireops.persistence.observed_models import SourceStatusModel
from wildfireops.sources.base import SourceAdapter
from wildfireops.sources.http import SourceUnavailable


type SessionFactory = Callable[[], AsyncSession]
type IncidentRefresher = Callable[
    [AsyncSession, tuple[DetectionCluster, ...], float], Awaitable[None]
]


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
    ) -> None:
        self._session_factory = session_factory
        self._clustering_config = clustering_config
        self._observation_repository = observation_repository or ObservationRepository()
        self._incident_refresher = incident_refresher

    async def run_source(self, adapter: SourceAdapter) -> IngestionRun:
        attempted_at = datetime.now(UTC)
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
                reference_at = max(
                    (observation.observed_at for observation in batch.observations),
                    default=attempted_at,
                )
                stats = await self._observation_repository.upsert_many(
                    session,
                    (*fire_observations, *weather_observations),
                )
                quarantined = await write_quarantine(session, batch.failures)
                await acquire_incident_refresh_lock(session)
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
                await _record_source_success(
                    session,
                    source_name=adapter.source_name,
                    attempted_at=attempted_at,
                    accepted=stats.inserted,
                    deduplicated=stats.deduplicated,
                    quarantined=quarantined,
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
                        attempted_at=attempted_at,
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
                await _record_source_failure(
                    session,
                    source_name=source_name,
                    attempted_at=attempted_at,
                    error_message=_sanitized_error_message(error),
                )
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
                await _record_source_failure(
                    session,
                    source_name=source_name,
                    attempted_at=attempted_at,
                    error_message=error_message,
                )
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
