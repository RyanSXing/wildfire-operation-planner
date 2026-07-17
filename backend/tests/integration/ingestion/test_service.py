import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import ClassVar, cast
from uuid import UUID

import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.domain.observations import (
    NormalizedObservation,
    SourceObservation,
    WeatherObservation,
)
from wildfireops.geospatial.clustering import ClusteringConfig, DetectionCluster
from wildfireops.ingestion.service import IngestionService
from wildfireops.ingestion.worker import ReplayAdapter
from wildfireops.persistence.incidents import (
    load_current_fire_detections,
    refresh_incidents,
)
from wildfireops.persistence.observations import IngestStats, ObservationRepository
from wildfireops.persistence.observed_models import (
    IncidentDetectionModel,
    QuarantinedObservationModel,
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
)
from wildfireops.replay.loader import ReplayLoader
from wildfireops.sources.base import (
    SourceBatch,
    SourceValidationFailure,
)
from wildfireops.sources.http import SourceUnavailable


class _FakeAdapter:
    def __init__(
        self,
        batch: SourceBatch,
        source_name: str = "nasa_firms",
    ) -> None:
        self._batch = batch
        self.source_name = source_name

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


class _FailFirstCommitSession(_TrackingSession):
    commit_attempts: ClassVar[int] = 0

    async def commit(self) -> None:
        type(self).commit_attempts += 1
        if type(self).commit_attempts == 1:
            raise RuntimeError("synthetic commit failure with secret-token")
        await super().commit()


class _FailEveryCommitSession(AsyncSession):
    commit_calls: ClassVar[int] = 0

    async def commit(self) -> None:
        type(self).commit_calls += 1
        raise RuntimeError("synthetic status commit failure")


class _FailingObservationRepository(ObservationRepository):
    async def upsert_many(
        self,
        session: AsyncSession,
        observations: Sequence[SourceObservation],
    ) -> IngestStats:
        del session, observations
        raise RuntimeError("synthetic upsert failure with secret-token")


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
    observed_at: datetime = datetime(2024, 7, 24, 18, tzinfo=UTC),
    longitude: float = -121.6,
    latitude: float = 39.8,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=longitude,
        latitude=latitude,
        confidence=0.9,
        intensity=None,
        raw_payload={"record_id": record_id},
    )


def _weather_record(
    record_id: str,
    *,
    observed_at: datetime,
) -> WeatherObservation:
    return WeatherObservation(
        source_name="nws",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=-121.6,
        latitude=39.8,
        wind_speed_mps=4.0,
        wind_direction_degrees=225.0,
        temperature_celsius=28.0,
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
    observation_repository: ObservationRepository | None = None,
    session_class: type[_TrackingSession] = _TrackingSession,
    temporal_window_seconds: float = 3_600.0,
    clock: Callable[[], datetime] | None = None,
) -> IngestionService:
    assert db_session.bind is not None
    session_class.commit_calls = 0
    session_class.rollback_calls = 0
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=session_class,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    kwargs: dict[str, object] = {}
    if incident_refresher is not None:
        kwargs["incident_refresher"] = incident_refresher
    if observation_repository is not None:
        kwargs["observation_repository"] = observation_repository
    if clock is not None:
        kwargs["clock"] = clock
    return IngestionService(
        session_factory,
        ClusteringConfig(
            spatial_radius_meters=1_000.0,
            temporal_window_seconds=temporal_window_seconds,
            minimum_points=1,
            algorithm_version="dbscan-v1",
        ),
        **kwargs,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE quarantined_observations, source_status, "
                "wildfire_incidents, source_observations CASCADE"
            )
        )
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE quarantined_observations, source_status, "
                    "wildfire_incidents, source_observations CASCADE"
                )
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_source_ingests_deduplicates_quarantines_and_commits_once(
    db_session: AsyncSession,
) -> None:
    service = _service(
        db_session,
        clock=lambda: datetime(2024, 7, 24, 18, tzinfo=UTC),
    )

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

    assert _TrackingSession.commit_calls == 1
    assert _TrackingSession.rollback_calls == 1
    for model in (
        SourceObservationModel,
        QuarantinedObservationModel,
        WildfireIncidentModel,
        IncidentDetectionModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    status = (await db_session.scalars(select(SourceStatusModel))).one()
    assert status.outcome == "failed"
    assert status.error_message == "RuntimeError"
    assert status.last_success_at is None


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
    service = _service(
        db_session,
        clock=lambda: datetime(2024, 7, 24, 18, tzinfo=UTC),
    )
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


@pytest.mark.asyncio
async def test_current_fire_detections_use_an_inclusive_replay_time_window(
    db_session: AsyncSession,
) -> None:
    reference_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    records = (
        _other_record("expired", observed_at=reference_at - timedelta(seconds=3_601)),
        _other_record(
            "lower-bound", observed_at=reference_at - timedelta(seconds=3_600)
        ),
        _other_record("reference", observed_at=reference_at),
        _other_record("future", observed_at=reference_at + timedelta(microseconds=1)),
    )
    await ObservationRepository().upsert_many(db_session, records)

    detections = await load_current_fire_detections(
        db_session,
        reference_at=reference_at,
        temporal_window_seconds=3_600.0,
    )

    assert [item.source_record_id for item in detections] == [
        "lower-bound",
        "reference",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference_at", "temporal_window_seconds"),
    (
        (datetime(2024, 7, 24, 18), 3_600.0),
        (datetime(2024, 7, 24, 14, tzinfo=timezone(timedelta(hours=-4))), 3_600.0),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), 0),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), -1),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), float("inf")),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), float("nan")),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), True),
        (datetime(2024, 7, 24, 18, tzinfo=UTC), 10**400),
        (datetime.min.replace(tzinfo=UTC), 1.0),
    ),
)
async def test_current_fire_detection_window_rejects_invalid_reference_or_duration(
    db_session: AsyncSession,
    reference_at: datetime,
    temporal_window_seconds: object,
) -> None:
    with pytest.raises(ValueError):
        await load_current_fire_detections(
            db_session,
            reference_at=reference_at,
            temporal_window_seconds=cast(float, temporal_window_seconds),
        )


@pytest.mark.asyncio
async def test_replay_reference_excludes_expired_and_future_detections_deterministically(
    db_session: AsyncSession,
) -> None:
    reference_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    stale = _other_record(
        "stale",
        observed_at=reference_at - timedelta(hours=2),
        longitude=-122.2,
    )
    lower_bound = _other_record(
        "lower-bound",
        observed_at=reference_at - timedelta(hours=1),
    )
    future = _other_record(
        "future",
        observed_at=reference_at + timedelta(seconds=1),
        longitude=-120.8,
    )
    await ObservationRepository().upsert_many(
        db_session,
        (stale, lower_bound, future),
    )
    stale_observation_id = await db_session.scalar(
        select(SourceObservationModel.id).where(
            SourceObservationModel.source_record_id == "stale"
        )
    )
    assert stale_observation_id is not None
    stale_incident_id = UUID("00000000-0000-0000-0000-000000000099")
    db_session.add(
        WildfireIncidentModel(
            id=stale_incident_id,
            geometry=WKTElement("POINT(-122.2 39.8)", srid=4326),
            first_observed_at=stale.observed_at,
            last_observed_at=stale.observed_at,
        )
    )
    await db_session.flush()
    db_session.add(
        IncidentDetectionModel(
            incident_id=stale_incident_id,
            observation_id=stale_observation_id,
        )
    )
    await db_session.flush()
    current = _other_record("current", observed_at=reference_at)
    service = _service(db_session)
    adapter = _FakeAdapter(
        SourceBatch(
            observations=(current,),
            failures=(),
            reference_at=reference_at,
        )
    )

    await service.run_source(adapter)
    first_state = await _incident_state(db_session)
    await service.run_source(adapter)
    second_state = await _incident_state(db_session)

    assert first_state == second_state
    assert first_state[stale_incident_id] == ("inactive", ())
    active_memberships = [
        members for status, members in first_state.values() if status == "active"
    ]
    assert active_memberships == [("nasa_firms:current", "nasa_firms:lower-bound")]


@pytest.mark.asyncio
async def test_empty_batch_uses_attempt_time_and_deactivates_expired_incident(
    db_session: AsyncSession,
) -> None:
    stale = _other_record(
        "stale",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
    )
    await ObservationRepository().upsert_many(db_session, (stale,))
    observation_id = await db_session.scalar(select(SourceObservationModel.id))
    assert observation_id is not None
    incident_id = UUID("00000000-0000-0000-0000-000000000098")
    db_session.add(
        WildfireIncidentModel(
            id=incident_id,
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            first_observed_at=stale.observed_at,
            last_observed_at=stale.observed_at,
        )
    )
    await db_session.flush()
    db_session.add(
        IncidentDetectionModel(
            incident_id=incident_id,
            observation_id=observation_id,
        )
    )
    await db_session.flush()

    await _service(db_session).run_source(
        _FakeAdapter(SourceBatch(observations=(), failures=()))
    )

    assert await _incident_state(db_session) == {incident_id: ("inactive", ())}


@pytest.mark.asyncio
async def test_replay_manifest_end_expires_last_record_and_repeats_deterministically(
    db_session: AsyncSession,
) -> None:
    adapter = ReplayAdapter(ReplayLoader(Path("tests/fixtures/replay-small")))
    service = _service(
        db_session,
        temporal_window_seconds=300.0,
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )

    first_run = await service.run_source(adapter)
    first_state = await _incident_state(db_session)
    second_run = await service.run_source(adapter)
    second_state = await _incident_state(db_session)

    assert first_run.accepted == 2
    assert second_run.deduplicated == 2
    assert first_state == second_state == {}
    assert await db_session.scalar(
        select(SourceStatusModel.last_attempted_at).where(
            SourceStatusModel.source_name == "replay:replay-small-v1"
        )
    ) == datetime(2024, 7, 24, 18, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_explicit_replay_reference_ignores_later_persisted_state(
    db_session: AsyncSession,
) -> None:
    reference_at = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
    future = _other_record(
        "future",
        observed_at=reference_at + timedelta(minutes=2),
    )
    await ObservationRepository().upsert_many(db_session, (future,))
    later_operational_time = reference_at + timedelta(hours=1)
    db_session.add(
        SourceStatusModel(
            source_name="later-live-source",
            outcome="success",
            last_attempted_at=later_operational_time,
            last_success_at=later_operational_time,
            accepted_count=1,
            deduplicated_count=0,
            quarantined_count=0,
            error_message=None,
        )
    )
    await db_session.flush()
    replay_record = _other_record(
        "replay-current",
        observed_at=reference_at - timedelta(minutes=2),
    )
    batch = SourceBatch(
        observations=(replay_record,),
        failures=(),
        reference_at=reference_at,
    )

    await _service(
        db_session,
        temporal_window_seconds=300.0,
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    ).run_source(_FakeAdapter(batch, source_name="replay:test"))

    active_memberships = [
        members
        for status, members in (await _incident_state(db_session)).values()
        if status == "active"
    ]
    assert active_memberships == [("nasa_firms:replay-current",)]


@pytest.mark.asyncio
async def test_lagging_weather_and_regressed_clock_do_not_rewind_live_reference(
    db_session: AsyncSession,
) -> None:
    first_reference = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
    clock_values = iter((first_reference, first_reference - timedelta(minutes=10)))
    service = _service(
        db_session,
        temporal_window_seconds=600.0,
        clock=lambda: next(clock_values),
    )
    fire = _other_record(
        "newer-fire",
        observed_at=first_reference - timedelta(minutes=5),
    )
    weather = _weather_record(
        "lagging-weather",
        observed_at=first_reference - timedelta(hours=2),
    )

    await service.run_source(
        _FakeAdapter(SourceBatch(observations=(fire,), failures=()))
    )
    first_state = await _incident_state(db_session)
    await service.run_source(
        _FakeAdapter(
            SourceBatch(observations=(weather,), failures=()),
            source_name="nws",
        )
    )
    second_state = await _incident_state(db_session)

    assert first_state == second_state
    assert [
        members for status, members in second_state.values() if status == "active"
    ] == [("nasa_firms:newer-fire",)]
    assert (
        await db_session.scalar(
            select(SourceStatusModel.last_attempted_at).where(
                SourceStatusModel.source_name == "nws"
            )
        )
        == first_reference
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_now",
    (
        datetime(2024, 7, 24, 18, 30),
        datetime(2024, 7, 24, 14, 30, tzinfo=timezone(-timedelta(hours=4))),
    ),
)
async def test_ingestion_clock_requires_exact_utc(
    db_session: AsyncSession,
    invalid_now: datetime,
) -> None:
    service = _service(db_session, clock=lambda: invalid_now)

    with pytest.raises(ValueError, match="ingestion clock must return UTC"):
        await service.run_source(_FakeAdapter(SourceBatch((), ())))


async def _incident_state(
    session: AsyncSession,
) -> dict[UUID, tuple[str, tuple[str, ...]]]:
    incidents = (
        await session.execute(
            select(WildfireIncidentModel.id, WildfireIncidentModel.status).order_by(
                WildfireIncidentModel.id
            )
        )
    ).all()
    membership_rows = (
        await session.execute(
            select(
                IncidentDetectionModel.incident_id,
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
            )
            .join(
                SourceObservationModel,
                SourceObservationModel.id == IncidentDetectionModel.observation_id,
            )
            .order_by(
                IncidentDetectionModel.incident_id,
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
            )
        )
    ).all()
    memberships: dict[UUID, list[str]] = {}
    for row in membership_rows:
        memberships.setdefault(row.incident_id, []).append(
            f"{row.source_name}:{row.source_record_id}"
        )
    return {
        row.id: (row.status, tuple(memberships.get(row.id, []))) for row in incidents
    }


async def _seed_prior_success_status(session: AsyncSession) -> datetime:
    last_success_at = datetime(2024, 7, 24, 17, tzinfo=UTC)
    session.add(
        SourceStatusModel(
            source_name="nasa_firms",
            outcome="success",
            last_attempted_at=last_success_at,
            last_success_at=last_success_at,
            accepted_count=7,
            deduplicated_count=2,
            quarantined_count=1,
            error_message=None,
            updated_at=last_success_at,
        )
    )
    await session.flush()
    return last_success_at


async def _assert_only_sanitized_failure_status(
    session: AsyncSession,
    *,
    expected_error: str,
    last_success_at: datetime,
) -> None:
    for model in (
        SourceObservationModel,
        QuarantinedObservationModel,
        WildfireIncidentModel,
        IncidentDetectionModel,
    ):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
    rows = (
        await session.execute(
            select(
                SourceStatusModel.source_name,
                SourceStatusModel.outcome,
                SourceStatusModel.last_success_at,
                SourceStatusModel.accepted_count,
                SourceStatusModel.deduplicated_count,
                SourceStatusModel.quarantined_count,
                SourceStatusModel.error_message,
            )
        )
    ).all()
    assert rows == [
        (
            "nasa_firms",
            "failed",
            last_success_at,
            0,
            0,
            0,
            expected_error,
        )
    ]
    assert "secret-token" not in repr(rows)


@pytest.mark.asyncio
async def test_type_separation_failure_rolls_back_and_records_only_failure_status(
    db_session: AsyncSession,
) -> None:
    last_success_at = await _seed_prior_success_status(db_session)
    invalid_batch = SourceBatch(
        observations=(cast(SourceObservation, object()),),
        failures=(),
    )

    with pytest.raises(TypeError, match="unsupported observation type"):
        await _service(db_session).run_source(_FakeAdapter(invalid_batch))

    assert _TrackingSession.rollback_calls == 1
    assert _TrackingSession.commit_calls == 1
    await _assert_only_sanitized_failure_status(
        db_session,
        expected_error="TypeError",
        last_success_at=last_success_at,
    )


@pytest.mark.asyncio
async def test_upsert_failure_rolls_back_and_records_only_failure_status(
    db_session: AsyncSession,
) -> None:
    last_success_at = await _seed_prior_success_status(db_session)
    service = _service(
        db_session,
        observation_repository=_FailingObservationRepository(),
    )

    with pytest.raises(RuntimeError, match="synthetic upsert failure"):
        await service.run_source(_FakeAdapter(_batch()))

    assert _TrackingSession.rollback_calls == 1
    assert _TrackingSession.commit_calls == 1
    await _assert_only_sanitized_failure_status(
        db_session,
        expected_error="RuntimeError",
        last_success_at=last_success_at,
    )


@pytest.mark.asyncio
async def test_clustering_failure_rolls_back_and_records_only_failure_status(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_success_at = await _seed_prior_success_status(db_session)

    def fail_clustering(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic clustering failure with secret-token")

    monkeypatch.setattr(
        "wildfireops.ingestion.service.cluster_detections",
        fail_clustering,
    )

    with pytest.raises(RuntimeError, match="synthetic clustering failure"):
        await _service(db_session).run_source(_FakeAdapter(_batch()))

    assert _TrackingSession.rollback_calls == 1
    assert _TrackingSession.commit_calls == 1
    await _assert_only_sanitized_failure_status(
        db_session,
        expected_error="RuntimeError",
        last_success_at=last_success_at,
    )


@pytest.mark.asyncio
async def test_refresh_failure_rolls_back_and_records_only_failure_status(
    db_session: AsyncSession,
) -> None:
    last_success_at = await _seed_prior_success_status(db_session)

    async def fail_refresh(
        _session: AsyncSession,
        _clusters: tuple[DetectionCluster, ...],
        _spatial_radius_meters: float,
    ) -> None:
        raise RuntimeError("synthetic refresh failure with secret-token")

    with pytest.raises(RuntimeError, match="synthetic refresh failure"):
        await _service(db_session, incident_refresher=fail_refresh).run_source(
            _FakeAdapter(_batch())
        )

    assert _TrackingSession.rollback_calls == 1
    assert _TrackingSession.commit_calls == 1
    await _assert_only_sanitized_failure_status(
        db_session,
        expected_error="RuntimeError",
        last_success_at=last_success_at,
    )


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_and_records_only_failure_status(
    db_session: AsyncSession,
) -> None:
    last_success_at = await _seed_prior_success_status(db_session)
    _FailFirstCommitSession.commit_attempts = 0

    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await _service(
            db_session,
            session_class=_FailFirstCommitSession,
        ).run_source(_FakeAdapter(_batch()))

    assert _FailFirstCommitSession.rollback_calls == 1
    assert _FailFirstCommitSession.commit_attempts == 2
    assert _FailFirstCommitSession.commit_calls == 1
    await _assert_only_sanitized_failure_status(
        db_session,
        expected_error="RuntimeError",
        last_success_at=last_success_at,
    )


@pytest.mark.asyncio
async def test_status_recording_failure_keeps_processing_error_primary(
    db_session: AsyncSession,
) -> None:
    assert db_session.bind is not None
    _FailEveryCommitSession.commit_calls = 0
    main_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=_TrackingSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    status_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=_FailEveryCommitSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    factory_calls = 0

    def session_factory() -> AsyncSession:
        nonlocal factory_calls
        factory_calls += 1
        return main_factory() if factory_calls == 1 else status_factory()

    async def fail_refresh(
        _session: AsyncSession,
        _clusters: tuple[DetectionCluster, ...],
        _spatial_radius_meters: float,
    ) -> None:
        raise LookupError("primary processing failure")

    service = IngestionService(
        session_factory,
        ClusteringConfig(1_000.0, 3_600.0, 1, "dbscan-v1"),
        incident_refresher=fail_refresh,
    )

    with pytest.raises(LookupError, match="primary processing failure"):
        await service.run_source(_FakeAdapter(_batch()))

    assert factory_calls == 2
    assert _FailEveryCommitSession.commit_calls == 1
    for model in (
        SourceObservationModel,
        QuarantinedObservationModel,
        SourceStatusModel,
        WildfireIncidentModel,
        IncidentDetectionModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_source_status_conflict_updates_refresh_updated_at(
    db_session: AsyncSession,
) -> None:
    ancient = datetime(2000, 1, 1, tzinfo=UTC)
    service = _service(db_session)

    await service.run_source(_FakeAdapter(_batch()))
    await db_session.execute(
        update(SourceStatusModel)
        .where(SourceStatusModel.source_name == "nasa_firms")
        .values(updated_at=ancient)
    )
    await db_session.flush()
    await service.run_source(_FakeAdapter(_batch()))
    success_updated_at = await db_session.scalar(
        select(SourceStatusModel.updated_at).where(
            SourceStatusModel.source_name == "nasa_firms"
        )
    )

    assert success_updated_at is not None
    assert success_updated_at > ancient

    await db_session.execute(
        update(SourceStatusModel)
        .where(SourceStatusModel.source_name == "nasa_firms")
        .values(updated_at=ancient)
    )
    await db_session.flush()
    await service.run_source(_UnavailableAdapter())
    failure_updated_at = await db_session.scalar(
        select(SourceStatusModel.updated_at).where(
            SourceStatusModel.source_name == "nasa_firms"
        )
    )

    assert failure_updated_at is not None
    assert failure_updated_at > ancient


@pytest.mark.asyncio
async def test_direct_incident_refresh_acquires_transaction_advisory_lock(
    db_session: AsyncSession,
) -> None:
    await refresh_incidents(db_session, ())

    held_lock_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM pg_locks "
            "WHERE locktype = 'advisory' AND granted "
            "AND pid = pg_backend_pid()"
        )
    )
    assert held_lock_count == 1


@pytest.mark.asyncio
async def test_overlapping_ingestion_recomputes_after_advisory_lock(
    isolated_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(
        isolated_engine,
        expire_on_commit=False,
    )
    first_refreshed = asyncio.Event()
    release_first = asyncio.Event()
    second_fetched = asyncio.Event()
    refresh_calls = 0

    async def gated_refresh(
        session: AsyncSession,
        clusters: tuple[DetectionCluster, ...],
        spatial_radius_meters: float,
    ) -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        await refresh_incidents(session, clusters, spatial_radius_meters)
        if refresh_calls == 1:
            first_refreshed.set()
            await release_first.wait()

    class SignalingAdapter(_FakeAdapter):
        async def fetch(self) -> SourceBatch:
            second_fetched.set()
            return await super().fetch()

    config = ClusteringConfig(1_000.0, 3_600.0, 1, "dbscan-v1")
    first_service = IngestionService(
        session_factory,
        config,
        incident_refresher=gated_refresh,
        clock=lambda: datetime(2024, 7, 24, 18, tzinfo=UTC),
    )
    second_service = IngestionService(
        session_factory,
        config,
        incident_refresher=gated_refresh,
        clock=lambda: datetime(2024, 7, 24, 17, tzinfo=UTC),
    )
    observed_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    first_task = asyncio.create_task(
        first_service.run_source(
            _FakeAdapter(
                SourceBatch(
                    observations=(_other_record("alpha", observed_at=observed_at),),
                    failures=(),
                )
            )
        )
    )
    second_task: asyncio.Task[object] | None = None
    wait_error: BaseException | None = None
    try:
        await asyncio.wait_for(first_refreshed.wait(), timeout=3.0)
        second_task = asyncio.create_task(
            second_service.run_source(
                SignalingAdapter(
                    SourceBatch(
                        observations=(
                            _other_record(
                                "bravo",
                                observed_at=observed_at,
                                longitude=-121.5999,
                            ),
                        ),
                        failures=(),
                    )
                )
            )
        )
        await asyncio.wait_for(second_fetched.wait(), timeout=3.0)
        await _wait_for_advisory_waiter(isolated_engine)
    except BaseException as error:
        wait_error = error
    finally:
        release_first.set()
    assert second_task is not None
    task_results = await asyncio.gather(
        first_task,
        second_task,
        return_exceptions=True,
    )
    if wait_error is not None:
        raise wait_error
    for result in task_results:
        if isinstance(result, BaseException):
            raise result

    async with session_factory() as session:
        state = await _incident_state(session)
    active_memberships = [
        members for status, members in state.values() if status == "active"
    ]
    assert active_memberships == [("nasa_firms:alpha", "nasa_firms:bravo")]
    assert len(state) == 1
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(SourceStatusModel.last_attempted_at).where(
                    SourceStatusModel.source_name == "nasa_firms"
                )
            )
            == observed_at
        )


async def _wait_for_advisory_waiter(engine: AsyncEngine) -> None:
    deadline = asyncio.get_running_loop().time() + 3.0
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype = 'advisory' AND NOT granted"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("second ingestion never waited on an advisory lock")
