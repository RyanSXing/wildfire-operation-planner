from datetime import UTC, datetime
from uuid import UUID

import networkx as nx
import pytest
from fastapi import FastAPI
from geoalchemy2.elements import WKTElement
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.main import create_app
from wildfireops.persistence.decision_models import (
    AuditEventModel,
    DecisionActionModel,
    IncidentSnapshotModel,
    RecommendationModel,
    ScenarioModel,
    ScenarioVersionModel,
)
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    IncidentDetectionModel,
    ResourceUnitModel,
    SourceObservationModel,
    WildfireIncidentModel,
)


_REFERENCE = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
_INCIDENT_ID = UUID("00000000-0000-0000-0000-000000001101")


def _road_graph() -> RoadGraph:
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        [
            ("engine-1-node", {"x": -121.60, "y": 39.80}),
            ("engine-2-node", {"x": -121.61, "y": 39.80}),
            ("town-1-node", {"x": -121.64, "y": 39.82}),
            ("town-2-node", {"x": -121.65, "y": 39.83}),
        ]
    )
    for origin, destination, edge_id, minutes in (
        ("engine-1-node", "town-1-node", "e1-t1", 5.0),
        ("engine-1-node", "town-2-node", "e1-t2", 12.0),
        ("engine-2-node", "town-1-node", "e2-t1", 6.0),
        ("engine-2-node", "town-2-node", "e2-t2", 7.0),
    ):
        graph.add_edge(
            origin,
            destination,
            edge_id=edge_id,
            travel_minutes=minutes,
            distance_meters=minutes * 1_000,
        )
    return RoadGraph.from_graph(graph)


async def _seed_decision_flow(session: AsyncSession, graph: RoadGraph) -> UUID:
    fire = SourceObservationModel(
        source_name="firms",
        source_record_id="fire-1",
        observation_kind="fire",
        observed_at=_REFERENCE,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        confidence=0.9,
        intensity=18.0,
        raw_payload={"source_version": "firms-v1"},
    )
    weather = SourceObservationModel(
        source_name="nws",
        source_record_id="weather-1",
        observation_kind="weather",
        observed_at=_REFERENCE,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        wind_speed_mps=5.0,
        wind_direction_degrees=180.0,
        temperature_celsius=30.0,
        raw_payload={"source_version": "nws-v1"},
    )
    incident = WildfireIncidentModel(
        id=_INCIDENT_ID,
        status="active",
        risk_score=50.0,
        geometry=WKTElement("POINT(-121.6 39.8)", srid=4326),
        first_observed_at=_REFERENCE,
        last_observed_at=_REFERENCE,
    )
    resources = (
        ResourceUnitModel(
            resource_id="engine-1",
            resource_type="engine",
            capabilities=["water"],
            capacity=2,
            available=True,
            status="available",
            geometry=WKTElement("POINT(-121.60 39.80)", srid=4326),
            raw_metadata={"simulated": True},
        ),
        ResourceUnitModel(
            resource_id="engine-2",
            resource_type="engine",
            capabilities=["water"],
            capacity=2,
            available=True,
            status="available",
            geometry=WKTElement("POINT(-121.61 39.80)", srid=4326),
            raw_metadata={"simulated": True},
        ),
    )
    assets = (
        ExposedAssetModel(
            asset_id="town-1",
            asset_kind="community",
            name="Town One",
            population=1_000,
            source_name="census",
            source_version="2024",
            geometry=WKTElement("POINT(-121.64 39.82)", srid=4326),
            raw_metadata={
                "demand": {"required_capability": "water", "required_capacity": 2}
            },
        ),
        ExposedAssetModel(
            asset_id="town-2",
            asset_kind="community",
            name="Town Two",
            population=500,
            source_name="census",
            source_version="2024",
            geometry=WKTElement("POINT(-121.65 39.83)", srid=4326),
            raw_metadata={
                "demand": {"required_capability": "water", "required_capacity": 5}
            },
        ),
    )
    session.add_all([fire, weather, incident, *resources, *assets])
    await session.flush()
    session.add(IncidentDetectionModel(incident_id=incident.id, observation_id=fire.id))

    source_versions = {
        "observation_inputs": [
            {
                "source_name": "firms",
                "source_version": None,
                "record_ids": ["fire-1"],
                "latest_observed_at": "2024-07-24T18:30:00Z",
            },
            {
                "source_name": "nws",
                "source_version": None,
                "record_ids": ["weather-1"],
                "latest_observed_at": "2024-07-24T18:30:00Z",
            },
        ],
        "asset_inputs": [{"source_name": "census", "source_version": "2024"}],
    }
    snapshot = IncidentSnapshotModel(
        incident_id=incident.id,
        snapshot_version=1,
        source_versions=source_versions,
        incident_state={
            "status": "active",
            "geometry_geojson": {
                "type": "Point",
                "coordinates": [-121.6, 39.8],
            },
            "first_observed_at": "2024-07-24T18:30:00Z",
            "last_observed_at": "2024-07-24T18:30:00Z",
            "reference_at": "2024-07-24T18:30:00Z",
            "detection_identities": ["firms:fire-1"],
            "clustering_algorithm_version": "spatiotemporal-dbscan-v1",
            "exposure": {"buffer_meters": 10_000.0},
            "risk": {"config_version": "risk-v1", "score": 50.0, "factors": []},
        },
        asset_state=[
            {
                "asset_id": asset.asset_id,
                "asset_kind": asset.asset_kind,
                "name": asset.name,
                "population": asset.population,
                "capacity": None,
                "source_name": asset.source_name,
                "source_version": asset.source_version,
                "geometry_geojson": {
                    "type": "Point",
                    "coordinates": (
                        [-121.64, 39.82]
                        if asset.asset_id == "town-1"
                        else [-121.65, 39.83]
                    ),
                },
                "raw_metadata": asset.raw_metadata,
                "distance_meters": 5_000.0,
                "bearing_degrees": 0.0,
            }
            for asset in assets
        ],
        resource_state=[
            {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "capabilities": ["water"],
                "capacity": 2,
                "available": True,
                "status": "available",
                "geometry_geojson": {
                    "type": "Point",
                    "coordinates": (
                        [-121.60, 39.80]
                        if resource.resource_id == "engine-1"
                        else [-121.61, 39.80]
                    ),
                },
                "raw_metadata": {"simulated": True},
            }
            for resource in resources
        ],
        captured_at=_REFERENCE,
    )
    session.add(snapshot)
    await session.flush()
    scenario = ScenarioModel(
        incident_id=incident.id,
        name="Protect towns",
        objective="Minimize response time",
        author_id="demo-operator",
        algorithm_config_version="scenario-v1",
    )
    session.add(scenario)
    await session.flush()
    version = ScenarioVersionModel(
        scenario_id=scenario.id,
        incident_id=incident.id,
        version=1,
        incident_snapshot_id=snapshot.id,
        graph_version=graph.graph_version,
        created_by="demo-operator",
    )
    session.add(version)
    await session.flush()
    return version.id


def _test_app(db_session: AsyncSession, graph: RoadGraph) -> FastAPI:
    app = create_app()
    assert db_session.bind is not None
    app.state.session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    app.state.graphs = {graph.graph_version: graph}
    app.state.clock = lambda: _REFERENCE
    return app


async def _generate(
    client: AsyncClient,
    version_id: UUID,
    *,
    key: str = "rec-1",
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    response = await client.post(
        f"/api/scenario-versions/{version_id}/recommendations",
        headers={"Idempotency-Key": key},
        json=body or {},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_generate_approve_and_audit_complete_decision_flow(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        generated = await client.post(
            f"/api/scenario-versions/{version_id}/recommendations",
            headers={"Idempotency-Key": "rec-1"},
            json={},
        )

        assert generated.status_code == 201
        recommendation = generated.json()
        recommendation_id = recommendation["id"]
        assert recommendation["assignments"] == [
            {
                "resourceId": "engine-1",
                "destinationId": "town-1",
                "route": {
                    "status": "reachable",
                    "edgeIds": ["e1-t1"],
                    "distanceMeters": 5_000.0,
                    "travelMinutes": 5.0,
                    "graphVersion": graph.graph_version,
                    "closureHash": recommendation["assignments"][0]["route"][
                        "closureHash"
                    ],
                },
                "travelMinutes": 5.0,
                "capacity": 2,
            }
        ]
        assert recommendation["uncoveredDestinationIds"] == ["town-2"]
        assert set(recommendation["objectiveComponents"]) == {
            "travelCost",
            "uncoveredRiskPenalty",
            "objectiveValue",
        }
        assert recommendation["solverStatus"] in {"FEASIBLE", "OPTIMAL"}
        assert recommendation["runtimeMilliseconds"] >= 0
        assert recommendation["algorithmVersion"] == "allocation-v1"
        assert recommendation["graphVersion"] == graph.graph_version
        assert recommendation["riskVersion"] == "risk-v1"
        assert len(recommendation["inputVersion"]) == 64
        assert recommendation["sourceVersions"]["observation_inputs"]
        assert recommendation["explanation"]["status"] == recommendation["solverStatus"]

        approved = await client.post(
            f"/api/recommendations/{recommendation_id}/decisions",
            headers={"Idempotency-Key": "decision-1"},
            json={"action": "approve", "note": "Dispatch approved"},
        )
        assert approved.status_code == 201
        decision = approved.json()
        assert decision["recommendationId"] == recommendation_id
        assert decision["action"] == "approve"
        assert decision["note"] == "Dispatch approved"
        assert decision["assignments"] == recommendation["assignments"]

        audited = await client.get(
            "/api/audit-events",
            params={"recommendationId": recommendation_id},
        )
        audit_detail = await client.get(
            f"/api/audit-events/{audited.json()['items'][0]['id']}"
        )

    assert audited.status_code == 200
    assert audit_detail.status_code == 200
    assert audit_detail.json() == audited.json()["items"][0]
    assert len(audited.json()["items"]) == 1
    event = audited.json()["items"][0]
    assert event["eventType"] == "recommendation.approved"
    assert event["aggregateType"] == "recommendation"
    assert event["aggregateId"] == recommendation_id
    assert event["actorId"] == "demo-operator"
    assert event["note"] == "Dispatch approved"
    assert event["afterState"]["finalPairs"] == [
        {"resourceId": "engine-1", "destinationId": "town-1"}
    ]
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.aggregate_id == UUID(recommendation_id))
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(text("decision_assignments"))
        )
        == 1
    )


@pytest.mark.asyncio
async def test_approve_rejects_a_recommendation_after_a_new_incident_snapshot(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        snapshot = await db_session.scalar(
            select(IncidentSnapshotModel).where(
                IncidentSnapshotModel.incident_id == _INCIDENT_ID
            )
        )
        assert snapshot is not None
        db_session.add(
            IncidentSnapshotModel(
                incident_id=snapshot.incident_id,
                snapshot_version=2,
                source_versions=snapshot.source_versions,
                incident_state={**snapshot.incident_state, "status": "expanded"},
                asset_state=snapshot.asset_state,
                resource_state=snapshot.resource_state,
                captured_at=_REFERENCE,
            )
        )
        await db_session.flush()

        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "stale-decision"},
            json={"action": "approve", "note": "Approve old plan"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "recommendation_stale"
    assert (
        await db_session.scalar(select(func.count()).select_from(DecisionActionModel))
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(AuditEventModel)) == 0
    )


@pytest.mark.asyncio
async def test_generation_rejects_malformed_snapshot_resource_json(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    snapshot = await db_session.scalar(
        select(IncidentSnapshotModel).where(
            IncidentSnapshotModel.incident_id == _INCIDENT_ID
        )
    )
    assert snapshot is not None
    snapshot.resource_state = [
        {key: value for key, value in item.items() if key != "status"}
        for item in snapshot.resource_state
        if isinstance(item, dict)
    ]
    await db_session.flush()
    app = _test_app(db_session, graph)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/scenario-versions/{version_id}/recommendations",
            headers={"Idempotency-Key": "malformed-resource"},
            json={},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "recommendation_inputs_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_inputs",
    (
        [],
        [
            {"source_name": "census", "source_version": "2024"},
            {"source_name": "other", "source_version": "v1"},
        ],
        [{"source_name": "census", "source_version": "2025"}],
        [
            {"source_name": "census", "source_version": "2024"},
            {"source_name": "census", "source_version": "2024"},
        ],
    ),
    ids=("missing", "extra", "mismatched", "duplicate"),
)
async def test_generation_requires_exact_canonical_asset_input_pins(
    db_session: AsyncSession,
    asset_inputs: list[dict[str, object]],
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    snapshot = await db_session.scalar(select(IncidentSnapshotModel))
    assert snapshot is not None
    snapshot.source_versions = {
        **snapshot.source_versions,
        "asset_inputs": asset_inputs,
    }
    await db_session.flush()

    async with AsyncClient(
        transport=ASGITransport(app=_test_app(db_session, graph)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/scenario-versions/{version_id}/recommendations",
            headers={"Idempotency-Key": "asset-pins"},
            json={},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "recommendation_inputs_invalid"


@pytest.mark.asyncio
async def test_generation_reads_only_observations_pinned_by_the_snapshot(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    db_session.add(
        SourceObservationModel(
            source_name="unrelated",
            source_record_id="noise-1",
            observation_kind="fire",
            observed_at=_REFERENCE,
            geometry=WKTElement("POINT(-100 40)", srid=4326),
            confidence=0.1,
            raw_payload={"source_version": "noise-v1"},
        )
    )
    await db_session.flush()
    assert isinstance(db_session.bind, AsyncConnection)
    captured: list[tuple[str, object]] = []

    def capture_observation_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if "ST_X(source_observations.geometry)" in statement:
            captured.append((statement, parameters))

    event.listen(
        db_session.bind.sync_connection,
        "before_cursor_execute",
        capture_observation_sql,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_test_app(db_session, graph)),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/scenario-versions/{version_id}/recommendations",
                headers={"Idempotency-Key": "bounded-observations"},
                json={},
            )
    finally:
        event.remove(
            db_session.bind.sync_connection,
            "before_cursor_execute",
            capture_observation_sql,
        )

    assert response.status_code == 201, response.text
    assert len(captured) == 1
    statement, parameters = captured[0]
    assert "WHERE" in statement.upper()
    assert "source_observations.source_name" in statement
    assert "source_observations.source_record_id" in statement
    assert {"firms", "fire-1", "nws", "weather-1"} <= set(
        str(parameters).replace("'", "").replace("(", "").replace(")", "").split(", ")
    )
    assert "unrelated" not in str(parameters)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "stale_version"),
    (("risk_version", "risk-v0"), ("algorithm_version", "allocation-v0")),
)
async def test_approve_rejects_runtime_algorithm_version_drift(
    db_session: AsyncSession,
    field: str,
    stale_version: str,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        model = await db_session.get(
            RecommendationModel,
            UUID(str(recommendation["id"])),
        )
        assert model is not None
        setattr(model, field, stale_version)
        await db_session.flush()
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": f"stale-{field}"},
            json={"action": "approve", "note": "Dispatch"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "recommendation_stale"


@pytest.mark.asyncio
async def test_approve_rejects_an_unavailable_pinned_graph(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        app.state.graphs = {}
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "missing-graph"},
            json={"action": "approve", "note": "Dispatch"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "recommendation_stale"


@pytest.mark.asyncio
async def test_reject_stores_note_and_audit_without_final_assignments(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "reject-1"},
            json={"action": "reject", "note": "Hold for air support"},
        )
        audited = await client.get(
            "/api/audit-events",
            params={"recommendationId": recommendation["id"]},
        )

    assert response.status_code == 201
    assert response.json()["action"] == "reject"
    assert response.json()["note"] == "Hold for air support"
    assert response.json()["assignments"] == []
    assert audited.json()["items"][0]["eventType"] == "recommendation.rejected"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(text("decision_assignments"))
        )
        == 0
    )


@pytest.mark.asyncio
async def test_edit_uses_persisted_candidate_route_and_capacity(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "edit-1"},
            json={
                "action": "edit",
                "note": "Use the second engine",
                "editedAssignments": [
                    {"resourceId": "engine-2", "destinationId": "town-1"}
                ],
            },
        )

    assert response.status_code == 201
    assert response.json()["action"] == "edit"
    assert response.json()["assignments"] == [
        {
            "resourceId": "engine-2",
            "destinationId": "town-1",
            "route": {
                "status": "reachable",
                "edgeIds": ["e2-t1"],
                "distanceMeters": 6_000.0,
                "travelMinutes": 6.0,
                "graphVersion": graph.graph_version,
                "closureHash": response.json()["assignments"][0]["route"][
                    "closureHash"
                ],
            },
            "travelMinutes": 6.0,
            "capacity": 2,
        }
    ]


@pytest.mark.asyncio
async def test_invalid_edit_is_422_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "invalid-edit"},
            json={
                "action": "edit",
                "note": "Insufficient capacity",
                "editedAssignments": [
                    {"resourceId": "engine-1", "destinationId": "town-2"}
                ],
            },
        )

    assert response.status_code == 422
    assert "capacity" in response.json()["error"]["message"]
    assert (
        await db_session.scalar(select(func.count()).select_from(DecisionActionModel))
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(AuditEventModel)) == 0
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(text("decision_assignments"))
        )
        == 0
    )


@pytest.mark.asyncio
async def test_recommendation_and_decision_idempotency_replay_and_conflict(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await _generate(client, version_id)
        replayed = await _generate(client, version_id)
        recommendation_conflict = await client.post(
            f"/api/scenario-versions/{version_id}/recommendations",
            headers={"Idempotency-Key": "rec-1"},
            json={"maxResponseMinutes": 20},
        )
        decision_body = {"action": "approve", "note": "Dispatch"}
        decided = await client.post(
            f"/api/recommendations/{first['id']}/decisions",
            headers={"Idempotency-Key": "decision-idem"},
            json=decision_body,
        )
        decision_replayed = await client.post(
            f"/api/recommendations/{first['id']}/decisions",
            headers={"Idempotency-Key": "decision-idem"},
            json=decision_body,
        )
        decision_conflict = await client.post(
            f"/api/recommendations/{first['id']}/decisions",
            headers={"Idempotency-Key": "decision-idem"},
            json={"action": "approve", "note": "Changed"},
        )

    assert replayed == first
    assert recommendation_conflict.status_code == 409
    assert recommendation_conflict.json()["error"]["code"] == "idempotency_conflict"
    assert decision_replayed.json() == decided.json()
    assert decision_conflict.status_code == 409
    assert decision_conflict.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_generation_rejects_stale_scenario_and_missing_pinned_input(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    version = await db_session.get(ScenarioVersionModel, version_id)
    assert version is not None
    db_session.add(
        ScenarioVersionModel(
            scenario_id=version.scenario_id,
            incident_id=version.incident_id,
            version=2,
            incident_snapshot_id=version.incident_snapshot_id,
            graph_version=version.graph_version,
            created_by="demo-operator",
        )
    )
    await db_session.flush()
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        stale = await client.post(
            f"/api/scenario-versions/{version_id}/recommendations",
            headers={"Idempotency-Key": "stale-scenario"},
            json={},
        )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "scenario_stale"

    await db_session.execute(
        text(
            "UPDATE incident_snapshots SET source_versions = "
            "jsonb_set(source_versions, '{observation_inputs,0,record_ids}', "
            "'[\"missing\"]'::jsonb)"
        )
    )
    fresh_version = await db_session.scalar(
        select(ScenarioVersionModel).where(ScenarioVersionModel.version == 2)
    )
    assert fresh_version is not None
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        invalid = await client.post(
            f"/api/scenario-versions/{fresh_version.id}/recommendations",
            headers={"Idempotency-Key": "missing-input"},
            json={},
        )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "recommendation_inputs_invalid"


@pytest.mark.asyncio
async def test_scenario_command_routes_create_version_and_require_idempotency(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    body = {
        "graphVersion": graph.graph_version,
        "name": "Second plan",
        "objective": "Protect both towns",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            f"/api/incidents/{_INCIDENT_ID}/scenarios",
            headers={"Idempotency-Key": "scenario-api"},
            json=body,
        )
        replayed = await client.post(
            f"/api/incidents/{_INCIDENT_ID}/scenarios",
            headers={"Idempotency-Key": "scenario-api"},
            json=body,
        )
        versioned = await client.post(
            f"/api/scenarios/{created.json()['scenarioId']}/versions",
            headers={"Idempotency-Key": "scenario-version-api"},
            json={"roadClosures": [{"edgeId": "e1-t1"}]},
        )
        missing_header = await client.post(
            f"/api/scenarios/{created.json()['scenarioId']}/versions",
            json={},
        )
        malformed = await client.post(
            "/api/scenarios/not-a-uuid/versions",
            headers={"Idempotency-Key": "bad-path"},
            json={},
        )
        invalid_weather = await client.post(
            f"/api/scenarios/{created.json()['scenarioId']}/versions",
            headers={"Idempotency-Key": "invalid-weather"},
            json={
                "weatherOverrides": [
                    {"windSpeedMps": 5.0, "windDirectionDegrees": 360.0}
                ]
            },
        )

    assert created.status_code == 201
    assert replayed.json() == created.json()
    assert versioned.status_code == 201
    assert versioned.json()["version"] == 2
    assert versioned.json()["roadClosures"] == [{"edgeId": "e1-t1"}]
    assert missing_header.status_code == 422
    assert missing_header.json()["error"]["code"] == "validation_error"
    assert malformed.status_code == 404
    assert malformed.json()["error"]["code"] == "scenario_not_found"
    assert invalid_weather.status_code == 422
    assert invalid_weather.json()["error"]["code"] == "scenario_invalid"


@pytest.mark.asyncio
async def test_terminal_non_actionable_and_active_resource_conflicts_are_409(
    db_session: AsyncSession,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first = await _generate(client, version_id, key="conflict-rec-1")
        second = await _generate(client, version_id, key="conflict-rec-2")
        approved = await client.post(
            f"/api/recommendations/{first['id']}/decisions",
            headers={"Idempotency-Key": "conflict-decision-1"},
            json={"action": "approve", "note": "First dispatch"},
        )
        terminal = await client.post(
            f"/api/recommendations/{first['id']}/decisions",
            headers={"Idempotency-Key": "different-key"},
            json={"action": "approve", "note": "Second decision"},
        )
        resource_conflict = await client.post(
            f"/api/recommendations/{second['id']}/decisions",
            headers={"Idempotency-Key": "conflict-decision-2"},
            json={"action": "approve", "note": "Competing dispatch"},
        )

    assert approved.status_code == 201
    assert terminal.status_code == 409
    assert terminal.json()["error"]["code"] == "recommendation_already_decided"
    assert resource_conflict.status_code == 409
    assert resource_conflict.json()["error"]["code"] == "resource_already_assigned"

    second_model = await db_session.get(RecommendationModel, UUID(str(second["id"])))
    assert second_model is not None
    second_model.solver_status = "UNKNOWN"
    await db_session.flush()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        non_actionable = await client.post(
            f"/api/recommendations/{second_model.id}/decisions",
            headers={"Idempotency-Key": "non-actionable"},
            json={
                "action": "edit",
                "note": "Try edit",
                "editedAssignments": [
                    {"resourceId": "engine-2", "destinationId": "town-1"}
                ],
            },
        )
    assert non_actionable.status_code == 409
    assert non_actionable.json()["error"]["code"] == "recommendation_not_actionable"


@pytest.mark.asyncio
@pytest.mark.parametrize("note", ["   ", "x" * 2_001])
async def test_every_decision_action_requires_a_bounded_nonblank_note(
    db_session: AsyncSession,
    note: str,
) -> None:
    graph = _road_graph()
    version_id = await _seed_decision_flow(db_session, graph)
    app = _test_app(db_session, graph)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        recommendation = await _generate(client, version_id)
        response = await client.post(
            f"/api/recommendations/{recommendation['id']}/decisions",
            headers={"Idempotency-Key": "invalid-note"},
            json={"action": "reject", "note": note},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "decision_invalid"
    assert (
        await db_session.scalar(select(func.count()).select_from(DecisionActionModel))
        == 0
    )
