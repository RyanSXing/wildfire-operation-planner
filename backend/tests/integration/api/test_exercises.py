import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.unit.application.test_exercise_planning import definition, graph
from wildfireops.application.commands import CommandServiceProvider
from wildfireops.config import Settings
from wildfireops.decision.task_optimizer import TaskOptimizationResult
from wildfireops.main import create_app
from wildfireops.persistence.exercises import ExerciseRepository
from wildfireops.replay.exercise import (
    ExerciseDefinition,
    _canonicalize,
    exercise_definition_digest,
)


NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
SAFETY_STATEMENT = (
    "Portfolio decision exercise only. Historical inputs are combined with "
    "simulated operational assumptions. Do not use for emergency or "
    "life-safety decisions."
)


TEST_DATABASE_URL = "postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test"
_RESET = text(
    "TRUNCATE TABLE exercise_events, exercise_plan_runs, exercise_sessions, "
    "idempotency_keys CASCADE"
)


@pytest_asyncio.fixture
async def exercise_app() -> AsyncIterator[FastAPI]:
    app = create_app(Settings(database_url=TEST_DATABASE_URL))
    exercise = _test_definition()
    road_graph = graph()
    app.state.clock = lambda: NOW
    app.state.graphs = {road_graph.graph_version: road_graph}
    app.state.exercise_definition = exercise
    app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: app.state.session_factory(),
        graphs=lambda: app.state.graphs,
        settings=app.state.settings,
        exercise_definition=exercise,
        clock=lambda: app.state.clock(),
        callsign=lambda: "EMBER-101",
    )
    try:
        async with app.state.engine.begin() as connection:
            await connection.execute(_RESET)
        yield app
    finally:
        async with app.state.engine.begin() as connection:
            await connection.execute(_RESET)
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_create_and_read_exercise_session(exercise_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=exercise_app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/exercises/park-fire-decision/sessions",
            headers={"Idempotency-Key": "create-session-1"},
        )

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["exerciseId"] == "park-fire-decision"
        assert body["definitionDigest"] == exercise_definition_digest(_test_definition())
        assert body["status"] == "active"
        assert body["version"] == 1
        assert body["allowedActions"] == ["select-objective"]

        replay = await client.post(
            "/api/exercises/park-fire-decision/sessions",
            headers={"Idempotency-Key": "create-session-1"},
        )

        restored = await client.get(f"/api/exercise-sessions/{body['id']}")

    assert replay.status_code == 201, replay.text
    assert replay.json() == body
    assert restored.status_code == 200, restored.text
    assert restored.json() == body


@pytest.mark.asyncio
async def test_unconfigured_exercise_maps_metadata_and_create_to_404() -> None:
    app = create_app(Settings(database_url=TEST_DATABASE_URL))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            metadata = await client.get("/api/exercises/park-fire-decision")
            created = await client.post(
                "/api/exercises/park-fire-decision/sessions",
                headers={"Idempotency-Key": "unconfigured"},
            )
    finally:
        await app.state.engine.dispose()

    assert metadata.status_code == created.status_code == 404
    assert metadata.json()["error"]["code"] == "exercise_not_found"
    assert created.json()["error"]["code"] == "exercise_not_found"


async def _create(client: AsyncClient, key: str = "create") -> dict[str, object]:
    response = await client.post(
        "/api/exercises/park-fire-decision/sessions",
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _objective(
    client: AsyncClient, session: dict[str, object], key: str = "objective"
) -> dict[str, object]:
    response = await client.post(
        f"/api/exercise-sessions/{session['id']}/objective",
        headers={"Idempotency-Key": key},
        json={"objective": "fastest-response", "expectedVersion": session["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _plan(
    client: AsyncClient, session: dict[str, object], key: str = "plan"
) -> dict[str, object]:
    response = await client.post(
        f"/api/exercise-sessions/{session['id']}/plans",
        headers={"Idempotency-Key": key},
        json={"expectedVersion": session["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _advance(
    client: AsyncClient, session: dict[str, object], key: str
) -> dict[str, object]:
    response = await client.post(
        f"/api/exercise-sessions/{session['id']}/advance",
        headers={"Idempotency-Key": key},
        json={"expectedVersion": session["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _complete(client: AsyncClient) -> dict[str, object]:
    selected = await _objective(client, await _create(client))
    initial = await _plan(client, selected)
    cascade = await _advance(client, initial["session"], "advance-initial")
    cascade_plan = await _plan(client, cascade, "cascade-plan")
    final = await _advance(client, cascade_plan["session"], "advance-cascade")
    planned = await _plan(client, final, "final-plan")
    overridden = await client.post(
        f"/api/exercise-sessions/{final['id']}/overrides",
        headers={"Idempotency-Key": "override"},
        json={
            "resourceId": "bus-1",
            "taskId": "shelter-capacity-transport",
            "expectedVersion": planned["session"]["version"],
        },
    )
    assert overridden.status_code == 201, overridden.text
    completed = await client.post(
        f"/api/exercise-sessions/{final['id']}/decisions",
        headers={"Idempotency-Key": "approve"},
        json={
            "expectedVersion": overridden.json()["session"]["version"],
            "note": "Approve the checked shelter transport.",
        },
    )
    assert completed.status_code == 201, completed.text
    return completed.json()


async def _sandbox_counts(
    app: FastAPI, session_id: str
) -> tuple[int, int, int, int, int]:
    async with app.state.engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM exercise_plan_runs), "
                    "(SELECT count(*) FROM exercise_events), "
                    "(SELECT count(*) FROM exercise_sessions), "
                    "(SELECT count(*) FROM idempotency_keys), "
                    "(SELECT version FROM exercise_sessions WHERE id = :session_id)"
                ),
                {"session_id": session_id},
            )
        ).one()
    return tuple(int(value) for value in row)


def _journey_definition() -> ExerciseDefinition:
    value = _canonicalize(_test_definition())
    assert isinstance(value, dict)
    clearing = value["checkpoints"][1]["tasks"][1]
    assert isinstance(clearing, dict)
    clearing["taskId"] = "clear-primary-corridor"
    clearing["incidentKey"] = "park-fire"
    clearing["assetId"] = "park-asset"
    clearing["basePriority"] = 100
    return ExerciseDefinition.model_validate(value)


def _sandbox_definition() -> ExerciseDefinition:
    value = _canonicalize(_journey_definition())
    assert isinstance(value, dict)
    value["sandbox"] = {
        "checkpointKeys": ["cascade"],
        "closureEdgeIds": ["edge-32"],
        "windPresets": {
            "strong-northeast": {
                "windSpeedMps": 12,
                "windDirectionDegrees": 45,
            }
        },
        "priorityMultipliers": {"standard": 1, "elevated": 2, "urgent": 3},
    }
    return ExerciseDefinition.model_validate(value)


def _test_definition() -> ExerciseDefinition:
    value = _canonicalize(definition())
    assert isinstance(value, dict)
    value["safetyStatement"] = SAFETY_STATEMENT
    return ExerciseDefinition.model_validate(value)


@pytest.mark.asyncio
async def test_metadata_plainly_discloses_historical_and_exercise_provenance(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        response = await client.get("/api/exercises/park-fire-decision")

    assert response.status_code == 200, response.text
    metadata = response.json()
    assert metadata["safetyStatement"] == SAFETY_STATEMENT
    assert metadata["objectives"] == [
        "fastest-response",
        "maximize-population-coverage",
        "protect-critical-services",
    ]
    assert {
        item["assetId"]: {
            key: item[key]
            for key in (
                "sourceName",
                "sourceVersion",
                "sourceRecordId",
                "citationUrl",
                "provenance",
            )
        }
        for item in metadata["assets"]
    } == {
        "park-asset": {
            "sourceName": "census",
            "sourceVersion": "v1",
            "sourceRecordId": "park",
            "citationUrl": "https://example.test/park",
            "provenance": "historical",
        },
        "spot-asset": {
            "sourceName": "census",
            "sourceVersion": "v1",
            "sourceRecordId": "spot",
            "citationUrl": "https://example.test/spot",
            "provenance": "historical",
        },
        "shelter-asset": {
            "sourceName": "census",
            "sourceVersion": "v1",
            "sourceRecordId": "shelter",
            "citationUrl": "https://example.test/shelter",
            "provenance": "historical",
        },
    }
    assert {
        item["resourceId"]: item["provenance"] for item in metadata["resources"]
    } == {"engine-1": "exercise", "bus-1": "exercise"}


@pytest.mark.asyncio
async def test_objective_requires_expected_version_and_idempotency_key(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        created = await _create(client)
        missing_header = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            json={"objective": "fastest-response", "expectedVersion": 1},
        )
        missing_version = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": "objective"},
            json={"objective": "fastest-response"},
        )

    assert missing_header.status_code == 422
    assert missing_version.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "body"),
    [
        ("objective", {"objective": "fastest-response", "expectedVersion": True}),
        ("plans", {"expectedVersion": "1"}),
        ("advance", {"expectedVersion": True}),
        (
            "overrides",
            {
                "resourceId": "bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": "1",
            },
        ),
        ("decisions", {"note": "Approve", "expectedVersion": True}),
    ],
)
async def test_command_schemas_reject_coerced_expected_version(
    exercise_app: FastAPI, suffix: str, body: dict[str, object]
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        created = await _create(client)
        response = await client.post(
            f"/api/exercise-sessions/{created['id']}/{suffix}",
            headers={"Idempotency-Key": f"strict-{suffix}"},
            json=body,
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "body"),
    [
        (
            "objective",
            {"objective": "fastest-response", "expectedVersion": 1, "extra": True},
        ),
        ("plans", {"expectedVersion": 1, "extra": True}),
        ("advance", {"expectedVersion": 1, "extra": True}),
        (
            "overrides",
            {
                "resourceId": "bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": 1,
                "extra": True,
            },
        ),
        ("decisions", {"note": "Approve", "expectedVersion": 1, "extra": True}),
    ],
)
async def test_command_schemas_forbid_extra_fields(
    exercise_app: FastAPI, suffix: str, body: dict[str, object]
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        created = await _create(client)
        response = await client.post(
            f"/api/exercise-sessions/{created['id']}/{suffix}",
            headers={"Idempotency-Key": f"extra-{suffix}"},
            json=body,
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stale_version_returns_committed_current_state_and_rolls_back_claim(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        created = await _create(client)
        selected = await _objective(client, created)
        stale = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": "stale"},
            json={
                "objective": "maximize-population-coverage",
                "expectedVersion": created["version"],
            },
        )
        retry = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": "stale"},
            json={
                "objective": "maximize-population-coverage",
                "expectedVersion": selected["version"],
            },
        )

    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["details"] == {
        "currentSession": selected,
        "allowedActions": ["select-objective", "generate-plan"],
    }
    assert retry.status_code == 200, retry.text


@pytest.mark.asyncio
async def test_plan_replay_returns_the_original_status_and_json(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        first = await _plan(client, selected)
        replay = await client.post(
            f"/api/exercise-sessions/{selected['id']}/plans",
            headers={"Idempotency-Key": "plan"},
            json={"expectedVersion": selected["version"]},
        )

    assert replay.status_code == 201, replay.text
    assert replay.json() == first
    assert first["plan"]["outputData"]["versions"]["definitionDigest"] == (
        exercise_definition_digest(_test_definition())
    )


@pytest.mark.asyncio
async def test_unreachable_task_is_a_stored_uncovered_plan_not_an_api_error(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        initial = await _plan(client, selected)
        cascade = await _advance(client, initial["session"], "advance-initial")
        result = await _plan(client, cascade, "cascade-plan")

    assert "spot-task" in result["plan"]["outputData"]["uncoveredTaskIds"]


@pytest.mark.asyncio
async def test_missing_exercise_graph_maps_to_stable_command_error(
    exercise_app: FastAPI,
) -> None:
    exercise_app.state.graphs = {}
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        response = await client.post(
            f"/api/exercise-sessions/{selected['id']}/plans",
            headers={"Idempotency-Key": "missing-graph"},
            json={"expectedVersion": selected["version"]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "exercise_command_invalid"


@pytest.mark.asyncio
async def test_unknown_plan_keeps_latest_valid_plan_and_cannot_advance(
    exercise_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(request: object) -> TaskOptimizationResult:
        tasks = getattr(request, "tasks")
        resources = getattr(request, "resources")
        return TaskOptimizationResult(
            status="UNKNOWN",
            assignments=(),
            uncovered_task_ids=tuple(item.task_id for item in tasks),
            unassigned_resource_ids=tuple(item.resource_id for item in resources),
            travel_cost=0,
            uncovered_task_penalty=0,
            objective_value=0,
            binding_constraints=("solver-unknown",),
            runtime_milliseconds=1,
            algorithm_version="task-allocation-v1",
        )

    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        valid = await _plan(client, selected, "valid-plan")
        monkeypatch.setattr("wildfireops.application.exercise_planning.solve_task_plan", unknown)
        failed = await _plan(client, valid["session"], "unknown-plan")
        advance = await client.post(
            f"/api/exercise-sessions/{selected['id']}/advance",
            headers={"Idempotency-Key": "advance"},
            json={"expectedVersion": failed["session"]["version"]},
        )

    assert failed["plan"]["outputData"]["status"] == "UNKNOWN"
    assert failed["session"]["latestPlan"] == valid["plan"]["outputData"]
    assert advance.status_code == 409
    assert advance.json()["error"]["details"]["currentSession"] == failed["session"]


@pytest.mark.asyncio
async def test_invalid_override_is_422_without_changing_the_visible_plan(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        initial = await _plan(client, selected)
        cascade = await _advance(client, initial["session"], "advance-initial")
        cascade_plan = await _plan(client, cascade, "cascade-plan")
        final = await _advance(client, cascade_plan["session"], "advance-cascade")
        planned = await _plan(client, final, "final-plan")
        invalid = await client.post(
            f"/api/exercise-sessions/{final['id']}/overrides",
            headers={"Idempotency-Key": "bad-override"},
            json={
                "resourceId": "engine-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": planned["session"]["version"],
            },
        )
        invalid_target = await client.post(
            f"/api/exercise-sessions/{final['id']}/overrides",
            headers={"Idempotency-Key": "bad-target"},
            json={
                "resourceId": "bus-1",
                "taskId": "wrong-task",
                "expectedVersion": planned["session"]["version"],
            },
        )
        invalid_joint = await client.post(
            f"/api/exercise-sessions/{final['id']}/overrides",
            headers={"Idempotency-Key": "bad-joint"},
            json={
                "resourceId": "bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": planned["session"]["version"],
            },
        )
        restored = await client.get(f"/api/exercise-sessions/{final['id']}")

    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["error"]["details"] == {
        "fields": [
            {
                "field": "resourceId",
                "message": "override requires an evacuation-bus resource",
            }
        ]
    }
    assert invalid_target.status_code == 422, invalid_target.text
    assert invalid_target.json()["error"]["details"] == {
        "fields": [
            {
                "field": "taskId",
                "message": "guided override must target shelter transport",
            }
        ]
    }
    assert invalid_joint.status_code == 422, invalid_joint.text
    assert invalid_joint.json()["error"]["details"] == {
        "fields": [
            {
                "field": "resourceId",
                "message": "override fails capability, capacity, route, deadline, or uniqueness",
            },
            {
                "field": "taskId",
                "message": "override fails capability, capacity, route, deadline, or uniqueness",
            },
        ]
    }
    assert restored.json()["latestPlan"]["versions"]["inputHash"] == planned["plan"]["inputHash"]


@pytest.mark.asyncio
async def test_expired_session_returns_start_new_exercise_action(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        created = await _create(client)
        exercise_app.state.clock = lambda: NOW + timedelta(hours=24)
        expired = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": "expired"},
            json={"objective": "fastest-response", "expectedVersion": 1},
        )

    assert expired.status_code == 410, expired.text
    assert expired.json()["error"]["details"] == {"action": "start-new-exercise"}


@pytest.mark.asyncio
async def test_final_decision_requires_a_note_and_debrief_restores_in_a_new_client(
    exercise_app: FastAPI,
) -> None:
    exercise = _journey_definition()
    exercise_app.state.exercise_definition = exercise
    exercise_app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: exercise_app.state.session_factory(),
        graphs=lambda: exercise_app.state.graphs,
        settings=exercise_app.state.settings,
        exercise_definition=exercise,
        clock=lambda: exercise_app.state.clock(),
        callsign=lambda: "EMBER-101",
    )
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        selected = await _objective(client, await _create(client))
        initial = await _plan(client, selected)
        cascade = await _advance(client, initial["session"], "advance-initial")
        cascade_plan = await _plan(client, cascade, "cascade-plan")
        final = await _advance(client, cascade_plan["session"], "advance-cascade")
        planned = await _plan(client, final, "final-plan")
        overridden = await client.post(
            f"/api/exercise-sessions/{final['id']}/overrides",
            headers={"Idempotency-Key": "override"},
            json={
                "resourceId": "bus-1",
                "taskId": "shelter-capacity-transport",
                "expectedVersion": planned["session"]["version"],
            },
        )
        assert overridden.status_code == 201, overridden.text
        blank = await client.post(
            f"/api/exercise-sessions/{final['id']}/decisions",
            headers={"Idempotency-Key": "blank-note"},
            json={"expectedVersion": overridden.json()["session"]["version"], "note": ""},
        )
        approved = await client.post(
            f"/api/exercise-sessions/{final['id']}/decisions",
            headers={"Idempotency-Key": "approve"},
            json={
                "expectedVersion": overridden.json()["session"]["version"],
                "displayName": "Operator",
                "note": "Approve the checked shelter transport.",
            },
        )
        assert approved.status_code == 201, approved.text
        debrief = await client.get(f"/api/exercise-sessions/{final['id']}/debrief")

    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as fresh:
        restored = await fresh.get(f"/api/exercise-sessions/{final['id']}/debrief")

    assert blank.status_code == 422
    assert debrief.status_code == 200, debrief.text
    assert restored.status_code == 200, restored.text
    assert restored.json() == debrief.json()
    plan_ids = {item["id"] for item in debrief.json()["plans"]}
    assert debrief.json()["finalPlan"] == debrief.json()["plans"][-1]
    assert {
        "id",
        "sessionId",
        "checkpointKey",
        "inputHash",
        "inputData",
        "outputData",
        "versions",
        "createdAt",
    } <= debrief.json()["finalPlan"].keys()
    assert all(
        {
            "id",
            "sessionId",
            "eventType",
            "expectedSessionVersion",
            "resultingSessionVersion",
            "beforeState",
            "afterState",
            "inputs",
            "occurredAt",
        }
        <= event.keys()
        for event in debrief.json()["events"]
    )
    assert {
        value
        for event in debrief.json()["events"]
        for key, value in event["inputs"].items()
        if key.endswith("PlanId") and value is not None
    } <= plan_ids


@pytest.mark.asyncio
async def test_completed_session_sandbox_plan_is_read_only_without_idempotency_key(
    exercise_app: FastAPI,
) -> None:
    exercise = _sandbox_definition()
    exercise_app.state.exercise_definition = exercise
    exercise_app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: exercise_app.state.session_factory(),
        graphs=lambda: exercise_app.state.graphs,
        settings=exercise_app.state.settings,
        exercise_definition=exercise,
        clock=lambda: exercise_app.state.clock(),
        callsign=lambda: "EMBER-101",
    )
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        completed = await _complete(client)
        session_id = completed["id"]
        before_counts = await _sandbox_counts(exercise_app, session_id)
        before_session = await client.get(f"/api/exercise-sessions/{session_id}")
        before_audit = await client.get(f"/api/exercise-sessions/{session_id}/audit")
        response = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={
                "expectedVersion": completed["version"],
                "checkpointKey": "cascade",
                "objective": "maximize-population-coverage",
                "windPreset": "strong-northeast",
                "unavailableResourceIds": ["engine-1"],
                "taskPriorityPresets": {"park-task": "urgent"},
            },
        )
        after_session = await client.get(f"/api/exercise-sessions/{session_id}")
        after_audit = await client.get(f"/api/exercise-sessions/{session_id}/audit")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sandbox"] is True
    assert body["sessionVersion"] == completed["version"]
    assert body["inputHash"] == body["output"]["versions"]["inputHash"]
    assert body["output"]["versions"]["riskVersion"] == "not-applicable"
    assert after_session.json() == before_session.json()
    assert after_audit.json() == before_audit.json()
    assert await _sandbox_counts(exercise_app, session_id) == before_counts


@pytest.mark.asyncio
async def test_sandbox_rejects_unbounded_controls_without_state_changes(
    exercise_app: FastAPI,
) -> None:
    exercise = _sandbox_definition()
    exercise_app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: exercise_app.state.session_factory(),
        graphs=lambda: exercise_app.state.graphs,
        settings=exercise_app.state.settings,
        exercise_definition=exercise,
        clock=lambda: exercise_app.state.clock(),
        callsign=lambda: "EMBER-101",
    )
    base = {
        "checkpointKey": "cascade",
        "objective": "maximize-population-coverage",
        "windPreset": "strong-northeast",
    }
    cases = (
        ({"checkpointKey": "unknown"}, "exercise_command_invalid", "sandbox checkpoint"),
        ({"objective": "unknown"}, "validation_error", "Input should be"),
        ({"closedEdgeIds": ["unknown"]}, "exercise_command_invalid", "sandbox closure"),
        ({"windPreset": "unknown"}, "exercise_command_invalid", "sandbox wind"),
        ({"unavailableResourceIds": ["unknown"]}, "exercise_command_invalid", "unknown sandbox resource"),
        ({"taskPriorityPresets": {"unknown": "urgent"}}, "exercise_command_invalid", "unknown sandbox task"),
        ({"lockedAssignments": [{"resourceId": "bus-1", "taskId": "park-task"}]}, "exercise_command_invalid", "locked assignment"),
        ({"extra": True}, "validation_error", "Extra inputs are not permitted"),
    )
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        completed = await _complete(client)
        session_id = completed["id"]
        before_counts = await _sandbox_counts(exercise_app, session_id)
        before_session = await client.get(f"/api/exercise-sessions/{session_id}")
        before_audit = await client.get(f"/api/exercise-sessions/{session_id}/audit")
        for patch, code, message in cases:
            response = await client.post(
                f"/api/exercise-sessions/{session_id}/sandbox-plans",
                json={**base, "expectedVersion": completed["version"], **patch},
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == code
            assert message in response.text
            assert await _sandbox_counts(exercise_app, session_id) == before_counts
            assert (await client.get(f"/api/exercise-sessions/{session_id}")).json() == before_session.json()
            assert (await client.get(f"/api/exercise-sessions/{session_id}/audit")).json() == before_audit.json()

        stale = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={**base, "expectedVersion": completed["version"] - 1},
        )
        assert await _sandbox_counts(exercise_app, session_id) == before_counts
        assert (await client.get(f"/api/exercise-sessions/{session_id}")).json() == before_session.json()
        assert (await client.get(f"/api/exercise-sessions/{session_id}/audit")).json() == before_audit.json()
        incomplete = await _create(client, "incomplete")
        incomplete_before = await _sandbox_counts(exercise_app, incomplete["id"])
        incomplete_response = await client.post(
            f"/api/exercise-sessions/{incomplete['id']}/sandbox-plans",
            json={**base, "expectedVersion": incomplete["version"]},
        )

    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "exercise_session_version_conflict"
    assert incomplete_response.status_code == 409, incomplete_response.text
    assert incomplete_response.json()["error"]["code"] == "exercise_transition_invalid"
    assert await _sandbox_counts(exercise_app, incomplete["id"]) == incomplete_before


@pytest.mark.asyncio
async def test_concurrent_and_failing_sandbox_requests_never_write(
    exercise_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_only: list[str] = []
    original_get_session = ExerciseRepository.get_session

    async def get_session(
        repository: ExerciseRepository, session_id: UUID
    ) -> object:
        read_only.append(
            str(await repository._session.scalar(text("SHOW transaction_read_only")))
        )
        return await original_get_session(repository, session_id)

    monkeypatch.setattr(ExerciseRepository, "get_session", get_session)
    exercise = _sandbox_definition()
    exercise_app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: exercise_app.state.session_factory(),
        graphs=lambda: exercise_app.state.graphs,
        settings=exercise_app.state.settings,
        exercise_definition=exercise,
        clock=lambda: exercise_app.state.clock(),
        callsign=lambda: "EMBER-101",
    )
    body = {
        "checkpointKey": "cascade",
        "objective": "maximize-population-coverage",
        "windPreset": "strong-northeast",
    }
    async with AsyncClient(
        transport=ASGITransport(app=exercise_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        completed = await _complete(client)
        session_id = completed["id"]
        before = await _sandbox_counts(exercise_app, session_id)
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/exercise-sessions/{session_id}/sandbox-plans",
                    json={**body, "expectedVersion": completed["version"]},
                )
                for _ in range(3)
            )
        )
        monkeypatch.setattr(
            "wildfireops.application.exercise_planning.solve_task_plan",
            lambda request: (_ for _ in ()).throw(RuntimeError("solver failed")),
        )
        failed = await client.post(
            f"/api/exercise-sessions/{session_id}/sandbox-plans",
            json={**body, "expectedVersion": completed["version"]},
        )

    assert all(response.status_code == 200 for response in responses)
    assert failed.status_code == 500, failed.text
    assert read_only == ["on"] * 4
    assert await _sandbox_counts(exercise_app, session_id) == before


@pytest.mark.asyncio
async def test_bad_path_header_and_body_values_are_422_not_500(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        invalid_id = await client.get("/api/exercise-sessions/not-a-uuid")
        created = await _create(client)
        empty_header = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": " "},
            json={"objective": "fastest-response", "expectedVersion": 1},
        )
        bad_version = await client.post(
            f"/api/exercise-sessions/{created['id']}/objective",
            headers={"Idempotency-Key": "valid"},
            json={"objective": "fastest-response", "expectedVersion": 0},
        )

    assert invalid_id.status_code == 422
    assert empty_header.status_code == 422
    assert bad_version.status_code == 422


@pytest.mark.asyncio
async def test_audit_is_session_scoped_and_version_ordered(
    exercise_app: FastAPI,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        first = await _objective(client, await _create(client, "first"), "first-objective")
        second = await _create(client, "second")
        audit = await client.get(f"/api/exercise-sessions/{first['id']}/audit")
        other = await client.get(f"/api/exercise-sessions/{second['id']}/audit")

    assert audit.status_code == 200, audit.text
    assert [item["resultingSessionVersion"] for item in audit.json()["items"]] == [1, 2]
    assert [item["sessionId"] for item in other.json()["items"]] == [second["id"]]


def _install_definition(app: FastAPI, exercise: ExerciseDefinition) -> None:
    app.state.exercise_definition = exercise
    app.state.command_service_provider = CommandServiceProvider(
        session_factory=lambda: app.state.session_factory(),
        graphs=lambda: app.state.graphs,
        settings=app.state.settings,
        exercise_definition=exercise,
        clock=lambda: app.state.clock(),
        callsign=lambda: "EMBER-101",
    )


@pytest.mark.asyncio
async def test_metadata_publishes_the_sandbox_options(
    exercise_app: FastAPI,
) -> None:
    _install_definition(exercise_app, _sandbox_definition())

    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        response = await client.get("/api/exercises/park-fire-decision")

    assert response.status_code == 200, response.text
    assert response.json()["sandbox"] == {
        "checkpointKeys": ["cascade"],
        "closureEdgeIds": ["edge-32"],
        "windPresets": [
            {
                "key": "strong-northeast",
                "disruption": {
                    "windSpeedMps": 12.0,
                    "windDirectionDegrees": 45.0,
                    "closedEdgeIds": [],
                    "provenance": "exercise",
                },
            }
        ],
        "priorityPresets": [
            {"key": "standard", "multiplier": 1},
            {"key": "elevated", "multiplier": 2},
            {"key": "urgent", "multiplier": 3},
        ],
    }


@pytest.mark.asyncio
async def test_every_advertised_sandbox_option_is_accepted(
    exercise_app: FastAPI,
) -> None:
    """Metadata and the sandbox validator must not be able to drift apart.

    A client that builds its form from the advertised options should never be
    rejected for using one, so every request below is assembled from the
    metadata response rather than from literals.
    """
    _install_definition(exercise_app, _sandbox_definition())

    async with AsyncClient(transport=ASGITransport(app=exercise_app), base_url="http://test") as client:
        metadata = (await client.get("/api/exercises/park-fire-decision")).json()
        options = metadata["sandbox"]
        completed = await _complete(client)
        session_id = str(completed["id"])
        before_counts = await _sandbox_counts(exercise_app, session_id)

        checkpoint_key = options["checkpointKeys"][0]
        debrief = (await client.get(f"/api/exercise-sessions/{session_id}/debrief")).json()
        task_ids = sorted(
            {
                entry["taskId"]
                for plan in debrief["plans"]
                if plan["checkpointKey"] == checkpoint_key
                for entry in plan["outputData"]["taskCoverage"]
            }
        )
        assert task_ids, "the sandbox checkpoint must have planned tasks to re-rank"

        for objective in metadata["objectives"]:
            for preset in options["priorityPresets"]:
                response = await client.post(
                    f"/api/exercise-sessions/{session_id}/sandbox-plans",
                    json={
                        "expectedVersion": completed["version"],
                        "checkpointKey": checkpoint_key,
                        "objective": objective,
                        "closedEdgeIds": options["closureEdgeIds"],
                        "windPreset": options["windPresets"][0]["key"],
                        "unavailableResourceIds": [],
                        "taskPriorityPresets": {task_ids[0]: preset["key"]},
                        "lockedAssignments": [],
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json()["sandbox"] is True

        # Nothing the sandbox does may reach the recorded exercise.
        assert await _sandbox_counts(exercise_app, session_id) == before_counts
