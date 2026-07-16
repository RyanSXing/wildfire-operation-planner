from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wildfireops.domain.observations import NormalizedObservation
from wildfireops.geospatial.clustering import ClusteringConfig, DetectionCluster
from wildfireops.ingestion.service import IngestionService
from wildfireops.persistence.incidents import refresh_incidents
from wildfireops.persistence.observations import ObservationRepository
from wildfireops.persistence.observed_models import (
    IncidentDetectionModel,
    QuarantinedObservationModel,
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
)
from wildfireops.sources.base import SourceBatch, SourceValidationFailure
from wildfireops.sources.http import SourceUnavailable


class _FakeAdapter:
    source_name = "nasa_firms"

    def __init__(self, batch: SourceBatch) -> None:
        self._batch = batch

    async def fetch(self) -> SourceBatch:
        return self._batch


class _UnavailableAdapter:
    source_name = "nasa_firms"

    async def fetch(self) -> SourceBatch:
        raise SourceUnavailable("nasa_firms", attempts=3, status_code=503)


class _TrackingSession(AsyncSession):
    commit_calls: ClassVar[int] = 0
    rollback_calls: ClassVar[int] = 0

    async def commit(self) -> None:
        type(self).commit_calls += 1
        await super().commit()

    async def rollback(self) -> None:
        type(self).rollback_calls += 1
        await super().rollback()


type IncidentRefresher = Callable[
    [AsyncSession, tuple[DetectionCluster, ...], float], Awaitable[None]
]


def _record() -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-42",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={"satellite": "NOAA-20"},
    )


def _other_record(
    record_id: str,
    *,
    longitude: float = -121.6,
    latitude: float = 39.8,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id=record_id,
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=longitude,
        latitude=latitude,
        confidence=0.9,
        intensity=None,
        raw_payload={"record_id": record_id},
    )


def _batch() -> SourceBatch:
    record = _record()
    return SourceBatch(
        observations=(record, record),
        failures=(
            SourceValidationFailure(
                source_name="nasa_firms",
                reason="invalid FIRMS row: latitude must be a number",
                raw_payload={"latitude": "not-a-number"},
            ),
        ),
    )


def _service(
    db_session: AsyncSession,
    *,
    incident_refresher: IncidentRefresher | None = None,
) -> IngestionService:
    assert db_session.bind is not None
    _TrackingSession.commit_calls = 0
    _TrackingSession.rollback_calls = 0
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=_TrackingSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    kwargs: dict[str, object] = {}
    if incident_refresher is not None:
        kwargs["incident_refresher"] = incident_refresher
    return IngestionService(
        session_factory,
        ClusteringConfig(
            spatial_radius_meters=1_000.0,
            temporal_window_seconds=3_600.0,
            minimum_points=1,
            algorithm_version="dbscan-v1",
        ),
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_run_source_ingests_deduplicates_quarantines_and_commits_once(
    db_session: AsyncSession,
) -> None:
    service = _service(db_session)

    result = await service.run_source(_FakeAdapter(_batch()))

    assert result.source_name == "nasa_firms"
    assert result.accepted == 1
    assert result.deduplicated == 1
    assert result.quarantined == 1
    assert result.outcome == "success"
    assert _TrackingSession.commit_calls == 1
    assert _TrackingSession.rollback_calls == 0
    assert (
        await db_session.scalar(
            select(func.count()).select_from(SourceObservationModel)
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(QuarantinedObservationModel)
        )
        == 1
    )
    quarantine = (await db_session.scalars(select(QuarantinedObservationModel))).one()
    assert quarantine.validation_reason == (
        "invalid FIRMS row: latitude must be a number"
    )
    status = (await db_session.scalars(select(SourceStatusModel))).one()
    assert status.source_name == "nasa_firms"
    assert status.outcome == "success"
    assert status.accepted_count == 1
    assert status.deduplicated_count == 1
    assert status.quarantined_count == 1
    assert status.last_success_at is not None
    assert status.error_message is None
    assert (
        await db_session.scalar(select(func.count()).select_from(WildfireIncidentModel))
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(IncidentDetectionModel)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_run_source_rolls_back_every_write_when_incident_refresh_fails(
    db_session: AsyncSession,
) -> None:
    async def fail_refresh(
        _session: AsyncSession,
        _clusters: tuple[DetectionCluster, ...],
        _spatial_radius_meters: float,
    ) -> None:
        raise RuntimeError("synthetic incident refresh failure")

    service = _service(db_session, incident_refresher=fail_refresh)

    with pytest.raises(RuntimeError, match="synthetic incident refresh failure"):
        await service.run_source(_FakeAdapter(_batch()))

    assert _TrackingSession.commit_calls == 0
    assert _TrackingSession.rollback_calls == 1
    for model in (
        SourceObservationModel,
        QuarantinedObservationModel,
        SourceStatusModel,
        WildfireIncidentModel,
        IncidentDetectionModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_fetch_failure_updates_source_status_and_returns_failed_run(
    db_session: AsyncSession,
) -> None:
    service = _service(db_session)

    result = await service.run_source(_UnavailableAdapter())

    assert result.source_name == "nasa_firms"
    assert result.accepted == 0
    assert result.deduplicated == 0
    assert result.quarantined == 0
    assert result.outcome == "failed"
    assert _TrackingSession.commit_calls == 1
    assert _TrackingSession.rollback_calls == 0
    status = (await db_session.scalars(select(SourceStatusModel))).one()
    assert status.source_name == "nasa_firms"
    assert status.outcome == "failed"
    assert status.last_success_at is None
    assert (
        status.error_message == "nasa_firms unavailable after 3 attempts (status 503)"
    )


@pytest.mark.asyncio
async def test_repeated_ingestion_preserves_incident_identity(
    db_session: AsyncSession,
) -> None:
    service = _service(db_session)
    adapter = _FakeAdapter(_batch())

    first_run = await service.run_source(adapter)
    first_incident_id = (
        await db_session.scalars(select(WildfireIncidentModel.id))
    ).one()
    second_run = await service.run_source(adapter)

    assert first_run.accepted == 1
    assert first_run.deduplicated == 1
    assert second_run.accepted == 0
    assert second_run.deduplicated == 2
    assert (await db_session.scalars(select(WildfireIncidentModel.id))).all() == [
        first_incident_id
    ]
    assert (
        await db_session.scalar(
            select(func.count()).select_from(IncidentDetectionModel)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_refresh_incidents_prefers_member_overlap_before_centroid_distance(
    db_session: AsyncSession,
) -> None:
    alpha = _other_record("alpha")
    bravo = _other_record("bravo", longitude=-121.5995)
    await ObservationRepository().upsert_many(db_session, (alpha, bravo))
    observation_ids = {
        row.source_record_id: row.id
        for row in (
            await db_session.execute(
                select(
                    SourceObservationModel.source_record_id,
                    SourceObservationModel.id,
                )
            )
        ).all()
    }
    overlap_id = UUID("00000000-0000-0000-0000-000000000002")
    nearby_id = UUID("00000000-0000-0000-0000-000000000001")
    overlap_incident = WildfireIncidentModel(
        id=overlap_id,
        geometry=WKTElement("POINT(-120.0 40.8)", srid=4326),
        first_observed_at=alpha.observed_at,
        last_observed_at=alpha.observed_at,
    )
    nearby_incident = WildfireIncidentModel(
        id=nearby_id,
        geometry=WKTElement("POINT(-121.59975 39.8)", srid=4326),
        first_observed_at=alpha.observed_at,
        last_observed_at=alpha.observed_at,
    )
    db_session.add_all([overlap_incident, nearby_incident])
    await db_session.flush()
    db_session.add(
        IncidentDetectionModel(
            incident_id=overlap_id,
            observation_id=observation_ids["alpha"],
        )
    )
    await db_session.flush()

    await refresh_incidents(
        db_session,
        (
            DetectionCluster(
                member_identities=("nasa_firms:alpha", "nasa_firms:bravo"),
                centroid_longitude=-121.59975,
                centroid_latitude=39.8,
            ),
        ),
        1_000.0,
    )
    await db_session.flush()

    assigned_ids = (
        await db_session.scalars(
            select(IncidentDetectionModel.incident_id).order_by(
                IncidentDetectionModel.incident_id
            )
        )
    ).all()
    assert assigned_ids == [overlap_id, overlap_id]


@pytest.mark.asyncio
async def test_refresh_incidents_uses_uuid_string_to_break_distance_ties(
    db_session: AsyncSession,
) -> None:
    alpha = _other_record("alpha")
    await ObservationRepository().upsert_many(db_session, (alpha,))
    lower_id = UUID("00000000-0000-0000-0000-000000000001")
    higher_id = UUID("00000000-0000-0000-0000-000000000002")
    db_session.add_all(
        [
            WildfireIncidentModel(
                id=incident_id,
                geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
                first_observed_at=alpha.observed_at,
                last_observed_at=alpha.observed_at,
            )
            for incident_id in (higher_id, lower_id)
        ]
    )
    await db_session.flush()

    await refresh_incidents(
        db_session,
        (
            DetectionCluster(
                member_identities=("nasa_firms:alpha",),
                centroid_longitude=-121.6,
                centroid_latitude=39.8,
            ),
        ),
        1_000.0,
    )
    await db_session.flush()

    assigned_id = (
        await db_session.scalars(select(IncidentDetectionModel.incident_id))
    ).one()
    assert assigned_id == lower_id


@pytest.mark.asyncio
async def test_refresh_incidents_never_assigns_one_incident_to_two_clusters(
    db_session: AsyncSession,
) -> None:
    alpha = _other_record("alpha", longitude=-121.6005)
    bravo = _other_record("bravo", longitude=-121.5995)
    await ObservationRepository().upsert_many(db_session, (alpha, bravo))
    existing_id = UUID("00000000-0000-0000-0000-000000000001")
    db_session.add(
        WildfireIncidentModel(
            id=existing_id,
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            first_observed_at=alpha.observed_at,
            last_observed_at=alpha.observed_at,
        )
    )
    await db_session.flush()

    await refresh_incidents(
        db_session,
        (
            DetectionCluster(
                member_identities=("nasa_firms:bravo",),
                centroid_longitude=bravo.longitude,
                centroid_latitude=bravo.latitude,
            ),
            DetectionCluster(
                member_identities=("nasa_firms:alpha",),
                centroid_longitude=alpha.longitude,
                centroid_latitude=alpha.latitude,
            ),
        ),
        1_000.0,
    )
    await db_session.flush()

    assigned_ids = (
        await db_session.scalars(
            select(IncidentDetectionModel.incident_id).order_by(
                IncidentDetectionModel.incident_id
            )
        )
    ).all()
    assert len(set(assigned_ids)) == 2
    assert existing_id in assigned_ids
    assert (
        await db_session.scalar(select(func.count()).select_from(WildfireIncidentModel))
        == 2
    )


@pytest.mark.asyncio
async def test_refresh_incidents_supports_the_public_two_argument_interface(
    db_session: AsyncSession,
) -> None:
    await refresh_incidents(db_session, ())

    assert (
        await db_session.scalar(select(func.count()).select_from(WildfireIncidentModel))
        == 0
    )
