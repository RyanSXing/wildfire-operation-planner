import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.decision.risk import default_risk_config
from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.ingestion.service import IngestionService
from wildfireops.persistence.decision_models import IncidentSnapshotModel
from wildfireops.persistence.exposures import refresh_exposure_and_risk
from wildfireops.persistence.observations import ObservationRepository
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    IncidentDetectionModel,
    ResourceUnitModel,
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
)
from wildfireops.sources.base import SourceBatch


_REFERENCE = datetime(2024, 7, 24, 18, tzinfo=UTC)
_INCIDENT_ID = UUID("00000000-0000-0000-0000-000000000702")


def _fire(
    record_id: str, observed_at: datetime, confidence: float
) -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=-121.6,
        latitude=39.8,
        confidence=confidence,
        intensity=None,
        raw_payload={"record_id": record_id},
    )


def _weather(
    record_id: str,
    observed_at: datetime,
    *,
    direction: float = 270,
) -> WeatherObservation:
    return WeatherObservation(
        source_name="nws",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=-121.6,
        latitude=39.8,
        wind_speed_mps=15,
        wind_direction_degrees=direction,
        temperature_celsius=None,
        raw_payload={"record_id": record_id},
    )


async def _seed_snapshot_inputs(session: AsyncSession) -> None:
    fire_early = _fire("fire-early", _REFERENCE - timedelta(minutes=30), 0.8)
    fire_latest = _fire("fire-latest", _REFERENCE, 1.0)
    weather = _weather("weather-1", _REFERENCE)
    await ObservationRepository().upsert_many(
        session,
        (fire_early, fire_latest, weather),
    )
    ids = {
        row.source_record_id: row.id
        for row in (
            await session.execute(
                select(
                    SourceObservationModel.source_record_id,
                    SourceObservationModel.id,
                )
            )
        ).all()
    }
    session.add(
        WildfireIncidentModel(
            id=_INCIDENT_ID,
            status="active",
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            first_observed_at=fire_early.observed_at,
            last_observed_at=fire_latest.observed_at,
        )
    )
    await session.flush()
    session.add_all(
        [
            IncidentDetectionModel(
                incident_id=_INCIDENT_ID,
                observation_id=ids[record_id],
            )
            for record_id in ("fire-early", "fire-latest")
        ]
    )
    session.add(
        ExposedAssetModel(
            asset_id="community-1",
            asset_kind="community",
            name="Community One",
            population=5_000,
            capacity=None,
            source_name="census",
            source_version="2023-acs5",
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            raw_metadata={"b": 2, "a": 1},
        )
    )
    session.add(
        ResourceUnitModel(
            resource_id="engine-1",
            resource_type="engine",
            capabilities=["water", "medical"],
            capacity=4,
            available=True,
            status="available",
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            raw_metadata={"simulated": True},
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_refresh_persists_exact_canonical_snapshot_and_current_risk(
    db_session: AsyncSession,
) -> None:
    await _seed_snapshot_inputs(db_session)

    snapshot_ids = await refresh_exposure_and_risk(
        db_session,
        reference_at=_REFERENCE,
        exposure_config=ExposureConfig(10_000),
        risk_config=default_risk_config(),
        clustering_algorithm_version="dbscan-v1",
    )
    await db_session.flush()

    assert len(snapshot_ids) == 1
    incident = await db_session.get(WildfireIncidentModel, _INCIDENT_ID)
    assert incident is not None
    assert incident.risk_score == 67.0
    snapshot = (await db_session.scalars(select(IncidentSnapshotModel))).one()
    assert snapshot.id == snapshot_ids[0]
    assert snapshot.snapshot_version == 1
    assert snapshot.captured_at == _REFERENCE
    assert snapshot.source_versions == {
        "observation_inputs": [
            {
                "source_name": "nasa_firms",
                "source_version": None,
                "record_ids": ["fire-early", "fire-latest"],
                "latest_observed_at": "2024-07-24T18:00:00Z",
            },
            {
                "source_name": "nws",
                "source_version": None,
                "record_ids": ["weather-1"],
                "latest_observed_at": "2024-07-24T18:00:00Z",
            },
        ],
        "asset_inputs": [{"source_name": "census", "source_version": "2023-acs5"}],
    }
    assert snapshot.asset_state == [
        {
            "asset_id": "community-1",
            "asset_kind": "community",
            "name": "Community One",
            "population": 5_000,
            "capacity": None,
            "source_name": "census",
            "source_version": "2023-acs5",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "raw_metadata": {"a": 1, "b": 2},
            "distance_meters": 0.0,
            "bearing_degrees": None,
        }
    ]
    assert snapshot.resource_state == [
        {
            "resource_id": "engine-1",
            "resource_type": "engine",
            "capabilities": ["medical", "water"],
            "capacity": 4,
            "available": True,
            "status": "available",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "raw_metadata": {"simulated": True},
        }
    ]
    assert snapshot.incident_state == {
        "status": "active",
        "geometry_geojson": {
            "type": "Point",
            "coordinates": [-121.6, 39.8],
        },
        "first_observed_at": "2024-07-24T17:30:00Z",
        "last_observed_at": "2024-07-24T18:00:00Z",
        "reference_at": "2024-07-24T18:00:00Z",
        "detection_identities": [
            "nasa_firms:fire-early",
            "nasa_firms:fire-latest",
        ],
        "clustering_algorithm_version": "dbscan-v1",
        "exposure": {"buffer_meters": 10_000.0},
        "risk": {
            "config_version": "risk-v1",
            "score": 67.0,
            "factors": [
                {
                    "name": "proximity",
                    "raw": {"buffer": 10_000.0, "nearest_distance": 0.0},
                    "normalized_value": 1.0,
                    "weight": 0.3,
                    "contribution": 30.0,
                },
                {
                    "name": "population",
                    "raw": {
                        "community_count": 1,
                        "population": 5_000,
                        "saturation_population": 10_000.0,
                    },
                    "normalized_value": 0.5,
                    "weight": 0.25,
                    "contribution": 12.5,
                },
                {
                    "name": "critical_facilities",
                    "raw": {"count": 0, "kinds": [], "saturation_count": 5.0},
                    "normalized_value": 0.0,
                    "weight": 0.2,
                    "contribution": 0.0,
                },
                {
                    "name": "wind_alignment",
                    "raw": {
                        "from": 270.0,
                        "max_alignment": 1.0,
                        "saturation_speed": 15.0,
                        "speed": 15.0,
                        "spread": 90.0,
                        "weather_identity": "nws:weather-1",
                    },
                    "normalized_value": 1.0,
                    "weight": 0.15,
                    "contribution": 15.0,
                },
                {
                    "name": "detection_confidence",
                    "raw": {"detection_count": 2, "mean": 0.9},
                    "normalized_value": 0.9,
                    "weight": 0.05,
                    "contribution": 4.5,
                },
                {
                    "name": "source_freshness",
                    "raw": {
                        "fire_age": 0.0,
                        "weather_age": 0.0,
                        "stale_thresholds": {
                            "fire_seconds": 21_600.0,
                            "weather_seconds": 3_600.0,
                        },
                    },
                    "normalized_value": 1.0,
                    "weight": 0.05,
                    "contribution": 5.0,
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_identical_refresh_reuses_snapshot_and_weather_only_change_advances(
    db_session: AsyncSession,
) -> None:
    await _seed_snapshot_inputs(db_session)
    kwargs = {
        "reference_at": _REFERENCE,
        "exposure_config": ExposureConfig(),
        "risk_config": default_risk_config(),
        "clustering_algorithm_version": "dbscan-v1",
    }

    first = await refresh_exposure_and_risk(db_session, **kwargs)
    second = await refresh_exposure_and_risk(db_session, **kwargs)
    later = _REFERENCE + timedelta(minutes=10)
    await ObservationRepository().upsert_many(
        db_session,
        (_weather("weather-2", later, direction=90),),
    )
    third = await refresh_exposure_and_risk(
        db_session,
        **{**kwargs, "reference_at": later},
    )
    await db_session.flush()

    assert first == second
    assert third != first
    snapshots = (
        await db_session.scalars(
            select(IncidentSnapshotModel).order_by(
                IncidentSnapshotModel.snapshot_version
            )
        )
    ).all()
    assert [item.snapshot_version for item in snapshots] == [1, 2]
    assert snapshots[1].source_versions["observation_inputs"][1]["record_ids"] == [
        "weather-2"
    ]


@pytest.mark.asyncio
async def test_refresh_returns_snapshots_in_stable_incident_uuid_order(
    db_session: AsyncSession,
) -> None:
    await _seed_snapshot_inputs(db_session)
    lower_incident_id = UUID("00000000-0000-0000-0000-000000000701")
    second_fire = _fire("second-incident-fire", _REFERENCE, 0.7)
    await ObservationRepository().upsert_many(db_session, (second_fire,))
    second_observation_id = await db_session.scalar(
        select(SourceObservationModel.id).where(
            SourceObservationModel.source_record_id == second_fire.source_record_id
        )
    )
    assert second_observation_id is not None
    db_session.add(
        WildfireIncidentModel(
            id=lower_incident_id,
            status="active",
            geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
            first_observed_at=_REFERENCE,
            last_observed_at=_REFERENCE,
        )
    )
    await db_session.flush()
    db_session.add(
        IncidentDetectionModel(
            incident_id=lower_incident_id,
            observation_id=second_observation_id,
        )
    )
    await db_session.flush()

    snapshot_ids = await refresh_exposure_and_risk(
        db_session,
        reference_at=_REFERENCE,
        exposure_config=ExposureConfig(),
        risk_config=default_risk_config(),
        clustering_algorithm_version="dbscan-v1",
    )

    snapshot_incidents = {
        row.id: row.incident_id
        for row in (
            await db_session.execute(
                select(IncidentSnapshotModel.id, IncidentSnapshotModel.incident_id)
            )
        ).all()
    }
    assert [snapshot_incidents[item] for item in snapshot_ids] == [
        lower_incident_id,
        _INCIDENT_ID,
    ]


@pytest.mark.asyncio
async def test_refresh_leaves_transaction_ownership_with_the_caller(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_snapshot_inputs(db_session)
    commit_spy = AsyncMock(side_effect=AssertionError("refresh must not commit"))
    rollback_spy = AsyncMock(side_effect=AssertionError("refresh must not roll back"))
    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)

    await refresh_exposure_and_risk(
        db_session,
        reference_at=_REFERENCE,
        exposure_config=ExposureConfig(),
        risk_config=default_risk_config(),
        clustering_algorithm_version="dbscan-v1",
    )

    commit_spy.assert_not_awaited()
    rollback_spy.assert_not_awaited()
    assert db_session.in_transaction()


class _Adapter:
    def __init__(self, batch: SourceBatch, source_name: str = "nasa_firms") -> None:
        self._batch = batch
        self.source_name = source_name

    async def fetch(self) -> SourceBatch:
        return self._batch


@pytest.mark.asyncio
async def test_exposure_failure_rolls_back_observations_incidents_and_snapshots(
    db_session: AsyncSession,
) -> None:
    assert db_session.bind is not None
    factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def fail_exposure(*_args: object, **_kwargs: object) -> tuple[UUID, ...]:
        raise RuntimeError("synthetic exposure failure")

    service = IngestionService(
        factory,
        ClusteringConfig(1_000, 3_600, 1, "dbscan-v1"),
        exposure_risk_refresher=fail_exposure,
        clock=lambda: _REFERENCE,
    )

    with pytest.raises(RuntimeError, match="synthetic exposure failure"):
        await service.run_source(
            _Adapter(
                SourceBatch(
                    observations=(_fire("fire", _REFERENCE, 0.9),),
                    failures=(),
                )
            )
        )

    for model in (
        SourceObservationModel,
        WildfireIncidentModel,
        IncidentDetectionModel,
        IncidentSnapshotModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    status = (await db_session.scalars(select(SourceStatusModel))).one()
    assert status.outcome == "failed"
    assert status.error_message == "RuntimeError"


@pytest.mark.asyncio
async def test_repeated_replay_ingestion_reuses_the_exact_snapshot(
    db_session: AsyncSession,
) -> None:
    assert db_session.bind is not None
    factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    service = IngestionService(
        factory,
        ClusteringConfig(1_000, 3_600, 1, "dbscan-v1"),
        clock=lambda: _REFERENCE,
    )
    adapter = _Adapter(
        SourceBatch(
            observations=(
                _fire("replay-fire", _REFERENCE, 0.9),
                _weather("replay-weather", _REFERENCE),
            ),
            failures=(),
            reference_at=_REFERENCE,
        ),
        source_name="replay:test-v1",
    )

    await service.run_source(adapter)
    first_id = await db_session.scalar(select(IncidentSnapshotModel.id))
    await service.run_source(adapter)

    assert first_id is not None
    assert (await db_session.scalars(select(IncidentSnapshotModel.id))).all() == [
        first_id
    ]


@pytest.mark.asyncio
async def test_weather_only_ingestion_advances_the_active_incident_snapshot(
    db_session: AsyncSession,
) -> None:
    assert db_session.bind is not None
    factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    service = IngestionService(
        factory,
        ClusteringConfig(1_000, 3_600, 1, "dbscan-v1"),
        clock=lambda: _REFERENCE,
    )
    await service.run_source(
        _Adapter(
            SourceBatch(
                observations=(_fire("live-fire", _REFERENCE, 0.9),),
                failures=(),
                reference_at=_REFERENCE,
            )
        )
    )
    later = _REFERENCE + timedelta(minutes=10)
    weather_adapter = _Adapter(
        SourceBatch(
            observations=(_weather("new-weather", later, direction=90),),
            failures=(),
            reference_at=later,
        ),
        source_name="nws",
    )

    await service.run_source(weather_adapter)
    await service.run_source(weather_adapter)

    snapshots = (
        await db_session.scalars(
            select(IncidentSnapshotModel).order_by(
                IncidentSnapshotModel.snapshot_version
            )
        )
    ).all()
    assert [item.snapshot_version for item in snapshots] == [1, 2]
    assert snapshots[1].source_versions["observation_inputs"][1]["record_ids"] == [
        "new-weather"
    ]


@pytest_asyncio.fixture
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE wildfire_incidents, source_observations, "
                "exposed_assets, resource_units, source_status CASCADE"
            )
        )
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE wildfire_incidents, source_observations, "
                    "exposed_assets, resource_units, source_status CASCADE"
                )
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_identical_refreshes_reuse_one_version_without_collision(
    isolated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with factory() as seed_session:
        await _seed_snapshot_inputs(seed_session)
        await seed_session.commit()

    async def refresh() -> tuple[UUID, ...]:
        async with factory() as session:
            result = await refresh_exposure_and_risk(
                session,
                reference_at=_REFERENCE,
                exposure_config=ExposureConfig(),
                risk_config=default_risk_config(),
                clustering_algorithm_version="dbscan-v1",
            )
            await session.commit()
            return result

    first, second = await asyncio.gather(refresh(), refresh())

    assert first == second
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(IncidentSnapshotModel)
            )
            == 1
        )
