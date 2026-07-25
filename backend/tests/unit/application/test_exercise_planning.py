from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import networkx as nx
import pytest

from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseEvent,
    ExercisePlanRun,
    ExerciseSession,
    ExerciseSessionService,
    ExerciseTransitionInvalid,
)
from wildfireops.decision.task_optimizer import (
    TaskOptimizationRequest,
    TaskOptimizationResult,
)
from wildfireops.domain.observations import freeze_json_object
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.geospatial.road_graph import RoadGraph, RoadGraphInvalid
from wildfireops.replay.exercise import ExerciseDefinition, _canonicalize


NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def graph() -> RoadGraph:
    value = nx.MultiDiGraph()
    value.add_node("depot", x=0.0, y=0.0)
    value.add_node("park", x=1.0, y=0.0)
    value.add_node("spot", x=2.0, y=0.0)
    value.add_edge(
        "depot", "park", edge_id="edge-01", travel_minutes=5.0, distance_meters=500
    )
    value.add_edge(
        "park", "spot", edge_id="edge-32", travel_minutes=5.0, distance_meters=500
    )
    return RoadGraph.from_graph(value)


def definition() -> ExerciseDefinition:
    roads = graph()
    return ExerciseDefinition.model_validate(
        {
            "exerciseId": "park-fire-decision",
            "version": "1",
            "name": "Park Fire",
            "description": "Exercise",
            "replayPackageId": "park-fire",
            "graphVersion": roads.graph_version,
            "objectives": {
                "fastest-response": {
                    "travelWeight": 3,
                    "basePriorityWeight": 1,
                    "criticalServiceWeight": 2,
                    "populationDivisor": 10,
                    "populationWeight": 1,
                },
                "protect-critical-services": {
                    "travelWeight": 1,
                    "basePriorityWeight": 2,
                    "criticalServiceWeight": 20,
                    "populationDivisor": 10,
                    "populationWeight": 1,
                },
                "maximize-population-coverage": {
                    "travelWeight": 1,
                    "basePriorityWeight": 1,
                    "criticalServiceWeight": 2,
                    "populationDivisor": 10,
                    "populationWeight": 10,
                },
            },
            "assets": [
                {
                    "assetId": "park-asset",
                    "assetKind": "community",
                    "name": "Park",
                    "position": {"longitude": 1, "latitude": 0},
                    "sourceName": "census",
                    "sourceVersion": "v1",
                    "sourceRecordId": "park",
                    "citationUrl": "https://example.test/park",
                },
                {
                    "assetId": "spot-asset",
                    "assetKind": "community",
                    "name": "Spot",
                    "position": {"longitude": 2, "latitude": 0},
                    "sourceName": "census",
                    "sourceVersion": "v1",
                    "sourceRecordId": "spot",
                    "citationUrl": "https://example.test/spot",
                },
                {
                    "assetId": "shelter-asset",
                    "assetKind": "shelter",
                    "name": "Shelter",
                    "position": {"longitude": 2, "latitude": 0},
                    "sourceName": "census",
                    "sourceVersion": "v1",
                    "sourceRecordId": "shelter",
                    "citationUrl": "https://example.test/shelter",
                },
            ],
            "resources": [
                {
                    "resourceId": "engine-1",
                    "resourceType": "engine",
                    "capabilities": ["protect"],
                    "capacity": 1,
                    "position": {"longitude": 0, "latitude": 0},
                },
                {
                    "resourceId": "bus-1",
                    "resourceType": "evacuation-bus",
                    "capabilities": ["transport"],
                    "capacity": 1,
                    "position": {"longitude": 0, "latitude": 0},
                },
            ],
            "checkpoints": [
                {
                    "checkpointKey": "initial",
                    "title": "Initial",
                    "situationSummary": "Initial",
                    "decisionPrompt": "Initial",
                    "referenceAt": "2026-07-24T12:00:00Z",
                    "historicalWeatherIdentity": "weather:1",
                    "incidents": [
                        {
                            "incidentKey": "park-fire",
                            "name": "Park",
                            "provenance": "historical",
                            "detectionIdentities": ["firms:1"],
                        }
                    ],
                    "tasks": [_task("park-task", "park-fire", "park-asset")],
                },
                {
                    "checkpointKey": "cascade",
                    "title": "Cascade",
                    "situationSummary": "Cascade",
                    "decisionPrompt": "Cascade",
                    "referenceAt": "2026-07-24T13:00:00Z",
                    "historicalWeatherIdentity": "weather:1",
                    "incidents": [
                        {
                            "incidentKey": "park-fire",
                            "name": "Park",
                            "provenance": "historical",
                            "detectionIdentities": ["firms:1"],
                        },
                        {
                            "incidentKey": "spot-fire",
                            "name": "Spot",
                            "provenance": "exercise",
                            "simulatedPosition": {"longitude": 2, "latitude": 0},
                        },
                    ],
                    "tasks": [
                        _task("park-task", "park-fire", "park-asset"),
                        _task("spot-task", "spot-fire", "spot-asset"),
                    ],
                    "disruption": {
                        "windSpeedMps": 8,
                        "windDirectionDegrees": 90,
                        "closedEdgeIds": ["edge-32"],
                    },
                },
                {
                    "checkpointKey": "field-report",
                    "title": "Field report",
                    "situationSummary": "Field report",
                    "decisionPrompt": "Field report",
                    "referenceAt": "2026-07-24T14:00:00Z",
                    "historicalWeatherIdentity": "weather:1",
                    "incidents": [
                        {
                            "incidentKey": "park-fire",
                            "name": "Park",
                            "provenance": "historical",
                            "detectionIdentities": ["firms:1"],
                        }
                    ],
                    "tasks": [
                        _task("park-task", "park-fire", "park-asset"),
                        _task(
                            "park-transport",
                            "park-fire",
                            "park-asset",
                            capability="transport",
                            priority=100,
                        ),
                        _task(
                            "shelter-capacity-transport",
                            "park-fire",
                            "shelter-asset",
                            capability="transport",
                            priority=1,
                        ),
                    ],
                    "disruption": {
                        "windSpeedMps": 8,
                        "windDirectionDegrees": 90,
                        "closedEdgeIds": ["edge-32"],
                    },
                },
            ],
            "sandbox": {
                "checkpointKeys": ["initial"],
                "closureEdgeIds": ["edge-32"],
                "windPresets": {},
                "priorityMultipliers": {"standard": 1, "elevated": 1, "urgent": 1},
            },
            "safetyStatement": "Exercise only",
        }
    )


def _task(
    task_id: str,
    incident_key: str,
    asset_id: str,
    *,
    capability: str = "protect",
    priority: int = 10,
) -> dict[str, object]:
    return {
        "taskId": task_id,
        "incidentKey": incident_key,
        "assetId": asset_id,
        "taskType": "community-evacuation",
        "requiredCapability": capability,
        "requiredCapacity": 1,
        "deadlineMinutes": 30,
        "affectedPopulation": 100,
        "criticalService": True,
        "basePriority": priority,
    }


class FakeExerciseRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, ExerciseSession] = {}
        self.plans: list[ExercisePlanRun] = []
        self.events: list[ExerciseEvent] = []
        self.claims: dict[tuple[str, str], IdempotencyClaim] = {}

    async def claim_idempotency(
        self, *, scope: str, key: str, request_hash: str
    ) -> IdempotencyClaim:
        existing = self.claims.get((scope, key))
        if existing is not None:
            return replace(existing, created=False)
        claim = IdempotencyClaim(uuid4(), request_hash, None, None, True)
        self.claims[scope, key] = claim
        return claim

    async def complete_idempotency(
        self, *, claim_id: UUID, response_type: str, response_id: UUID
    ) -> None:
        for key, claim in self.claims.items():
            if claim.id == claim_id:
                self.claims[key] = IdempotencyClaim(
                    claim.id, claim.request_hash, response_type, response_id, True
                )
                return
        raise AssertionError("claim does not exist")

    async def get_session(self, session_id: UUID) -> ExerciseSession | None:
        return self.sessions.get(session_id)

    async def lock_session(self, session_id: UUID) -> ExerciseSession | None:
        return self.sessions.get(session_id)

    async def save_session(self, session: ExerciseSession) -> None:
        self.sessions[session.id] = session

    async def store_plan(self, **values: object) -> ExercisePlanRun:
        values.pop("idempotency_key_id")
        plan = ExercisePlanRun(
            id=uuid4(),
            created_at=NOW,
            input_data=freeze_json_object(values.pop("input_data")),
            output_data=freeze_json_object(values.pop("output_data")),
            versions=freeze_json_object(values.pop("versions")),
            **values,  # type: ignore[arg-type]
        )
        self.plans.append(plan)
        return plan

    async def get_plan(self, session_id: UUID, plan_id: UUID) -> ExercisePlanRun | None:
        return next(
            (
                plan
                for plan in self.plans
                if plan.id == plan_id and plan.session_id == session_id
            ),
            None,
        )

    async def latest_plan(
        self, session_id: UUID, checkpoint_key: str
    ) -> ExercisePlanRun | None:
        return next(
            (
                plan
                for plan in reversed(self.plans)
                if plan.session_id == session_id and plan.checkpoint_key == checkpoint_key
            ),
            None,
        )

    async def latest_plan_for_session(self, session_id: UUID) -> ExercisePlanRun | None:
        return next(
            (plan for plan in reversed(self.plans) if plan.session_id == session_id),
            None,
        )

    async def list_plans(self, session_id: UUID) -> tuple[ExercisePlanRun, ...]:
        return tuple(plan for plan in self.plans if plan.session_id == session_id)

    async def get_event(self, session_id: UUID, event_id: UUID) -> ExerciseEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.id == event_id and event.session_id == session_id
            ),
            None,
        )

    async def append_event(self, **values: object) -> ExerciseEvent:
        event = ExerciseEvent(
            id=uuid4(),
            occurred_at=NOW,
            before_state=freeze_json_object(values.pop("before_state")),
            after_state=freeze_json_object(values.pop("after_state")),
            inputs=freeze_json_object(values.pop("inputs")),
            **values,  # type: ignore[arg-type]
        )
        self.events.append(event)
        return event


def planning_service(
    repository: FakeExerciseRepository, exercise_definition: ExerciseDefinition | None = None
) -> tuple[object, ExerciseSessionService]:
    from wildfireops.application.exercise_planning import ExercisePlanningService

    exercise = definition() if exercise_definition is None else exercise_definition
    sessions = ExerciseSessionService(
        definition=exercise,
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: NOW,
        callsign=lambda: "EMBER-101",
    )
    return (
        ExercisePlanningService(
            definition=exercise,
            definition_digest="a" * 64,
            graph=graph(),
            repository=repository,
            session_service=sessions,
            clock=lambda: NOW,
        ),
        sessions,
    )


def session(
    repository: FakeExerciseRepository,
    *,
    checkpoint_index: int = 0,
    consequences: dict[str, object] | None = None,
) -> ExerciseSession:
    value = ExerciseSession(
        id=uuid4(),
        exercise_id="park-fire-decision",
        definition_version="1",
        definition_digest="a" * 64,
        callsign="EMBER-101",
        display_name=None,
        checkpoint_index=checkpoint_index,
        objective="fastest-response",
        status="active",
        version=1,
        consequences={} if consequences is None else consequences,
        expires_at=NOW + timedelta(hours=24),
    )
    repository.sessions[value.id] = value
    return value


def _unknown_task_plan(request: TaskOptimizationRequest) -> TaskOptimizationResult:
    return TaskOptimizationResult(
        "UNKNOWN",
        (),
        tuple(task.task_id for task in request.tasks),
        tuple(resource.resource_id for resource in request.resources),
        0,
        0,
        0,
        (),
        0,
        "task-allocation-v1",
    )


def test_checkpoint_materialization_combines_both_incidents() -> None:
    from wildfireops.application.exercise_planning import materialize_checkpoint

    materialized = materialize_checkpoint(
        definition(),
        checkpoint_index=1,
        objective="protect-critical-services",
        consequences={"corridorCleared": False},
    )

    assert {item.incident_id for item in materialized.tasks} == {
        "park-fire",
        "spot-fire",
    }
    assert materialized.closed_edge_ids == ("edge-32",)
    assert materialized.objective == "protect-critical-services"


def test_all_three_objectives_compute_different_penalties() -> None:
    from wildfireops.application.exercise_planning import uncovered_penalty

    task = definition().checkpoints[0].tasks[0]

    assert [
        uncovered_penalty(task, definition().objectives[objective])
        for objective in definition().objectives
    ] == [22, 50, 112]


def test_checkpoint_two_routes_apply_closure() -> None:
    from wildfireops.application.exercise_planning import candidate_routes, materialize_checkpoint

    exercise = definition()
    checkpoint = materialize_checkpoint(
        exercise,
        checkpoint_index=1,
        objective="fastest-response",
        consequences={},
    )

    routes = candidate_routes(
        graph(),
        checkpoint.resources,
        checkpoint.tasks,
        checkpoint.asset_positions,
        checkpoint.closed_edge_ids,
    )

    assert all("edge-32" not in route.route.edge_ids for route in routes)


def test_checkpoint_three_reopens_corridor_only_after_crew_assignment() -> None:
    from wildfireops.application.exercise_planning import materialize_checkpoint

    closed = materialize_checkpoint(
        definition(),
        checkpoint_index=2,
        objective="fastest-response",
        consequences={"corridorCleared": False},
    )
    reopened = materialize_checkpoint(
        definition(),
        checkpoint_index=2,
        objective="fastest-response",
        consequences={"corridorCleared": True},
    )

    assert closed.closed_edge_ids == ("edge-32",)
    assert reopened.closed_edge_ids == ()


@pytest.mark.asyncio
async def test_duplicate_plan_command_replays_same_plan() -> None:
    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository)

    first, first_projection = await service.generate_plan(
        current.id, expected_version=1, idempotency_key="plan"
    )
    current.version = 99
    repository.plans.append(
        replace(first, id=uuid4(), output_data=freeze_json_object({"status": "UNKNOWN"}))
    )
    plan_count = len(repository.plans)
    event_count = len(repository.events)
    replay, replay_projection = await service.generate_plan(
        current.id, expected_version=1, idempotency_key="plan"
    )

    assert replay.id == first.id
    assert replay_projection == first_projection
    assert len(repository.plans) == plan_count
    assert len(repository.events) == event_count


@pytest.mark.asyncio
async def test_unknown_plan_is_stored_but_cannot_advance(monkeypatch: pytest.MonkeyPatch) -> None:
    from wildfireops.application import exercise_planning

    monkeypatch.setattr(exercise_planning, "solve_task_plan", _unknown_task_plan)
    repository = FakeExerciseRepository()
    service, sessions = planning_service(repository)
    current = session(repository)

    plan, projection = await service.generate_plan(
        current.id, expected_version=1, idempotency_key="plan"
    )

    assert plan.output_data["status"] == "UNKNOWN"
    assert projection["allowedActions"] == ("select-objective", "generate-plan")
    with pytest.raises(ExerciseTransitionInvalid, match="current checkpoint has no actionable plan"):
        await sessions.advance(current.id, expected_version=2, idempotency_key="advance")


@pytest.mark.asyncio
async def test_override_rejects_non_bus_resource_without_storing_plan_or_event() -> None:
    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository, checkpoint_index=2, consequences={"corridorCleared": True})
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")

    with pytest.raises(ExerciseCommandInvalid, match="evacuation-bus") as error:
        await service.apply_override(
            current.id,
            resource_id="engine-1",
            task_id="shelter-capacity-transport",
            expected_version=2,
            idempotency_key="override",
        )

    assert error.value.fields == ("resourceId",)
    assert len(repository.plans) == len(repository.events) == 1


@pytest.mark.asyncio
async def test_override_rejects_unreachable_shelter_route() -> None:
    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository, checkpoint_index=2, consequences={"corridorCleared": False})
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")

    with pytest.raises(
        ExerciseCommandInvalid,
        match="override fails capability, capacity, route, deadline, or uniqueness",
    ):
        await service.apply_override(
            current.id,
            resource_id="bus-1",
            task_id="shelter-capacity-transport",
            expected_version=2,
            idempotency_key="override",
        )


@pytest.mark.asyncio
async def test_override_recalculates_uncovered_tasks_and_objective() -> None:
    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository, checkpoint_index=2, consequences={"corridorCleared": True})
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")

    plan, _ = await service.apply_override(
        current.id,
        resource_id="bus-1",
        task_id="shelter-capacity-transport",
        expected_version=2,
        idempotency_key="override",
    )

    assert {item["taskId"] for item in plan.output_data["assignments"]} >= {
        "shelter-capacity-transport"
    }
    assert "park-transport" in plan.output_data["uncoveredTaskIds"]
    components = plan.output_data["objectiveComponents"]
    assert components["objectiveValue"] == (
        components["travelCost"] + components["uncoveredTaskPenalty"]
    )
    assert "operator.override-changed-plan" in {
        item["code"] for item in plan.output_data["explanation"]["changes"]
    }


@pytest.mark.asyncio
async def test_override_validates_a_semantically_unchanged_frozen_plan() -> None:
    exercise_data = definition().model_dump(
        mode="json", by_alias=True, fallback=dict, warnings=False
    )
    tasks = exercise_data["checkpoints"][2]["tasks"]
    tasks[1]["basePriority"] = 1
    tasks[2]["basePriority"] = 100
    repository = FakeExerciseRepository()
    service, _ = planning_service(
        repository, ExerciseDefinition.model_validate(exercise_data)
    )
    current = session(repository, checkpoint_index=2, consequences={"corridorCleared": True})
    prior, _ = await service.generate_plan(
        current.id, expected_version=1, idempotency_key="plan"
    )

    override, _ = await service.apply_override(
        current.id,
        resource_id="bus-1",
        task_id="shelter-capacity-transport",
        expected_version=2,
        idempotency_key="override",
    )

    assert prior.output_data["assignments"] == override.output_data["assignments"]
    assert "operator.override-validated" in {
        item["code"] for item in override.output_data["explanation"]["changes"]
    }


@pytest.mark.asyncio
async def test_failed_plan_replay_returns_latest_prior_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops.application import exercise_planning

    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository)
    await service.generate_plan(current.id, expected_version=1, idempotency_key="first")
    latest, _ = await service.generate_plan(
        current.id, expected_version=2, idempotency_key="latest"
    )
    monkeypatch.setattr(exercise_planning, "solve_task_plan", _unknown_task_plan)
    failed, projection = await service.generate_plan(
        current.id, expected_version=3, idempotency_key="failed"
    )

    replay, replay_projection = await service.generate_plan(
        current.id, expected_version=3, idempotency_key="failed"
    )

    assert repository.events[-1].inputs["visiblePlanId"] == str(latest.id)
    assert projection["latestPlan"] == latest.output_data
    assert replay.id == failed.id
    assert replay_projection == projection


@pytest.mark.asyncio
async def test_failed_plan_replay_rejects_older_visible_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops.application import exercise_planning

    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository)
    older, _ = await service.generate_plan(
        current.id, expected_version=1, idempotency_key="older"
    )
    await service.generate_plan(current.id, expected_version=2, idempotency_key="latest")
    monkeypatch.setattr(exercise_planning, "solve_task_plan", _unknown_task_plan)
    await service.generate_plan(current.id, expected_version=3, idempotency_key="failed")
    event = repository.events[-1]
    snapshot = dict(event.inputs["_responseProjection"])
    snapshot["latestPlan"] = older.output_data
    repository.events[-1] = replace(
        event,
        inputs=freeze_json_object(
            {
                **event.inputs,
                "visiblePlanId": str(older.id),
                "_responseProjection": snapshot,
            }
        ),
    )

    with pytest.raises(RuntimeError, match="exercise replay response is invalid"):
        await service.generate_plan(
            current.id, expected_version=3, idempotency_key="failed"
        )


@pytest.mark.asyncio
async def test_failed_plan_replay_rejects_visible_plan_output_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops.application import exercise_planning

    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository)
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")
    monkeypatch.setattr(exercise_planning, "solve_task_plan", _unknown_task_plan)
    failed, _ = await service.generate_plan(
        current.id, expected_version=2, idempotency_key="failed"
    )
    event = repository.events[-1]
    snapshot = dict(event.inputs["_responseProjection"])
    snapshot["latestPlan"] = failed.output_data
    repository.events[-1] = replace(
        event,
        inputs=freeze_json_object(
            {**event.inputs, "_responseProjection": snapshot}
        ),
    )

    with pytest.raises(RuntimeError, match="exercise replay response is invalid"):
        await service.generate_plan(
            current.id, expected_version=2, idempotency_key="failed"
        )


@pytest.mark.asyncio
async def test_failed_plan_replay_rejects_attempt_missing_from_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops.application import exercise_planning

    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository)
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")
    monkeypatch.setattr(exercise_planning, "solve_task_plan", _unknown_task_plan)
    failed, _ = await service.generate_plan(
        current.id, expected_version=2, idempotency_key="failed"
    )

    async def incomplete_history(session_id: UUID) -> tuple[ExercisePlanRun, ...]:
        return tuple(
            plan
            for plan in repository.plans
            if plan.session_id == session_id and plan.id != failed.id
        )

    monkeypatch.setattr(repository, "list_plans", incomplete_history)
    with pytest.raises(RuntimeError, match="exercise replay integrity is invalid"):
        await service.generate_plan(
            current.id, expected_version=2, idempotency_key="failed"
        )


@pytest.mark.asyncio
async def test_generate_rejects_checkpoint_three_after_override() -> None:
    repository = FakeExerciseRepository()
    service, _ = planning_service(repository)
    current = session(repository, checkpoint_index=2, consequences={"corridorCleared": True})
    await service.generate_plan(current.id, expected_version=1, idempotency_key="plan")
    await service.apply_override(
        current.id,
        resource_id="bus-1",
        task_id="shelter-capacity-transport",
        expected_version=2,
        idempotency_key="override",
    )

    with pytest.raises(
        ExerciseTransitionInvalid,
        match="checkpoint-three override is already applied",
    ):
        await service.generate_plan(current.id, expected_version=3, idempotency_key="retry")


def test_runtime_validation_accepts_the_curated_definition() -> None:
    from wildfireops.application.exercise_planning import validate_exercise_runtime

    validate_exercise_runtime(_runtime_definition(), graph())


def test_runtime_validation_rejects_unknown_closure_edge() -> None:
    from wildfireops.application.exercise_planning import (
        ExerciseRuntimeInvalid,
        validate_exercise_runtime,
    )

    payload = _definition_payload()
    payload["checkpoints"][1]["disruption"]["closedEdgeIds"] = ["unknown-edge"]

    with pytest.raises(ExerciseRuntimeInvalid, match="unknown closure edge: unknown-edge"):
        validate_exercise_runtime(ExerciseDefinition.model_validate(payload), graph())


def test_runtime_validation_rejects_an_unsnappable_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops.application import exercise_planning

    def unsnappable(*_args: object) -> object:
        raise RoadGraphInvalid("road graph has no finite coordinate nodes")

    monkeypatch.setattr(exercise_planning, "nearest_road_node", unsnappable)

    with pytest.raises(
        exercise_planning.ExerciseRuntimeInvalid,
        match="cannot snap asset: park-asset",
    ):
        exercise_planning.validate_exercise_runtime(_runtime_definition(), graph())


def test_runtime_validation_rejects_an_infeasible_shelter_override() -> None:
    from wildfireops.application.exercise_planning import (
        ExerciseRuntimeInvalid,
        validate_exercise_runtime,
    )

    payload = _canonicalize(_runtime_definition())
    assert isinstance(payload, dict)
    payload["resources"][1]["capabilities"] = ["not-transport"]

    with pytest.raises(
        ExerciseRuntimeInvalid,
        match="shelter override is unavailable: fastest-response, corridorCleared=False",
    ):
        validate_exercise_runtime(ExerciseDefinition.model_validate(payload), graph())


def _runtime_definition() -> ExerciseDefinition:
    payload = _definition_payload()
    payload["checkpoints"][2]["disruption"]["closedEdgeIds"] = []
    return ExerciseDefinition.model_validate(payload)


def _definition_payload() -> dict[str, object]:
    payload = _canonicalize(definition())
    assert isinstance(payload, dict)
    return payload
