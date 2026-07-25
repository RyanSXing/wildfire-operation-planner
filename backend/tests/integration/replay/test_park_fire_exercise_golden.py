import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wildfireops.config import Settings
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
                (item["resourceId"], item["taskId"])
                for item in value["initialAllocation"]["assignments"]
            )
            for value in actual.values()
        }
    ) >= 2
    assert all(value["cascadingDisruption"]["uncoveredTaskIds"] for value in actual.values())
    assert all(
        value["finalOverride"]["operatorOverride"] == {
            "resourceId": "exercise-bus-1",
            "taskId": "shelter-capacity-transport",
        }
        for value in actual.values()
    )
    assert all(
        CLOSED_EDGE_ID not in assignment["route"]["edgeIds"]
        for value in actual.values()
        for assignment in value["cascadingDisruption"]["assignments"]
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
    cascade_session = await _advance(client, initial["session"], f"{objective}-advance-1")
    cascade = await _plan(client, cascade_session, f"{objective}-cascade")
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
    audit = await _request(client.get(f"/api/exercise-sessions/{session['id']}/audit"), 200)
    return {
        "initialAllocation": _plan_semantics(initial["plan"]),
        "cascadingDisruption": _plan_semantics(cascade["plan"]),
        "shelterFieldReport": _plan_semantics(final["plan"]),
        "finalOverride": _plan_semantics(override["plan"]),
        "auditEventTypes": [item["eventType"] for item in audit["items"]],
    }


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


def _plan_semantics(plan: dict[str, Any]) -> dict[str, object]:
    output = plan["outputData"]
    return {
        "inputHash": plan["inputHash"],
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
            else {
                "resourceId": output["operatorOverride"]["resourceId"],
                "taskId": output["operatorOverride"]["taskId"],
            }
        ),
    }
