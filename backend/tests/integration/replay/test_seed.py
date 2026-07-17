import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.decision.risk import default_risk_config
from wildfireops.domain.observations import SourceObservation
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.ingestion.service import IngestionRun, IngestionService
from wildfireops.persistence.observations import IngestStats, ObservationRepository
from wildfireops.persistence.decision_models import (
    IdempotencyKeyModel,
    IncidentSnapshotModel,
)
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    IncidentDetectionModel,
    QuarantinedObservationModel,
    ResourceUnitModel,
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
)
from wildfireops.replay.build import build_package
from wildfireops.replay.loader import ReplayLoader
from wildfireops.replay.seed import (
    ReplaySeedConflict,
    ReplaySeedError,
    _package_digest,
    _seed_request_hash,
    seed_replay_package,
)
from wildfireops.sources.base import SourceBatch


CLUSTERING = ClusteringConfig(
    spatial_radius_meters=1_000.0,
    temporal_window_seconds=3_600.0,
    minimum_points=2,
    algorithm_version="dbscan-v1",
)
EXPOSURE = ExposureConfig(buffer_meters=10_000.0)
RISK = default_risk_config()


@pytest_asyncio.fixture
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings())
    statement = text(
        "TRUNCATE TABLE quarantined_observations, source_status, "
        "idempotency_keys, resource_units, exposed_assets, "
        "wildfire_incidents, source_observations CASCADE"
    )
    async with engine.begin() as connection:
        await connection.execute(statement)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(statement)
        await engine.dispose()


def _build_synthetic_package(
    tmp_path: Path,
    *,
    variant: str,
    package_id: str = "synthetic-seed-v1",
    fire_intensity: float = 327.4,
) -> ReplayLoader:
    staging = tmp_path / f"staging-{variant}"
    output = tmp_path / f"output-{variant}"
    staging.mkdir()
    staging.joinpath("fire_detections.jsonl").write_text(
        "\n".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"))
            for record in (
                {
                    "observation_type": "fire_detection",
                    "source_name": "nasa_firms",
                    "source_record_id": "fire-a",
                    "observed_at": "2024-07-24T18:12:00Z",
                    "longitude": -121.5000,
                    "latitude": 39.8000,
                    "confidence": 0.75,
                    "intensity": fire_intensity,
                    "raw_payload": {"satellite": "N20"},
                },
                {
                    "observation_type": "fire_detection",
                    "source_name": "nasa_firms",
                    "source_record_id": "fire-b",
                    "observed_at": "2024-07-24T18:18:00Z",
                    "longitude": -121.5005,
                    "latitude": 39.8005,
                    "confidence": 0.8,
                    "intensity": fire_intensity,
                    "raw_payload": {"satellite": "N20"},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    staging.joinpath("weather_observations.jsonl").write_text(
        json.dumps(
            {
                "observation_type": "weather_observation",
                "source_name": "nws",
                "source_record_id": "weather-a",
                "observed_at": "2024-07-24T18:20:00Z",
                "longitude": -121.5010,
                "latitude": 39.8010,
                "wind_speed_mps": 5.2,
                "wind_direction_degrees": 215.0,
                "temperature_celsius": 31.5,
                "raw_payload": {"station": "TEST"},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    staging.joinpath("metadata.json").write_text(
        json.dumps(
            {
                "algorithm_config_version": "test-config-v1",
                "static_data_versions": {
                    "census": "2023-acs5",
                    "nasa_firms": "recorded-test-v1",
                    "nws": "recorded-test-v1",
                    "simulated_resources": "synthetic-v1",
                },
                "source_citations": {
                    "census": "https://www.census.gov/",
                    "nasa_firms": "https://firms.modaps.eosdis.nasa.gov/",
                    "nws": "https://www.weather.gov/documentation/services-web-api",
                    "simulated_resources": "WildfireOps portfolio simulation",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    staging.joinpath("exposed_assets.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-121.51, 39.81]},
                        "properties": {
                            "asset_id": "community-a",
                            "asset_kind": "community",
                            "name": "Community A",
                            "population": 1000,
                            "capacity": None,
                            "source_name": "census",
                            "source_version": "2023-acs5",
                            "raw_metadata": {
                                "demand": {
                                    "required_capability": "water",
                                    "required_capacity": 2,
                                }
                            },
                        },
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    staging.joinpath("resources.json").write_text(
        json.dumps(
            [
                {
                    "resource_id": "engine-a",
                    "resource_type": "engine",
                    "capabilities": ["water"],
                    "capacity": 4,
                    "available": True,
                    "status": "available",
                    "geometry_geojson": {
                        "type": "Point",
                        "coordinates": [-121.51, 39.81],
                    },
                    "raw_metadata": {"simulated": True},
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    build_package(
        source_dir=staging,
        package_id=package_id,
        bbox=(-122.4, 39.2, -120.3, 41.0),
        start_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        end_at=datetime(2024, 7, 24, 18, 30, tzinfo=UTC),
        output=output,
    )
    return ReplayLoader(output)


async def _row_counts(session_factory: async_sessionmaker) -> tuple[int, ...]:
    async with session_factory() as session:
        counts: list[int] = []
        for model in (
            ExposedAssetModel,
            ResourceUnitModel,
            SourceObservationModel,
            QuarantinedObservationModel,
            WildfireIncidentModel,
            IncidentDetectionModel,
            IncidentSnapshotModel,
            SourceStatusModel,
            IdempotencyKeyModel,
        ):
            counts.append(
                int(await session.scalar(select(func.count()).select_from(model)) or 0)
            )
        return tuple(counts)


@pytest.mark.asyncio
async def test_successful_seed_commits_complete_replay_state(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    loader = _build_synthetic_package(tmp_path, variant="successful")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

    result = await seed_replay_package(
        loader=loader,
        session_factory=factory,
        clustering_config=CLUSTERING,
        exposure_config=EXPOSURE,
        risk_config=RISK,
    )

    assert result.status == "seeded"
    assert result.assets_inserted == 1
    assert result.resources_inserted == 1
    assert result.observations_inserted == 3
    assert result.incidents_created > 0
    assert result.snapshots_created > 0
    async with factory() as session:
        asset = await session.scalar(select(ExposedAssetModel))
        resource = await session.scalar(select(ResourceUnitModel))
        observations = (
            await session.scalars(
                select(SourceObservationModel).order_by(
                    SourceObservationModel.source_name,
                    SourceObservationModel.source_record_id,
                )
            )
        ).all()
        incidents = (
            await session.scalars(
                select(WildfireIncidentModel).where(
                    WildfireIncidentModel.status == "active"
                )
            )
        ).all()
        snapshots = (await session.scalars(select(IncidentSnapshotModel))).all()
        statuses = (
            await session.scalars(
                select(SourceStatusModel).order_by(SourceStatusModel.source_name)
            )
        ).all()
        claim = await session.scalar(select(IdempotencyKeyModel))

    assert asset is not None
    assert asset.source_name == "census"
    assert asset.source_version == "2023-acs5"
    assert asset.raw_metadata == {
        "demand": {"required_capability": "water", "required_capacity": 2}
    }
    assert resource is not None
    assert resource.raw_metadata == {"simulated": True}
    assert resource.capabilities == ["water"]
    assert [(item.source_name, item.source_record_id) for item in observations] == [
        ("nasa_firms", "fire-a"),
        ("nasa_firms", "fire-b"),
        ("nws", "weather-a"),
    ]
    assert incidents and all(item.risk_score is not None for item in incidents)
    assert {item.incident_id for item in snapshots} == {item.id for item in incidents}
    assert [item.source_name for item in statuses] == ["nasa_firms", "nws"]
    assert all(item.outcome == "success" for item in statuses)
    assert all(item.last_attempted_at == loader.manifest.end_at for item in statuses)
    assert [item.last_success_at for item in statuses] == [
        datetime(2024, 7, 24, 18, 18, tzinfo=UTC),
        datetime(2024, 7, 24, 18, 20, tzinfo=UTC),
    ]
    assert [
        (
            item.accepted_count,
            item.deduplicated_count,
            item.quarantined_count,
            item.error_message,
        )
        for item in statuses
    ] == [(2, 0, 0, None), (1, 0, 0, None)]
    assert claim is not None
    assert claim.scope == "replay_seed"
    assert claim.key == loader.manifest.package_id
    assert claim.request_hash == _seed_request_hash(
        _package_digest(loader.manifest), CLUSTERING, EXPOSURE, RISK
    )
    assert claim.response_type is None
    assert claim.response_id is None


@pytest.mark.asyncio
async def test_identical_seed_is_a_noop(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    loader = _build_synthetic_package(tmp_path, variant="identical")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    await seed_replay_package(
        loader=loader,
        session_factory=factory,
        clustering_config=CLUSTERING,
        exposure_config=EXPOSURE,
        risk_config=RISK,
    )
    counts = await _row_counts(factory)

    result = await seed_replay_package(
        loader=loader,
        session_factory=factory,
        clustering_config=CLUSTERING,
        exposure_config=EXPOSURE,
        risk_config=RISK,
    )

    assert result.status == "already_seeded"
    assert result.assets_inserted == 0
    assert result.resources_inserted == 0
    assert result.observations_inserted == 0
    assert result.incidents_created == 0
    assert result.snapshots_created == 0
    assert await _row_counts(factory) == counts


@pytest.mark.asyncio
async def test_changed_package_with_same_id_conflicts(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    first = _build_synthetic_package(tmp_path, variant="package-first")
    changed = _build_synthetic_package(
        tmp_path,
        variant="package-changed",
        fire_intensity=400.0,
    )
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    await seed_replay_package(
        loader=first,
        session_factory=factory,
        clustering_config=CLUSTERING,
        exposure_config=EXPOSURE,
        risk_config=RISK,
    )
    counts = await _row_counts(factory)

    with pytest.raises(ReplaySeedConflict):
        await seed_replay_package(
            loader=changed,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    assert await _row_counts(factory) == counts


@pytest.mark.asyncio
async def test_changed_config_conflicts(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    loader = _build_synthetic_package(tmp_path, variant="config")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    await seed_replay_package(
        loader=loader,
        session_factory=factory,
        clustering_config=CLUSTERING,
        exposure_config=EXPOSURE,
        risk_config=RISK,
    )

    with pytest.raises(ReplaySeedConflict):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=ClusteringConfig(
                spatial_radius_meters=2_000.0,
                temporal_window_seconds=3_600.0,
                minimum_points=2,
                algorithm_version="dbscan-v1",
            ),
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )
    with pytest.raises(ReplaySeedConflict):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=ExposureConfig(buffer_meters=20_000.0),
            risk_config=RISK,
        )


def _dirty_model(model: type[object]) -> object:
    point = WKTElement("POINT(-121.5 39.8)", srid=4326)
    if model is SourceObservationModel:
        return SourceObservationModel(
            source_name="existing",
            source_record_id="source-observation",
            observation_kind="fire",
            observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            geometry=point,
            confidence=0.75,
            intensity=1.0,
            raw_payload={},
        )
    if model is QuarantinedObservationModel:
        return QuarantinedObservationModel(
            source_name="existing",
            source_record_id=None,
            validation_reason="synthetic",
            raw_payload={},
        )
    if model is ExposedAssetModel:
        return ExposedAssetModel(
            asset_id="existing-asset",
            asset_kind="community",
            name="Existing",
            population=None,
            capacity=None,
            source_name=None,
            source_version=None,
            geometry=point,
            raw_metadata={},
        )
    if model is ResourceUnitModel:
        return ResourceUnitModel(
            resource_id="existing-resource",
            resource_type="engine",
            capabilities=[],
            capacity=1,
            available=True,
            status="available",
            geometry=point,
            raw_metadata={},
        )
    if model is WildfireIncidentModel:
        return WildfireIncidentModel(
            geometry=point,
            first_observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            last_observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        )
    if model is SourceStatusModel:
        return SourceStatusModel(
            source_name="existing",
            outcome="success",
            last_attempted_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            last_success_at=None,
            accepted_count=0,
            deduplicated_count=0,
            quarantined_count=0,
            error_message=None,
        )
    raise AssertionError(f"unexpected model: {model}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        SourceObservationModel,
        QuarantinedObservationModel,
        ExposedAssetModel,
        ResourceUnitModel,
        WildfireIncidentModel,
        SourceStatusModel,
    ],
)
async def test_dirty_database_refuses_seed(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
    model: type[object],
) -> None:
    loader = _build_synthetic_package(tmp_path, variant=f"dirty-{model.__name__}")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(_dirty_model(model))

    with pytest.raises(ReplaySeedConflict):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(model)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyKeyModel)
                .where(IdempotencyKeyModel.scope == "replay_seed")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_legacy_package_is_refused_before_writing(
    isolated_engine: AsyncEngine,
) -> None:
    loader = ReplayLoader(Path("tests/fixtures/replay-small"))
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

    with pytest.raises(ReplaySeedError):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    assert await _row_counts(factory) == (0, 0, 0, 0, 0, 0, 0, 0, 0)


@pytest.mark.asyncio
async def test_seed_without_clusters_rolls_back(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    loader = _build_synthetic_package(tmp_path, variant="no-clusters")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

    with pytest.raises(ReplaySeedError, match="no incident clusters"):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=ClusteringConfig(
                spatial_radius_meters=1_000.0,
                temporal_window_seconds=3_600.0,
                minimum_points=3,
                algorithm_version="dbscan-v1",
            ),
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    assert await _row_counts(factory) == (0, 0, 0, 0, 0, 0, 0, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refresh_name", ["refresh_incidents", "refresh_exposure_and_risk"]
)
async def test_refresh_failure_rolls_back_all_seed_state(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_name: str,
) -> None:
    async def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("synthetic refresh failure")

    monkeypatch.setattr(f"wildfireops.replay.seed.{refresh_name}", fail)
    loader = _build_synthetic_package(tmp_path, variant=f"failure-{refresh_name}")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

    with pytest.raises(RuntimeError, match="synthetic refresh failure"):
        await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    assert await _row_counts(factory) == (0, 0, 0, 0, 0, 0, 0, 0, 0)


@pytest.mark.asyncio
async def test_concurrent_distinct_seeds_allow_only_one_owner(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    first = _build_synthetic_package(
        tmp_path,
        variant="concurrent-first",
        package_id="synthetic-seed-first",
    )
    second = _build_synthetic_package(
        tmp_path,
        variant="concurrent-second",
        package_id="synthetic-seed-second",
    )
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)

    async def seed(loader: ReplayLoader) -> object:
        return await seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )

    results = await asyncio.gather(seed(first), seed(second), return_exceptions=True)

    assert sum(getattr(item, "status", None) == "seeded" for item in results) == 1
    assert sum(isinstance(item, ReplaySeedConflict) for item in results) == 1
    assert await _row_counts(factory) == (1, 1, 3, 0, 1, 2, 1, 2, 1)


@pytest.mark.asyncio
async def test_seed_waits_for_live_ingestion_without_lock_inversion(
    isolated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    class GatedObservationRepository(ObservationRepository):
        def __init__(self) -> None:
            self.inserted = asyncio.Event()
            self.release = asyncio.Event()

        async def upsert_many(
            self,
            session: AsyncSession,
            observations: Sequence[SourceObservation],
        ) -> IngestStats:
            stats = await super().upsert_many(session, observations)
            self.inserted.set()
            await self.release.wait()
            return stats

    class Adapter:
        source_name = "nasa_firms"

        async def fetch(self) -> SourceBatch:
            return _source_batch(loader)

    loader = _build_synthetic_package(tmp_path, variant="seed-live-lock")
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    repository = GatedObservationRepository()
    ingestion = IngestionService(
        factory,
        CLUSTERING,
        observation_repository=repository,
        exposure_config=EXPOSURE,
        risk_config=RISK,
        clock=lambda: loader.manifest.end_at,
    )
    live_task = asyncio.create_task(ingestion.run_source(Adapter()))
    await asyncio.wait_for(repository.inserted.wait(), timeout=3.0)
    seed_task = asyncio.create_task(
        seed_replay_package(
            loader=loader,
            session_factory=factory,
            clustering_config=CLUSTERING,
            exposure_config=EXPOSURE,
            risk_config=RISK,
        )
    )
    await _wait_for_seed_lock_waiter(isolated_engine)
    repository.release.set()

    live_result, seed_result = await asyncio.gather(
        live_task,
        seed_task,
        return_exceptions=True,
    )

    assert isinstance(live_result, IngestionRun)
    assert live_result.outcome == "success"
    assert isinstance(seed_result, ReplaySeedConflict)
    assert await _row_counts(factory) == (0, 0, 3, 0, 1, 2, 1, 1, 0)


def _source_batch(loader: ReplayLoader) -> SourceBatch:
    return SourceBatch(
        observations=tuple(loader.iter_until(loader.manifest.end_at)),
        failures=(),
        reference_at=loader.manifest.end_at,
    )


async def _wait_for_seed_lock_waiter(engine: AsyncEngine) -> None:
    deadline = asyncio.get_running_loop().time() + 3.0
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype IN ('advisory', 'transactionid') AND NOT granted"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("seed never waited for the live ingestion transaction")
