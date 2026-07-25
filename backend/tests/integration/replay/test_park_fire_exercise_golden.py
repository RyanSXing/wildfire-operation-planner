import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from wildfireops.application.commands import CommandServiceProvider
from wildfireops.config import Settings
from wildfireops.decision.task_optimizer import TaskOptimizationResult
from wildfireops.db import create_engine, create_session_factory
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.ingestion.worker import build_exposure_config, build_risk_config
from wildfireops.main import create_app
from wildfireops.replay.loader import ReplayLoader
from wildfireops.replay.seed import seed_replay_package


PACKAGE = Path(__file__).parents[4] / "data/replay/park-fire"
DATABASE_URL = "postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test"
RESET = text(
    "TRUNCATE TABLE exercise_events, exercise_plan_runs, exercise_sessions, "
    "quarantined_observations, source_status, idempotency_keys, resource_units, "
    "exposed_assets, wildfire_incidents, source_observations CASCADE"
)
CLOSED_EDGE_ID = "osm-20100003f58c64e9ea9c5b1b82874110b4315c6fe6c421cb4cc484111874e91f"
OBJECTIVES = (
    "fastest-response",
    "protect-critical-services",
    "maximize-population-coverage",
)


async def _reset(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(RESET)


@pytest_asyncio.fixture
async def exercise_app() -> AsyncIterator[FastAPI]:
    settings = Settings(database_url=DATABASE_URL, replay_package=PACKAGE)
    loader = ReplayLoader(PACKAGE)
    async with AsyncExitStack() as resources:
        seed_engine = create_engine(settings)
        resources.push_async_callback(seed_engine.dispose)
        await _reset(seed_engine)
        await seed_replay_package(
            loader=loader,
            session_factory=create_session_factory(seed_engine),
            clustering_config=ClusteringConfig(
                spatial_radius_meters=settings.clustering_spatial_radius_meters,
                temporal_window_seconds=settings.clustering_temporal_window_seconds,
                minimum_points=settings.clustering_minimum_points,
                algorithm_version=settings.clustering_algorithm_version,
            ),
            exposure_config=build_exposure_config(settings),
            risk_config=build_risk_config(settings),
        )
        app = create_app(settings)
        app.state.command_service_provider = CommandServiceProvider(
            session_factory=lambda: app.state.session_factory(),
            graphs=lambda: app.state.graphs,
            settings=app.state.settings,
            exercise_definition=app.state.exercise_definition,
            clock=lambda: app.state.clock(),
            callsign=lambda: "EMBER-GOLDEN",
        )
        resources.push_async_callback(app.state.engine.dispose)
        try:
            yield app
        finally:
            await _reset(seed_engine)


@pytest.mark.asyncio
async def test_park_fire_exercise_matches_golden_semantics(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=exercise_app), base_url="http://test"
    ) as client:
        actual = {
            objective: await _journey(client, objective)
            for objective in OBJECTIVES
        }

    assert len(
        {
            tuple(
                sorted(
                    (item["resourceId"], item["taskId"])
                    for item in value["initialAllocation"]["assignments"]
                )
            )
            for value in actual.values()
        }
    ) >= 2
    assert all(value["cascadingDisruption"]["uncoveredTaskIds"] for value in actual.values())
    assert all(
        value["finalOverride"]["operatorOverride"] == {
            "resourceId": "exercise-bus-1",
            "taskId": "shelter-capacity-transport",
            "beforePlanId": "field",
        }
        for value in actual.values()
    )
    assert all(
        ("exercise-bus-1", "shelter-capacity-transport")
        in {
            (item["resourceId"], item["taskId"])
            for item in value["finalOverride"]["assignments"]
        }
        for value in actual.values()
    )
    assert any(
        CLOSED_EDGE_ID in assignment["route"]["edgeIds"]
        for value in actual.values()
        for assignment in value["initialAllocation"]["assignments"]
    )
    assert all(
        CLOSED_EDGE_ID not in assignment["route"]["edgeIds"]
        for value in actual.values()
        for assignment in value["cascadingDisruption"]["assignments"]
    )
    assert all(
        value["completedSession"]["status"] == "completed" for value in actual.values()
    )
    assert all(
        value["audit"][-1]["eventType"] == "exercise.plan-approved"
        for value in actual.values()
    )
    assert actual == json.loads(PACKAGE.joinpath("exercise_golden_outputs.json").read_text())


async def _journey(client: AsyncClient, objective: str) -> dict[str, object]:
    session = await _request(
        client.post(
            "/api/exercises/park-fire-decision/sessions",
            headers={"Idempotency-Key": f"{objective}-create"},
        ),
        201,
    )
    session = await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/objective",
            headers={"Idempotency-Key": f"{objective}-objective"},
            json={"objective": objective, "expectedVersion": session["version"]},
        ),
        200,
    )
    initial = await _plan(client, session, f"{objective}-initial")
    assert initial["session"]["allowedActions"] == ["select-objective", "advance"]
    cascade_session = await _advance(client, initial["session"], f"{objective}-advance-1")
    cascade = await _plan(client, cascade_session, f"{objective}-cascade")
    assert cascade["session"]["allowedActions"] == ["select-objective", "advance"]
    final_session = await _advance(client, cascade["session"], f"{objective}-advance-2")
    final = await _plan(client, final_session, f"{objective}-final")
    override = await _request(
        client.post(
            f"/api/exercise-sessions/{final_session['id']}/overrides",
            headers={"Idempotency-Key": f"{objective}-override"},
            json={
                "resourceId": "exercise-bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": final["session"]["version"],
            },
        ),
        201,
    )
    aliases = {
        initial["plan"]["id"]: "initial",
        cascade["plan"]["id"]: "cascade",
        final["plan"]["id"]: "field",
        override["plan"]["id"]: "override",
    }
    approved = await _request(
        client.post(
            f"/api/exercise-sessions/{final_session['id']}/decisions",
            headers={"Idempotency-Key": f"{objective}-approve"},
            json={
                "expectedVersion": override["session"]["version"],
                "displayName": "Golden Operator",
                "note": "Approve the validated shelter transport override.",
            },
        ),
        201,
    )
    audit = await _request(client.get(f"/api/exercise-sessions/{session['id']}/audit"), 200)
    return {
        "initialAllocation": _plan_semantics(initial["plan"], aliases),
        "cascadingDisruption": _plan_semantics(cascade["plan"], aliases),
        "shelterFieldReport": _plan_semantics(final["plan"], aliases),
        "finalOverride": _plan_semantics(override["plan"], aliases),
        "completedSession": _session_semantics(approved, aliases),
        "audit": [_audit_semantics(item, aliases) for item in audit["items"]],
    }


async def _completed_session(client: AsyncClient) -> dict[str, Any]:
    session = await _request(
        client.post(
            "/api/exercises/park-fire-decision/sessions",
            headers={"Idempotency-Key": "sandbox-create"},
        ),
        201,
    )
    session = await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/objective",
            headers={"Idempotency-Key": "sandbox-objective"},
            json={"objective": "fastest-response", "expectedVersion": session["version"]},
        ),
        200,
    )
    initial = await _plan(client, session, "sandbox-initial")
    cascade = await _plan(
        client, await _advance(client, initial["session"], "sandbox-advance-1"), "sandbox-cascade"
    )
    final = await _plan(
        client, await _advance(client, cascade["session"], "sandbox-advance-2"), "sandbox-final"
    )
    override = await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/overrides",
            headers={"Idempotency-Key": "sandbox-override"},
            json={
                "resourceId": "exercise-bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": final["session"]["version"],
            },
        ),
        201,
    )
    return await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/decisions",
            headers={"Idempotency-Key": "sandbox-approve"},
            json={
                "expectedVersion": override["session"]["version"],
                "note": "Approve fixture sandbox journey.",
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_park_fire_completed_sandbox_is_autocommit_read_only(
    exercise_app: FastAPI,
) -> None:
    statements: list[str] = []

    def record(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(exercise_app.state.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=exercise_app), base_url="http://test"
        ) as client:
            completed = await _completed_session(client)
            session_id = completed["id"]
            async with exercise_app.state.engine.connect() as connection:
                before = (
                    await connection.execute(
                        text(
                            "SELECT (SELECT count(*) FROM exercise_plan_runs), "
                            "(SELECT count(*) FROM exercise_events), "
                            "(SELECT count(*) FROM exercise_sessions), "
                            "(SELECT count(*) FROM idempotency_keys)"
                        )
                    )
                ).one()
            response = await client.post(
                f"/api/exercise-sessions/{session_id}/sandbox-plans",
                json={
                    "expectedVersion": completed["version"],
                    "checkpointKey": "initial-allocation",
                    "objective": "fastest-response",
                    "windPreset": "historical-calm",
                    "lockedAssignments": [
                        {"resourceId": "exercise-bus-1", "taskId": "evacuate-paradise"},
                        {"resourceId": "exercise-medical-1", "taskId": "support-feather-river"},
                    ],
                },
            )
            async with exercise_app.state.engine.connect() as connection:
                after = (
                    await connection.execute(
                        text(
                            "SELECT (SELECT count(*) FROM exercise_plan_runs), "
                            "(SELECT count(*) FROM exercise_events), "
                            "(SELECT count(*) FROM exercise_sessions), "
                            "(SELECT count(*) FROM idempotency_keys)"
                        )
                    )
                ).one()
    finally:
        event.remove(exercise_app.state.engine.sync_engine, "before_cursor_execute", record)

    assert response.status_code == 200, response.text
    assert response.json()["output"]["status"] == "OPTIMAL"
    assert response.json()["input"]["sandboxControls"]["windPreset"] == "historical-calm"
    assert before == after
    assert not any(statement.strip().upper() in {"BEGIN", "COMMIT"} for statement in statements)


@pytest.mark.asyncio
async def test_park_fire_sandbox_unknown_mismatch_and_coercion_are_read_only(
    exercise_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(request: object) -> TaskOptimizationResult:
        tasks = getattr(request, "tasks")
        resources = getattr(request, "resources")
        return TaskOptimizationResult(
            "UNKNOWN",
            (),
            tuple(item.task_id for item in tasks),
            tuple(item.resource_id for item in resources),
            0,
            0,
            0,
            ("solver-unknown",),
            0,
            "task-allocation-v1",
        )

    body = {
        "checkpointKey": "initial-allocation",
        "objective": "fastest-response",
        "windPreset": "historical-calm",
    }
    async with AsyncClient(
        transport=ASGITransport(app=exercise_app), base_url="http://test"
    ) as client:
        completed = await _completed_session(client)
        session_id = completed["id"]
        async with exercise_app.state.engine.connect() as connection:
            before = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM exercise_plan_runs "
                        "UNION ALL SELECT count(*) FROM exercise_events "
                        "UNION ALL SELECT count(*) FROM idempotency_keys"
                    )
                )
            ).scalars().all()
        monkeypatch.setattr(
            "wildfireops.application.exercise_planning.solve_task_plan", unknown
        )
        unknown_response = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={**body, "expectedVersion": completed["version"]},
        )
        coerced = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={**body, "expectedVersion": True},
        )
        definition = exercise_app.state.exercise_definition.model_copy(
            update={"version": "mismatch"}
        )
        exercise_app.state.command_service_provider = CommandServiceProvider(
            session_factory=lambda: exercise_app.state.session_factory(),
            graphs=lambda: exercise_app.state.graphs,
            settings=exercise_app.state.settings,
            exercise_definition=definition,
            clock=lambda: exercise_app.state.clock(),
            callsign=lambda: "EMBER-GOLDEN",
        )
        mismatch = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={**body, "expectedVersion": completed["version"]},
        )
        async with exercise_app.state.engine.connect() as connection:
            after = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM exercise_plan_runs "
                        "UNION ALL SELECT count(*) FROM exercise_events "
                        "UNION ALL SELECT count(*) FROM idempotency_keys"
                    )
                )
            ).scalars().all()

    assert unknown_response.status_code == 200, unknown_response.text
    assert unknown_response.json()["output"]["status"] == "UNKNOWN"
    assert coerced.status_code == 422, coerced.text
    assert mismatch.status_code == 404, mismatch.text
    assert before == after


async def _plan(client: AsyncClient, session: dict[str, Any], key: str) -> dict[str, Any]:
    return await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/plans",
            headers={"Idempotency-Key": key},
            json={"expectedVersion": session["version"]},
        ),
        201,
    )


async def _advance(client: AsyncClient, session: dict[str, Any], key: str) -> dict[str, Any]:
    return await _request(
        client.post(
            f"/api/exercise-sessions/{session['id']}/advance",
            headers={"Idempotency-Key": key},
            json={"expectedVersion": session["version"]},
        ),
        200,
    )


async def _request(request: Any, status: int) -> dict[str, Any]:
    response = await request
    assert response.status_code == status, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _plan_semantics(
    plan: dict[str, Any], aliases: dict[str, str]
) -> dict[str, object]:
    output = _normalize_links(plan["outputData"], aliases)
    assert isinstance(output, dict)
    return {
        "inputHash": plan["inputHash"],
        "versions": output["versions"],
        "tasks": [
            {"taskId": item["taskId"], "penalty": item["penalty"]}
            for item in plan["inputData"]["tasks"]
        ],
        "assignments": [
            {
                "resourceId": item["resourceId"],
                "taskId": item["taskId"],
                "route": {"edgeIds": item["route"]["edgeIds"]},
            }
            for item in output["assignments"]
        ],
        "coveredTaskIds": output["coveredTaskIds"],
        "uncoveredTaskIds": output["uncoveredTaskIds"],
        "objectiveComponents": output["objectiveComponents"],
        "bindingConstraints": output["bindingConstraints"],
        "causalCodes": [item["code"] for item in output["explanation"]["changes"]],
        "consequences": plan["inputData"]["consequences"],
        "operatorOverride": (
            None
            if output.get("operatorOverride") is None
            else output["operatorOverride"]
        ),
    }


def _audit_semantics(
    event: dict[str, Any], aliases: dict[str, str]
) -> dict[str, object]:
    return {
        "eventType": event["eventType"],
        "actorCallsign": event["actorCallsign"],
        "displayName": event["displayName"],
        "expectedSessionVersion": event["expectedSessionVersion"],
        "resultingSessionVersion": event["resultingSessionVersion"],
        "beforeState": _session_semantics(event["beforeState"], aliases),
        "afterState": _session_semantics(event["afterState"], aliases),
        "inputs": _normalize_links(event["inputs"], aliases),
        "note": event["note"],
    }


def _session_semantics(
    state: dict[str, Any], aliases: dict[str, str]
) -> dict[str, object]:
    result = dict(state)
    result.pop("id", None)
    result.pop("callsign", None)
    return _normalize_links(result, aliases)


def _normalize_links(value: object, aliases: dict[str, str]) -> object:
    if isinstance(value, dict):
        return {
            key: (
                _link_alias(item, aliases)
                if key
                in {
                    "planId",
                    "acceptedPlanId",
                    "beforePlanId",
                    "visiblePlanId",
                    "lastPlanId",
                }
                else _normalize_links(item, aliases)
            )
            for key, item in value.items()
            if key != "_responseProjection"
        }
    if isinstance(value, list):
        return [_normalize_links(item, aliases) for item in value]
    return value


def _link_alias(value: object, aliases: dict[str, str]) -> str | None:
    if value is None:
        return None
    assert isinstance(value, str), "plan linkage must be a UUID string"
    assert value in aliases, f"unknown plan linkage UUID: {value}"
    return aliases[value]


def test_link_normalization_rejects_unknown_uuid() -> None:
    with pytest.raises(AssertionError, match="unknown plan linkage UUID"):
        _normalize_links({"planId": "missing"}, {})
