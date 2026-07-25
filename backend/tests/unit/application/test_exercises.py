from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseEvent,
    ExerciseIdempotencyConflict,
    ExercisePlanRun,
    ExerciseSession,
    ExerciseSessionExpired,
    ExerciseSessionService,
    ExerciseTransitionInvalid,
    ExerciseVersionConflict,
    _session_from_state,
)
from wildfireops.domain.scenario_versions import IdempotencyClaim
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

    async def get_event(self, event_id: UUID) -> ExerciseEvent | None:
        return next((item for item in self.events if item.id == event_id), None)

    async def get_plan(self, plan_id: UUID) -> ExercisePlanRun | None:
        return next((item for item in self.plans if item.id == plan_id), None)

    async def latest_plan(
        self, session_id: UUID, checkpoint_key: str
    ) -> ExercisePlanRun | None:
        return next(
            (
                item
                for item in reversed(self.plans)
                if item.session_id == session_id
                and item.checkpoint_key == checkpoint_key
            ),
            None,
        )

    async def latest_plan_for_session(self, session_id: UUID) -> ExercisePlanRun | None:
        return next(
            (item for item in reversed(self.plans) if item.session_id == session_id),
            None,
        )

    async def list_plans(self, session_id: UUID) -> tuple[ExercisePlanRun, ...]:
        return tuple(item for item in self.plans if item.session_id == session_id)

    async def list_events(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        return tuple(item for item in self.events if item.session_id == session_id)

    async def append_event(self, **values: object) -> ExerciseEvent:
        event = ExerciseEvent(id=uuid4(), occurred_at=NOW, **values)  # type: ignore[arg-type]
        self.events.append(event)
        return event


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
