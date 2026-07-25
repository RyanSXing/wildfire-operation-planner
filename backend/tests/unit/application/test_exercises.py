from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseEvent,
    ExerciseIdempotencyConflict,
    ExercisePlanRun,
    ExerciseQueryService,
    ExerciseSession,
    ExerciseSessionExpired,
    ExerciseSessionNotFound,
    ExerciseSessionService,
    ExerciseTransitionInvalid,
    ExerciseVersionConflict,
    _request_hash,
    _session_from_state,
)
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.domain.observations import freeze_json_object
from wildfireops.replay.exercise import ExerciseDefinition


NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def definition() -> ExerciseDefinition:
    return ExerciseDefinition.model_validate(
        {
            "exerciseId": "park-fire-decision",
            "version": "1",
            "name": "Park Fire",
            "description": "Exercise",
            "replayPackageId": "park-fire",
            "graphVersion": "1",
            "objectives": {
                "fastest-response": {
                    "travelWeight": 1,
                    "basePriorityWeight": 1,
                    "criticalServiceWeight": 1,
                    "populationDivisor": 1,
                    "populationWeight": 1,
                },
                "protect-critical-services": {
                    "travelWeight": 1,
                    "basePriorityWeight": 1,
                    "criticalServiceWeight": 1,
                    "populationDivisor": 1,
                    "populationWeight": 1,
                },
                "maximize-population-coverage": {
                    "travelWeight": 1,
                    "basePriorityWeight": 1,
                    "criticalServiceWeight": 1,
                    "populationDivisor": 1,
                    "populationWeight": 1,
                },
            },
            "assets": [],
            "resources": [],
            "checkpoints": [
                checkpoint("initial"),
                checkpoint("cascade"),
                checkpoint("field-report"),
            ],
            "sandbox": {
                "checkpointKeys": ["initial"],
                "closureEdgeIds": [],
                "windPresets": {},
                "priorityMultipliers": {"standard": 1, "elevated": 1, "urgent": 1},
            },
            "safetyStatement": "Exercise only",
        }
    )


def checkpoint(key: str) -> dict[str, object]:
    return {
        "checkpointKey": key,
        "title": key,
        "situationSummary": key,
        "decisionPrompt": key,
        "referenceAt": "2026-07-24T12:00:00Z",
        "historicalWeatherIdentity": "weather:1",
        "incidents": [],
        "tasks": [],
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
            return IdempotencyClaim(
                id=existing.id,
                request_hash=existing.request_hash,
                response_type=existing.response_type,
                response_id=existing.response_id,
                created=False,
            )
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

    async def create_session(self, **values: object) -> ExerciseSession:
        session = ExerciseSession(
            id=uuid4(),
            display_name=None,
            checkpoint_index=0,
            objective=None,
            status="active",
            version=1,
            consequences={},
            **values,  # type: ignore[arg-type]
        )
        self.sessions[session.id] = session
        return session

    async def get_session(self, session_id: UUID) -> ExerciseSession | None:
        return self.sessions.get(session_id)

    async def lock_session(self, session_id: UUID) -> ExerciseSession | None:
        return self.sessions.get(session_id)

    async def save_session(self, session: ExerciseSession) -> None:
        self.sessions[session.id] = session

    async def get_event(self, session_id: UUID, event_id: UUID) -> ExerciseEvent | None:
        return next(
            (
                item
                for item in self.events
                if item.id == event_id and item.session_id == session_id
            ),
            None,
        )

    async def get_creation_event(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        event_id: UUID,
    ) -> ExerciseEvent | None:
        event = next((item for item in self.events if item.id == event_id), None)
        if event is None or event.event_type != "exercise.session-created":
            return None
        session = self.sessions.get(event.session_id)
        if session is None or (
            session.exercise_id,
            session.definition_version,
            session.definition_digest,
        ) != (exercise_id, definition_version, definition_digest):
            return None
        return event

    async def get_plan(self, session_id: UUID, plan_id: UUID) -> ExercisePlanRun | None:
        plan = next(
            (
                item
                for item in self.plans
                if item.id == plan_id and item.session_id == session_id
            ),
            None,
        )
        return None if plan is None else _frozen_plan(plan)

    async def latest_plan(
        self, session_id: UUID, checkpoint_key: str
    ) -> ExercisePlanRun | None:
        plan = next(
            (
                item
                for item in reversed(self.plans)
                if item.session_id == session_id
                and item.checkpoint_key == checkpoint_key
            ),
            None,
        )
        return None if plan is None else _frozen_plan(plan)

    async def latest_plan_for_session(self, session_id: UUID) -> ExercisePlanRun | None:
        plan = next(
            (item for item in reversed(self.plans) if item.session_id == session_id),
            None,
        )
        return None if plan is None else _frozen_plan(plan)

    async def list_plans(self, session_id: UUID) -> tuple[ExercisePlanRun, ...]:
        return tuple(
            _frozen_plan(item) for item in self.plans if item.session_id == session_id
        )

    async def list_events(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        return tuple(item for item in self.events if item.session_id == session_id)

    async def append_event(self, **values: object) -> ExerciseEvent:
        event = ExerciseEvent(  # type: ignore[arg-type]
            id=uuid4(),
            occurred_at=NOW,
            before_state=freeze_json_object(values.pop("before_state")),
            after_state=freeze_json_object(values.pop("after_state")),
            inputs=freeze_json_object(values.pop("inputs")),
            **values,
        )
        self.events.append(event)
        return event


def _frozen_plan(plan: ExercisePlanRun) -> ExercisePlanRun:
    return ExercisePlanRun(
        id=plan.id,
        session_id=plan.session_id,
        checkpoint_key=plan.checkpoint_key,
        input_hash=plan.input_hash,
        input_data=freeze_json_object(plan.input_data),
        output_data=freeze_json_object(plan.output_data),
        versions=freeze_json_object(plan.versions),
        created_at=plan.created_at,
    )


def service(
    repository: FakeExerciseRepository, *, now: datetime = NOW
) -> ExerciseSessionService:
    return ExerciseSessionService(
        definition=definition(),
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: now,
        callsign=lambda: "EMBER-101",
    )


def query(repository: FakeExerciseRepository) -> ExerciseQueryService:
    return ExerciseQueryService(
        definition=definition(),
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_new_session_gets_callsign_and_24_hour_expiry() -> None:
    repository = FakeExerciseRepository()

    session = await service(repository).create(idempotency_key="create-1")

    assert session.callsign == "EMBER-101"
    assert session.status == "active"
    assert session.version == 1
    assert session.expires_at == NOW + timedelta(hours=24)


@pytest.mark.asyncio
async def test_identical_objective_command_replays_original_version() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")

    first = await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    replay = await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )

    assert first.version == replay.version == 2
    assert len(repository.events) == 2


@pytest.mark.asyncio
async def test_replay_projects_original_response_after_later_changes() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    selected = await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    original = await commands.project(selected)
    repository.plans.append(
        ExercisePlanRun(
            uuid4(),
            session.id,
            "initial",
            "a" * 64,
            {"objective": "fastest-response"},
            {"status": "OPTIMAL"},
            {},
            NOW,
        )
    )
    selected.version = 3
    selected.checkpoint_index = 1

    replay = await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )

    assert await commands.project(replay) == original


@pytest.mark.asyncio
async def test_create_replay_projects_original_response_after_later_changes_and_expiry() -> (
    None
):
    repository = FakeExerciseRepository()
    commands = service(repository)
    created = await commands.create(idempotency_key="create")
    original = await commands.project(created)
    await commands.select_objective(
        created.id,
        "fastest-response",
        expected_version=1,
        idempotency_key="objective",
    )
    created.checkpoint_index = 1
    created.version = 3

    replay = await service(repository, now=NOW + timedelta(hours=25)).create(
        idempotency_key="create"
    )

    assert await commands.project(replay) == original


@pytest.mark.asyncio
async def test_forged_same_session_snapshot_is_rejected() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    event = repository.events[-1]
    repository.events[-1] = replace(
        event,
        inputs=freeze_json_object(
            {
                **event.inputs,
                "_responseProjection": {
                    **event.inputs["_responseProjection"],
                    "version": 999,
                },
            }
        ),
    )

    with pytest.raises(RuntimeError, match="exercise replay response is invalid"):
        await commands.select_objective(
            session.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="objective",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot.pop("allowedActions"),
        lambda snapshot: snapshot.__setitem__("unexpected", True),
        lambda snapshot: snapshot.__setitem__("allowedActions", ("", 1)),
        lambda snapshot: snapshot.__setitem__("currentCheckpoint", {}),
        lambda snapshot: snapshot.__setitem__("latestPlan", "not-an-object"),
    ],
)
async def test_replay_rejects_malformed_full_projection(
    mutate: object,
) -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    event = repository.events[-1]
    snapshot = dict(event.inputs["_responseProjection"])
    mutate(snapshot)  # type: ignore[operator]
    repository.events[-1] = replace(
        event,
        inputs=freeze_json_object({**event.inputs, "_responseProjection": snapshot}),
    )

    with pytest.raises(RuntimeError, match="exercise replay response is invalid"):
        await commands.select_objective(
            session.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="objective",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actions",
    [
        (),
        ("unknown",),
        (" select-objective", "generate-plan"),
        ("select-objective", "select-objective"),
        ("view-debrief",),
    ],
)
async def test_replay_rejects_actions_impossible_for_session_state(
    actions: tuple[str, ...],
) -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    event = repository.events[-1]
    repository.events[-1] = replace(
        event,
        inputs=freeze_json_object(
            {
                **event.inputs,
                "_responseProjection": {
                    **event.inputs["_responseProjection"],
                    "allowedActions": actions,
                },
            }
        ),
    )

    with pytest.raises(RuntimeError, match="exercise replay response is invalid"):
        await commands.select_objective(
            session.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="objective",
        )


@pytest.mark.asyncio
async def test_mismatched_definition_session_is_unavailable_to_commands_and_queries() -> (
    None
):
    repository = FakeExerciseRepository()
    session = await service(repository).create(idempotency_key="create")
    session.definition_digest = "b" * 64

    with pytest.raises(ExerciseSessionNotFound):
        await service(repository).select_objective(
            session.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="objective",
        )
    with pytest.raises(ExerciseSessionNotFound):
        await query(repository).session(session.id)


@pytest.mark.asyncio
async def test_blank_idempotency_key_is_rejected() -> None:
    with pytest.raises(ExerciseCommandInvalid):
        await service(FakeExerciseRepository()).create(idempotency_key=" ")


@pytest.mark.asyncio
async def test_audit_hides_private_replay_snapshot() -> None:
    repository = FakeExerciseRepository()
    session = await service(repository).create(idempotency_key="create")
    await service(repository).select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )

    events = await query(repository).audit(session.id)

    assert events[-1].inputs == {"objective": "fastest-response"}
    with pytest.raises(TypeError):
        events[-1].inputs["changed"] = True  # type: ignore[index]

    await repository.append_event(
        session_id=session.id,
        event_type="exercise.test",
        actor_callsign=session.callsign,
        display_name=None,
        expected_session_version=2,
        resulting_session_version=3,
        before_state={},
        after_state={},
        inputs={"public": {"nested": ["value"]}},
        note=None,
    )
    nested = (await query(repository).audit(session.id))[-1].inputs["public"]
    with pytest.raises(TypeError):
        nested["changed"] = True  # type: ignore[index]


@pytest.mark.asyncio
async def test_forged_cross_session_event_claim_cannot_replay() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    first = await commands.create(idempotency_key="first")
    second = await commands.create(idempotency_key="second")
    foreign = await repository.append_event(
        session_id=second.id,
        event_type="exercise.objective-selected",
        actor_callsign=second.callsign,
        display_name=None,
        expected_session_version=1,
        resulting_session_version=2,
        before_state={},
        after_state={},
        inputs={},
        note=None,
    )
    repository.claims[(f"exercise-session:{first.id}:select-objective", "forged")] = (
        IdempotencyClaim(
            uuid4(),
            _request_hash(
                {
                    "sessionId": str(first.id),
                    "expectedVersion": 1,
                    "payload": {"objective": "fastest-response"},
                }
            ),
            "exercise_event",
            foreign.id,
            False,
        )
    )

    with pytest.raises(RuntimeError, match="exercise idempotency event does not exist"):
        await commands.select_objective(
            first.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="forged",
        )


@pytest.mark.asyncio
async def test_same_key_with_different_objective_conflicts() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    await commands.select_objective(
        session.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )

    with pytest.raises(ExerciseIdempotencyConflict):
        await commands.select_objective(
            session.id,
            "protect-critical-services",
            expected_version=1,
            idempotency_key="objective",
        )

    assert repository.sessions[session.id].objective == "fastest-response"


@pytest.mark.asyncio
async def test_stale_expected_version_does_not_append_event() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")

    with pytest.raises(ExerciseVersionConflict):
        await commands.select_objective(
            session.id,
            "fastest-response",
            expected_version=2,
            idempotency_key="objective",
        )

    assert len(repository.events) == 1


@pytest.mark.asyncio
async def test_expired_session_is_read_only_without_persisted_side_effects() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository, now=NOW + timedelta(hours=25))
    session = ExerciseSession(
        id=uuid4(),
        exercise_id="park-fire-decision",
        definition_version="1",
        definition_digest="a" * 64,
        callsign="EMBER-101",
        display_name=None,
        checkpoint_index=0,
        objective=None,
        status="active",
        version=1,
        consequences={},
        expires_at=NOW + timedelta(hours=24),
    )
    repository.sessions[session.id] = session

    with pytest.raises(ExerciseSessionExpired):
        await commands.select_objective(
            session.id,
            "fastest-response",
            expected_version=1,
            idempotency_key="objective",
        )

    projection = await commands.project(session)
    assert projection["status"] == "expired"
    assert repository.sessions[session.id].objective is None
    assert repository.sessions[session.id].version == 1


@pytest.mark.asyncio
async def test_checkpoint_two_acceptance_records_corridor_cleared() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 1
    session.version = 2
    repository.plans.append(
        ExercisePlanRun(
            uuid4(),
            session.id,
            "cascade",
            "a" * 64,
            {"objective": session.objective},
            {
                "status": "OPTIMAL",
                "assignments": [{"taskId": "clear-primary-corridor"}],
            },
            {},
            NOW,
        )
    )

    result = await commands.advance(
        session.id, expected_version=2, idempotency_key="advance"
    )

    assert result.consequences == {"corridorCleared": True}


@pytest.mark.asyncio
async def test_checkpoint_two_without_road_crew_keeps_corridor_closed() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 1
    session.version = 2
    repository.plans.append(
        ExercisePlanRun(
            uuid4(),
            session.id,
            "cascade",
            "a" * 64,
            {"objective": session.objective},
            {"status": "OPTIMAL", "assignments": []},
            {},
            NOW,
        )
    )

    result = await commands.advance(
        session.id, expected_version=2, idempotency_key="advance"
    )

    assert result.consequences == {"corridorCleared": False}


@pytest.mark.asyncio
async def test_final_approval_requires_checkpoint_three() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")

    with pytest.raises(
        ExerciseTransitionInvalid, match="final decision requires checkpoint three"
    ):
        await commands.decide(
            session.id,
            display_name=None,
            note="approved",
            expected_version=1,
            idempotency_key="decision",
        )


@pytest.mark.asyncio
async def test_final_approval_requires_validated_override() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 2
    session.version = 2

    with pytest.raises(
        ExerciseTransitionInvalid, match="final decision requires a validated override"
    ):
        await commands.decide(
            session.id,
            display_name=None,
            note="approved",
            expected_version=2,
            idempotency_key="decision",
        )


@pytest.mark.asyncio
async def test_final_approval_requires_nonblank_note() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 2
    session.version = 2

    with pytest.raises(ExerciseCommandInvalid, match="decision note must not be blank"):
        await commands.decide(
            session.id,
            display_name=None,
            note=" ",
            expected_version=2,
            idempotency_key="decision",
        )


@pytest.mark.asyncio
async def test_final_approval_is_append_only() -> None:
    repository = FakeExerciseRepository()
    commands = service(repository)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 2
    session.version = 2
    repository.plans.append(
        ExercisePlanRun(
            uuid4(),
            session.id,
            "field-report",
            "a" * 64,
            {"objective": session.objective},
            {"operatorOverride": {"resourceId": "bus"}},
            {},
            NOW,
        )
    )
    await commands.decide(
        session.id,
        display_name=" Alex ",
        note=" approved ",
        expected_version=2,
        idempotency_key="first",
    )

    with pytest.raises(
        ExerciseTransitionInvalid, match="exercise session is not active"
    ):
        await commands.decide(
            session.id,
            display_name="Alex",
            note="approved",
            expected_version=3,
            idempotency_key="second",
        )

    assert [event.event_type for event in repository.events].count(
        "exercise.plan-approved"
    ) == 1


@pytest.mark.parametrize(
    "state",
    [
        {"id": str(uuid4()), "exerciseId": "x"},
        {
            "id": str(uuid4()),
            "exerciseId": "x",
            "definitionVersion": "1",
            "definitionDigest": "a",
            "callsign": "c",
            "displayName": None,
            "checkpointIndex": 0,
            "objective": None,
            "status": "active",
            "version": 1,
            "consequences": {},
            "expiresAt": "2026-07-24T12:00:00+00:00",
            "unexpected": True,
        },
        {
            "id": str(uuid4()),
            "exerciseId": "x",
            "definitionVersion": "1",
            "definitionDigest": "a",
            "callsign": "c",
            "displayName": None,
            "checkpointIndex": True,
            "objective": None,
            "status": "active",
            "version": 1,
            "consequences": {},
            "expiresAt": "2026-07-24T12:00:00+00:00",
        },
        {
            "id": str(uuid4()),
            "exerciseId": "x",
            "definitionVersion": "1",
            "definitionDigest": "a",
            "callsign": "c",
            "displayName": None,
            "checkpointIndex": 0,
            "objective": None,
            "status": "active",
            "version": 1.0,
            "consequences": {},
            "expiresAt": "not-a-datetime",
        },
    ],
)
def test_stored_session_state_rejects_missing_unknown_and_coerced_values(
    state: dict[str, object],
) -> None:
    with pytest.raises(RuntimeError, match="stored exercise state is invalid"):
        _session_from_state(state)
