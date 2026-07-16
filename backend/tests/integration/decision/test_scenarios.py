import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import networkx as nx
import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.decision.scenarios import IdempotencyConflict, ScenarioService
from wildfireops.decision.scenarios import ScenarioValidationError
from wildfireops.domain.scenarios import (
    ResourceOverride,
    RoadClosure,
    WeatherOverride,
)
from wildfireops.domain.scenario_versions import StoredScenarioVersion
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.persistence.decision_models import (
    IncidentSnapshotModel,
    IdempotencyKeyModel,
    ScenarioResourceOverrideModel,
    ScenarioRoadClosureModel,
    ScenarioVersionModel,
    ScenarioWeatherOverrideModel,
)
from wildfireops.persistence.observed_models import (
    ResourceUnitModel,
    WildfireIncidentModel,
)
from wildfireops.persistence.scenarios import ScenarioRepository


def _road_graph() -> RoadGraph:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "B",
        "C",
        edge_id="BC",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "A",
        "C",
        edge_id="AC",
        travel_minutes=15.0,
        distance_meters=1_200.0,
    )
    return RoadGraph.from_graph(graph)


async def _seed_incident_snapshot(session: AsyncSession) -> tuple[UUID, UUID]:
    observed_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    incident = WildfireIncidentModel(
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
    resource = ResourceUnitModel(
        resource_id="engine-1",
        resource_type="engine",
        capabilities=["water"],
        capacity=4,
        available=True,
        status="available",
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        raw_metadata={"simulated": True},
    )
    session.add_all([incident, resource])
    await session.flush()
    snapshot = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=1,
        source_versions={"observations": "recorded-v1"},
        incident_state={"status": "active"},
        asset_state=[],
        resource_state=[
            {
                "resource_id": "engine-1",
                "available": True,
                "capacity": 4,
            }
        ],
        captured_at=observed_at,
    )
    session.add(snapshot)
    await session.flush()
    return incident.id, snapshot.id


async def _create_scenario(
    session: AsyncSession,
    *,
    graphs: dict[str, RoadGraph] | None = None,
) -> tuple[ScenarioService, StoredScenarioVersion, RoadGraph, UUID]:
    incident_id, snapshot_id = await _seed_incident_snapshot(session)
    roads = _road_graph()
    graph_registry = graphs or {roads.graph_version: roads}
    if roads.graph_version not in graph_registry:
        graph_registry[roads.graph_version] = roads
    service = ScenarioService(
        graphs=graph_registry,
        repository=ScenarioRepository(session),
    )
    version_1 = await service.create(
        incident_id=incident_id,
        graph_version=roads.graph_version,
        name="Protect communities",
        objective="Minimize response time",
        author_id="demo-operator",
        algorithm_config_version="scenario-v1",
        idempotency_key="create-scenario-1",
    )
    return service, version_1, roads, snapshot_id


@pytest.mark.asyncio
async def test_add_version_is_immutable_and_idempotent(
    db_session: AsyncSession,
) -> None:
    service, version_1, _, _ = await _create_scenario(db_session)

    version_2 = await service.add_version(
        scenario_id=UUID(version_1.scenario.scenario_id),
        created_by="demo-operator",
        idempotency_key="close-bc",
        road_closures=(RoadClosure("BC"),),
        weather_overrides=(WeatherOverride(8.0, 225.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )
    replayed = await service.add_version(
        scenario_id=UUID(version_1.scenario.scenario_id),
        created_by="demo-operator",
        idempotency_key="close-bc",
        road_closures=(RoadClosure("BC"),),
        weather_overrides=(WeatherOverride(8.0, 225.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )

    assert version_1.scenario.version == 1
    assert (
        version_1.scenario.incident_snapshot_id
        == version_2.scenario.incident_snapshot_id
    )
    assert version_1.graph_version == version_2.graph_version
    assert version_1.scenario.road_closures == ()
    assert version_1.scenario.weather_overrides == ()
    assert version_1.scenario.resource_overrides == ()
    assert version_2.scenario.version == 2
    assert version_2.scenario.road_closures == (RoadClosure("BC"),)
    assert version_2.scenario.weather_overrides == (WeatherOverride(8.0, 225.0),)
    assert version_2.scenario.resource_overrides == (
        ResourceOverride("engine-1", False),
    )
    assert replayed == version_2

    rows = (
        await db_session.scalars(
            select(ScenarioVersionModel).order_by(ScenarioVersionModel.version)
        )
    ).all()
    assert [row.version for row in rows] == [1, 2]
    assert (
        await db_session.scalars(select(ScenarioRoadClosureModel))
    ).one().scenario_version_id == rows[1].id
    assert (
        await db_session.scalars(select(ScenarioWeatherOverrideModel))
    ).one().scenario_version_id == rows[1].id
    assert (
        await db_session.scalars(select(ScenarioResourceOverrideModel))
    ).one().scenario_version_id == rows[1].id

    with pytest.raises(IdempotencyConflict) as conflict:
        await service.add_version(
            scenario_id=UUID(version_1.scenario.scenario_id),
            created_by="demo-operator",
            idempotency_key="close-bc",
            road_closures=(RoadClosure("AC"),),
            weather_overrides=(WeatherOverride(8.0, 225.0),),
            resource_overrides=(ResourceOverride("engine-1", False),),
        )

    assert conflict.value.code == "idempotency_conflict"


@pytest.mark.asyncio
async def test_overlay_categories_inherit_clear_and_replace_independently(
    db_session: AsyncSession,
) -> None:
    service, version_1, _, _ = await _create_scenario(db_session)
    scenario_id = UUID(version_1.scenario.scenario_id)
    version_2 = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="set-all",
        road_closures=(RoadClosure("BC"),),
        weather_overrides=(WeatherOverride(8.0, 225.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )
    version_3 = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="clear-weather",
        weather_overrides=(),
    )
    version_4 = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="replace-road-clear-resource",
        road_closures=(RoadClosure("AB"),),
        resource_overrides=(),
    )
    replayed_version_2 = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="set-all",
        road_closures=(RoadClosure("BC"),),
        weather_overrides=(WeatherOverride(8.0, 225.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )

    assert version_3.scenario.version == 3
    assert version_3.scenario.road_closures == version_2.scenario.road_closures
    assert version_3.scenario.weather_overrides == ()
    assert (
        version_3.scenario.resource_overrides == version_2.scenario.resource_overrides
    )
    assert version_4.scenario.road_closures == (RoadClosure("AB"),)
    assert version_4.scenario.weather_overrides == ()
    assert version_4.scenario.resource_overrides == ()
    assert replayed_version_2 == version_2


@pytest.mark.asyncio
async def test_newer_snapshot_and_graph_never_rebase_an_existing_scenario(
    db_session: AsyncSession,
) -> None:
    second_graph_data = nx.MultiDiGraph()
    second_graph_data.add_edge(
        "X",
        "Y",
        edge_id="V2-edge",
        travel_minutes=1.0,
        distance_meters=100.0,
    )
    second_graph = RoadGraph.from_graph(second_graph_data)
    service, version_1, roads, snapshot_1_id = await _create_scenario(
        db_session,
        graphs={second_graph.graph_version: second_graph},
    )
    incident_id = version_1.incident_id
    db_session.add(
        ResourceUnitModel(
            resource_id="live-only",
            resource_type="engine",
            capabilities=["water"],
            capacity=2,
            available=True,
            status="available",
            geometry=WKTElement("POINT(-121.5 39.8)", srid=4326),
            raw_metadata={"simulated": True},
        )
    )
    db_session.add(
        IncidentSnapshotModel(
            incident_id=incident_id,
            snapshot_version=2,
            source_versions={"observations": "recorded-v2"},
            incident_state={"status": "active"},
            asset_state=[],
            resource_state=[{"resource_id": "live-only"}],
            captured_at=datetime(2024, 7, 24, 19, tzinfo=UTC),
        )
    )
    await db_session.flush()
    scenario_id = UUID(version_1.scenario.scenario_id)

    version_2 = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="still-s1-v1",
        road_closures=(RoadClosure("BC"),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )

    assert version_2.scenario.incident_snapshot_id == str(snapshot_1_id)
    assert version_2.graph_version == roads.graph_version
    with pytest.raises(ScenarioValidationError, match="pinned graph"):
        await service.add_version(
            scenario_id=scenario_id,
            created_by="demo-operator",
            idempotency_key="wrong-graph-edge",
            road_closures=(RoadClosure("V2-edge"),),
        )
    with pytest.raises(ScenarioValidationError, match="pinned snapshot"):
        await service.add_version(
            scenario_id=scenario_id,
            created_by="demo-operator",
            idempotency_key="live-is-not-snapshot",
            resource_overrides=(ResourceOverride("live-only", False),),
        )


@pytest.mark.asyncio
async def test_semantic_replacement_hash_is_order_independent(
    db_session: AsyncSession,
) -> None:
    service, version_1, _, _ = await _create_scenario(db_session)
    scenario_id = UUID(version_1.scenario.scenario_id)

    first = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="canonical-order",
        road_closures=(RoadClosure("BC"), RoadClosure("AB")),
        weather_overrides=(WeatherOverride(-0.0, -0.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )
    replayed = await service.add_version(
        scenario_id=scenario_id,
        created_by="demo-operator",
        idempotency_key="canonical-order",
        road_closures=(RoadClosure("AB"), RoadClosure("BC")),
        weather_overrides=(WeatherOverride(0.0, 0.0),),
        resource_overrides=(ResourceOverride("engine-1", False),),
    )

    assert replayed == first
    assert first.scenario.road_closures == (
        RoadClosure("AB"),
        RoadClosure("BC"),
    )


@pytest.mark.asyncio
async def test_create_is_idempotent_and_conflicts_on_a_changed_body(
    db_session: AsyncSession,
) -> None:
    service, version_1, roads, _ = await _create_scenario(db_session)

    replayed = await service.create(
        incident_id=version_1.incident_id,
        graph_version=roads.graph_version,
        name="Protect communities",
        objective="Minimize response time",
        author_id="demo-operator",
        algorithm_config_version="scenario-v1",
        idempotency_key="create-scenario-1",
    )

    assert replayed == version_1
    with pytest.raises(IdempotencyConflict):
        await service.create(
            incident_id=version_1.incident_id,
            graph_version=roads.graph_version,
            name="Protect communities",
            objective="Changed objective",
            author_id="demo-operator",
            algorithm_config_version="scenario-v1",
            idempotency_key="create-scenario-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"road_closures": (RoadClosure("BC"), RoadClosure("BC"))},
            "duplicate road closure edge_id",
        ),
        (
            {
                "resource_overrides": (
                    ResourceOverride("engine-1", False),
                    ResourceOverride("engine-1", True),
                )
            },
            "duplicate resource override resource_id",
        ),
        (
            {"weather_overrides": (WeatherOverride(float("nan"), 225.0),)},
            "wind_speed_mps must be a finite number",
        ),
    ],
)
async def test_invalid_replacement_sets_fail_before_claiming_idempotency(
    db_session: AsyncSession,
    changes: dict[str, object],
    message: str,
) -> None:
    service, version_1, _, _ = await _create_scenario(db_session)

    with pytest.raises(ScenarioValidationError, match=message):
        await service.add_version(
            scenario_id=UUID(version_1.scenario.scenario_id),
            created_by="demo-operator",
            idempotency_key="invalid-replacement",
            **changes,  # type: ignore[arg-type]
        )

    assert (
        await db_session.scalar(select(func.count()).select_from(ScenarioVersionModel))
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.key == "invalid-replacement")
        )
        == 0
    )


@pytest_asyncio.fixture
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine(Settings())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE idempotency_keys, resource_units, "
                "wildfire_incidents, source_observations CASCADE"
            )
        )
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE idempotency_keys, resource_units, "
                    "wildfire_incidents, source_observations CASCADE"
                )
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_version_commands_serialize_without_colliding(
    isolated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with factory.begin() as seed_session:
        _, version_1, roads, _ = await _create_scenario(seed_session)
    scenario_id = UUID(version_1.scenario.scenario_id)

    async def add(key: str, edge_id: str) -> StoredScenarioVersion:
        async with factory.begin() as session:
            service = ScenarioService(
                graphs={roads.graph_version: roads},
                repository=ScenarioRepository(session),
            )
            return await service.add_version(
                scenario_id=scenario_id,
                created_by="demo-operator",
                idempotency_key=key,
                road_closures=(RoadClosure(edge_id),),
            )

    first, second = await asyncio.gather(
        add("concurrent-ab", "AB"),
        add("concurrent-bc", "BC"),
    )

    assert sorted([first.scenario.version, second.scenario.version]) == [2, 3]
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ScenarioVersionModel))
            == 3
        )


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_returns_one_version(
    isolated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with factory.begin() as seed_session:
        _, version_1, roads, _ = await _create_scenario(seed_session)
    scenario_id = UUID(version_1.scenario.scenario_id)

    async def add() -> StoredScenarioVersion:
        async with factory.begin() as session:
            service = ScenarioService(
                graphs={roads.graph_version: roads},
                repository=ScenarioRepository(session),
            )
            return await service.add_version(
                scenario_id=scenario_id,
                created_by="demo-operator",
                idempotency_key="same-concurrent-key",
                road_closures=(RoadClosure("BC"),),
            )

    first, second = await asyncio.gather(add(), add())

    assert first == second
    assert first.scenario.version == 2
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ScenarioVersionModel))
            == 2
        )


@pytest.mark.asyncio
async def test_caller_rollback_removes_version_children_and_idempotency_claim(
    isolated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(isolated_engine, expire_on_commit=False)
    async with factory.begin() as seed_session:
        _, version_1, roads, _ = await _create_scenario(seed_session)
    scenario_id = UUID(version_1.scenario.scenario_id)
    async with factory() as session:
        service = ScenarioService(
            graphs={roads.graph_version: roads},
            repository=ScenarioRepository(session),
        )
        await service.add_version(
            scenario_id=scenario_id,
            created_by="demo-operator",
            idempotency_key="rolled-back",
            road_closures=(RoadClosure("BC"),),
        )
        await session.rollback()

    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ScenarioVersionModel))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(ScenarioRoadClosureModel)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyKeyModel)
                .where(IdempotencyKeyModel.key == "rolled-back")
            )
            == 0
        )
