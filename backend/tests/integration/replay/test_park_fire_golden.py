import json
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine

from wildfireops.config import Settings
from wildfireops.db import create_engine, create_session_factory
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.ingestion.worker import build_exposure_config, build_risk_config
from wildfireops.main import create_app
from wildfireops.replay.loader import ReplayLoader
from wildfireops.replay.seed import seed_replay_package


PACKAGE = Path(__file__).parents[4] / "data/replay/park-fire"
RESET = text(
    "TRUNCATE TABLE quarantined_observations, source_status, "
    "idempotency_keys, resource_units, exposed_assets, "
    "wildfire_incidents, source_observations CASCADE"
)


def test_golden_replay_rejects_ordinary_database_before_engine_creation() -> None:
    settings = Settings(
        database_url=(
            "postgresql+asyncpg://wildfireops:wildfireops@db:5432/wildfireops"
        ),
        replay_package=PACKAGE,
    )

    with patch.object(sys.modules[__name__], "create_engine") as engine_factory:
        with pytest.raises(
            RuntimeError,
            match="requires dedicated database 'wildfireops_test'",
        ):
            _golden_engine(settings)

    engine_factory.assert_not_called()


def _golden_engine(settings: Settings) -> AsyncEngine:
    try:
        database = make_url(settings.database_url).database
    except ArgumentError as error:
        raise RuntimeError(
            "golden replay integration test requires a valid dedicated database URL"
        ) from error
    if database != "wildfireops_test":
        raise RuntimeError(
            "golden replay integration test requires dedicated database "
            f"'wildfireops_test'; got {database!r}"
        )
    return create_engine(settings)


async def _reset_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(RESET)


@pytest_asyncio.fixture
async def seeded_replay_app() -> AsyncIterator[FastAPI]:
    settings = Settings(replay_package=PACKAGE)
    loader = ReplayLoader(PACKAGE)
    async with AsyncExitStack() as resources:
        seed_engine = _golden_engine(settings)
        resources.push_async_callback(seed_engine.dispose)
        try:
            await _reset_database(seed_engine)
            await seed_replay_package(
                loader=loader,
                session_factory=create_session_factory(seed_engine),
                clustering_config=ClusteringConfig(
                    spatial_radius_meters=settings.clustering_spatial_radius_meters,
                    temporal_window_seconds=(
                        settings.clustering_temporal_window_seconds
                    ),
                    minimum_points=settings.clustering_minimum_points,
                    algorithm_version=settings.clustering_algorithm_version,
                ),
                exposure_config=build_exposure_config(settings),
                risk_config=build_risk_config(settings),
            )
            app = create_app(settings)
            resources.push_async_callback(app.state.engine.dispose)
            yield app
        finally:
            cleanup_engine = _golden_engine(settings)
            try:
                await _reset_database(cleanup_engine)
            finally:
                await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_park_fire_replay_matches_golden_semantics(
    seeded_replay_app: FastAPI,
) -> None:
    expected = json.loads(PACKAGE.joinpath("golden_outputs.json").read_text())
    loader = ReplayLoader(PACKAGE)
    graph_metadata = loader.manifest.road_graph
    assert graph_metadata is not None
    graph = RoadGraph.load(PACKAGE / graph_metadata.filename)

    async with AsyncClient(
        transport=ASGITransport(app=seeded_replay_app),
        base_url="http://test",
    ) as client:
        summaries = (await _json(client.get("/api/incidents")))["items"]
        details = [
            await _json(client.get(f"/api/incidents/{summary['id']}"))
            for summary in summaries
        ]
        selected = max(details, key=lambda item: item["risk"]["score"])
        assert selected["name"] == "Park Fire"

        baseline_version = await _json(
            client.post(
                f"/api/incidents/{selected['id']}/scenarios",
                headers={"Idempotency-Key": "park-fire-golden-baseline"},
                json={
                    "graphVersion": graph.graph_version,
                    "objective": "minimize-response-time",
                    "name": "Park Fire golden replay",
                    "algorithmConfigVersion": "scenario-v1",
                },
            )
        )
        baseline = await _json(
            client.post(
                f"/api/scenario-versions/{baseline_version['id']}/recommendations",
                headers={"Idempotency-Key": "park-fire-golden-baseline-result"},
                json={"maxResponseMinutes": 30, "maxSolverSeconds": 2},
            )
        )
        baseline_routes = [
            assignment["route"]["edgeIds"] for assignment in baseline["assignments"]
        ]
        assert baseline_routes and all(baseline_routes)
        closed_edge_id = baseline_routes[0][0]

        scenario_version = await _json(
            client.post(
                f"/api/scenarios/{baseline_version['scenarioId']}/versions",
                headers={"Idempotency-Key": "park-fire-golden-close-route"},
                json={
                    "roadClosures": [{"edgeId": closed_edge_id}],
                    "weatherOverrides": [],
                    "resourceOverrides": [],
                },
            )
        )
        scenario = await _json(
            client.post(
                f"/api/scenario-versions/{scenario_version['id']}/recommendations",
                headers={"Idempotency-Key": "park-fire-golden-scenario-result"},
                json={"maxResponseMinutes": 30, "maxSolverSeconds": 2},
            )
        )

    actual: dict[str, Any] = {
        "package_id": loader.manifest.package_id,
        "replay_at": loader.manifest.end_at.isoformat().replace("+00:00", "Z"),
        "incidents": sorted(
            (
                _incident_semantics(
                    detail,
                    selected=detail["id"] == selected["id"],
                )
                for detail in details
            ),
            key=lambda item: item["memberships"],
        ),
        "source_versions": _source_versions(selected["sourceVersions"]),
        "graph": {
            "version": graph.graph_version,
            "edge_count": len(graph.edge_ids),
        },
        "baseline": _recommendation_semantics(baseline),
        "closure_scenario": {
            "closed_edge_id": closed_edge_id,
            "recommendation": _recommendation_semantics(scenario),
        },
    }

    assert all(
        closed_edge_id not in assignment["route"]["edge_ids"]
        for assignment in actual["closure_scenario"]["recommendation"]["assignments"]
    )
    assert _consequential(
        actual["baseline"], actual["closure_scenario"]["recommendation"]
    )
    assert actual == expected


async def _json(request: Any) -> dict[str, Any]:
    response: Response = await request
    assert response.status_code < 400, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _memberships(detail: dict[str, Any]) -> list[str]:
    return sorted(
        f"{item['sourceName']}:{item['sourceRecordId']}"
        for item in detail["detections"]
    )


def _incident_semantics(
    detail: dict[str, Any],
    *,
    selected: bool,
) -> dict[str, Any]:
    return {
        "selected": selected,
        "memberships": _memberships(detail),
        "centroid": detail["geometry"],
        "freshness": detail["freshness"],
        "risk": {
            "score": detail["risk"]["score"],
            "algorithm_version": detail["risk"]["algorithmVersion"],
            "factors": [
                {
                    "name": item["name"],
                    "raw_value": item["rawValue"],
                    "normalized_value": item["normalizedValue"],
                    "weight": item["weight"],
                    "contribution": item["contribution"],
                }
                for item in detail["risk"]["contributions"]
            ],
        },
        "exposed_asset_ids": sorted(
            item["assetId"] for item in detail["exposedAssets"]
        ),
    }


def _source_versions(source_versions: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_inputs": [
            {
                "source_name": item["source_name"],
                "source_version": item["source_version"],
                "latest_observed_at": item["latest_observed_at"],
            }
            for item in source_versions["observation_inputs"]
        ],
        "asset_inputs": source_versions["asset_inputs"],
    }


def _recommendation_semantics(recommendation: dict[str, Any]) -> dict[str, Any]:
    return {
        "solver_status": recommendation["solverStatus"],
        "graph_version": recommendation["graphVersion"],
        "risk_version": recommendation["riskVersion"],
        "algorithm_version": recommendation["algorithmVersion"],
        "assignments": [
            {
                "resource_id": assignment["resourceId"],
                "destination_id": assignment["destinationId"],
                "capacity": assignment["capacity"],
                "travel_minutes": assignment["travelMinutes"],
                "route": {
                    "status": assignment["route"]["status"],
                    "edge_ids": assignment["route"]["edgeIds"],
                    "distance_meters": assignment["route"]["distanceMeters"],
                    "travel_minutes": assignment["route"]["travelMinutes"],
                    "graph_version": assignment["route"]["graphVersion"],
                },
            }
            for assignment in recommendation["assignments"]
        ],
        "uncovered_destination_ids": recommendation["uncoveredDestinationIds"],
        "objective_components": {
            "travel_cost": recommendation["objectiveComponents"]["travelCost"],
            "uncovered_risk_penalty": recommendation["objectiveComponents"][
                "uncoveredRiskPenalty"
            ],
            "objective_value": recommendation["objectiveComponents"]["objectiveValue"],
        },
        "outcome": {
            "weighted_risk_covered": recommendation["outcome"]["weightedRiskCovered"],
            "weighted_risk_uncovered": recommendation["outcome"][
                "weightedRiskUncovered"
            ],
            "total_travel_minutes": recommendation["outcome"]["totalTravelMinutes"],
            "unreachable_destination_ids": recommendation["outcome"][
                "unreachableDestinationIds"
            ],
        },
    }


def _consequential(baseline: dict[str, Any], scenario: dict[str, Any]) -> bool:
    return any(
        baseline[key] != scenario[key]
        for key in (
            "assignments",
            "uncovered_destination_ids",
            "objective_components",
            "outcome",
        )
    )
