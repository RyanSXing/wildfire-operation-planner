import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.decision.risk import RiskConfig
from wildfireops.geospatial.clustering import ClusteringConfig, DetectionCluster
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.ingestion.service import IngestionService
from wildfireops.persistence.decision_models import IncidentSnapshotModel
from wildfireops.persistence.observed_models import WildfireIncidentModel
from wildfireops.sources.base import SourceBatch
from wildfireops.sources.http import SourceUnavailable


_REFERENCE = datetime(2024, 7, 24, 18, tzinfo=UTC)
_FIRST_INCIDENT = UUID("00000000-0000-0000-0000-000000000101")
_SECOND_INCIDENT = UUID("00000000-0000-0000-0000-000000000202")


class _Adapter:
    source_name = "nws"

    async def fetch(self) -> SourceBatch:
        return SourceBatch((), (), reference_at=_REFERENCE)


class _UnavailableAdapter(_Adapter):
    async def fetch(self) -> SourceBatch:
        raise SourceUnavailable("nws", attempts=3, status_code=503)


class _GatedCommitSession(AsyncSession):
    commit_started: ClassVar[asyncio.Event]
    allow_commit: ClassVar[asyncio.Event]

    async def commit(self) -> None:
        type(self).commit_started.set()
        await type(self).allow_commit.wait()
        await super().commit()


class _FailFirstCommitSession(AsyncSession):
    commit_attempts: ClassVar[int] = 0

    async def commit(self) -> None:
        type(self).commit_attempts += 1
        if type(self).commit_attempts == 1:
            raise RuntimeError("synthetic commit failure")
        await super().commit()


@pytest_asyncio.fixture
async def notification_database() -> AsyncIterator[tuple[AsyncEngine, list[str]]]:
    settings = Settings()
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE quarantined_observations, source_status, "
                "wildfire_incidents, source_observations CASCADE"
            )
        )
    connection = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    payloads: list[str] = []

    def receive(
        _connection: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        payloads.append(payload)

    await connection.add_listener("wildfireops_events", receive)
    try:
        yield engine, payloads
    finally:
        if not connection.is_closed():
            await connection.remove_listener("wildfireops_events", receive)
            await connection.close()
        async with engine.begin() as cleanup:
            await cleanup.execute(
                text(
                    "TRUNCATE TABLE quarantined_observations, source_status, "
                    "wildfire_incidents, source_observations CASCADE"
                )
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_success_notifications_are_transactional_sorted_and_deduplicated(
    notification_database: tuple[AsyncEngine, list[str]],
) -> None:
    engine, payloads = notification_database
    await _seed_incidents(engine)
    _GatedCommitSession.commit_started = asyncio.Event()
    _GatedCommitSession.allow_commit = asyncio.Event()
    service = _service(engine, session_class=_GatedCommitSession)

    task = asyncio.create_task(service.run_source(_Adapter()))
    await asyncio.wait_for(_GatedCommitSession.commit_started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    assert payloads == []

    _GatedCommitSession.allow_commit.set()
    result = await task
    await _wait_for_payloads(payloads, 3)

    assert result.outcome == "success"
    assert payloads == [
        '{"data":{"incidentId":"00000000-0000-0000-0000-000000000101"},"name":"incident-updated"}',
        '{"data":{"incidentId":"00000000-0000-0000-0000-000000000202"},"name":"incident-updated"}',
        '{"data":{"sourceName":"nws"},"name":"source-status-updated"}',
    ]


@pytest.mark.asyncio
async def test_processing_rollback_releases_only_failure_source_notification(
    notification_database: tuple[AsyncEngine, list[str]],
) -> None:
    engine, payloads = notification_database
    await _seed_incidents(engine)
    _FailFirstCommitSession.commit_attempts = 0
    service = _service(engine, session_class=_FailFirstCommitSession)

    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await service.run_source(_Adapter())
    await _wait_for_payloads(payloads, 1)

    assert payloads == ['{"data":{"sourceName":"nws"},"name":"source-status-updated"}']


@pytest.mark.asyncio
async def test_fetch_failure_commit_notifies_only_its_source_status(
    notification_database: tuple[AsyncEngine, list[str]],
) -> None:
    engine, payloads = notification_database
    result = await _service(engine).run_source(_UnavailableAdapter())
    await _wait_for_payloads(payloads, 1)

    assert result.outcome == "failed"
    assert payloads == ['{"data":{"sourceName":"nws"},"name":"source-status-updated"}']


async def _seed_incidents(engine: AsyncEngine) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False).begin() as session:
        session.add_all(
            [
                WildfireIncidentModel(
                    id=incident_id,
                    status="active",
                    geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
                    first_observed_at=_REFERENCE,
                    last_observed_at=_REFERENCE,
                )
                for incident_id in (_SECOND_INCIDENT, _FIRST_INCIDENT)
            ]
        )


def _service(
    engine: AsyncEngine,
    *,
    session_class: type[AsyncSession] = AsyncSession,
) -> IngestionService:
    factory = async_sessionmaker(
        engine,
        class_=session_class,
        expire_on_commit=False,
    )

    async def refresh_incidents(
        _session: AsyncSession,
        _clusters: tuple[DetectionCluster, ...],
        _spatial_radius_meters: float,
    ) -> None:
        return None

    async def refresh_exposure(
        session: AsyncSession,
        *,
        reference_at: datetime,
        exposure_config: ExposureConfig,
        risk_config: RiskConfig,
        clustering_algorithm_version: str,
    ) -> tuple[UUID, ...]:
        del exposure_config, risk_config, clustering_algorithm_version
        snapshots = [
            IncidentSnapshotModel(
                incident_id=incident_id,
                snapshot_version=1,
                source_versions={},
                incident_state={},
                asset_state=[],
                resource_state=[],
                captured_at=reference_at,
            )
            for incident_id in (_SECOND_INCIDENT, _FIRST_INCIDENT)
        ]
        session.add_all(snapshots)
        await session.flush()
        return snapshots[0].id, snapshots[1].id, snapshots[0].id

    return IngestionService(
        factory,
        ClusteringConfig(1_000.0, 3_600.0, 1, "dbscan-v1"),
        incident_refresher=refresh_incidents,
        exposure_risk_refresher=refresh_exposure,
        clock=lambda: _REFERENCE,
    )


async def _wait_for_payloads(payloads: list[str], count: int) -> None:
    deadline = asyncio.get_running_loop().time() + 1
    while len(payloads) < count and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert len(payloads) == count
