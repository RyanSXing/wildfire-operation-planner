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
from wildfireops.domain.observations import freeze_json_object
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.replay.exercise import ExerciseDefinition


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
    repository: FakeExerciseRepository,
) -> tuple[object, ExerciseSessionService]:
    from wildfireops.application.exercise_planning import ExercisePlanningService

    exercise = definition()
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
    from wildfireops.decision.task_optimizer import TaskOptimizationResult

    monkeypatch.setattr(
        exercise_planning,
        "solve_task_plan",
        lambda request: TaskOptimizationResult(
            "UNKNOWN", (), tuple(task.task_id for task in request.tasks),
            tuple(resource.resource_id for resource in request.resources),
            0, 0, 0, (), 0, "task-allocation-v1"
        ),
    )
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

    with pytest.raises(
        ExerciseCommandInvalid,
        match="override fails capability, capacity, route, deadline, or uniqueness",
    ):
        await service.apply_override(
            current.id,
            resource_id="engine-1",
            task_id="shelter-capacity-transport",
            expected_version=2,
            idempotency_key="override",
        )

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
