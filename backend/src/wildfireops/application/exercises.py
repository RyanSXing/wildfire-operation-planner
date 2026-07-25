import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal, Protocol, cast
from uuid import UUID

from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.replay.exercise import ExerciseDefinition, ObjectivePreset


type SessionStatus = Literal["active", "completed", "expired"]

_OBJECTIVES = frozenset(
    {
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    }
)
_STATE_KEYS = frozenset(
    {
        "id",
        "exerciseId",
        "definitionVersion",
        "definitionDigest",
        "callsign",
        "displayName",
        "checkpointIndex",
        "objective",
        "status",
        "version",
        "consequences",
        "expiresAt",
    }
)


@dataclass(slots=True)
class ExerciseSession:
    id: UUID
    exercise_id: str
    definition_version: str
    definition_digest: str
    callsign: str
    display_name: str | None
    checkpoint_index: int
    objective: ObjectivePreset | None
    status: SessionStatus
    version: int
    consequences: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExercisePlanRun:
    id: UUID
    session_id: UUID
    checkpoint_key: str
    input_hash: str
    input_data: Mapping[str, object]
    output_data: Mapping[str, object]
    versions: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExerciseEvent:
    id: UUID
    session_id: UUID
    event_type: str
    actor_callsign: str
    display_name: str | None
    expected_session_version: int
    resulting_session_version: int
    before_state: Mapping[str, object]
    after_state: Mapping[str, object]
    inputs: Mapping[str, object]
    note: str | None
    occurred_at: datetime


class ExerciseRepositoryProtocol(Protocol):
    async def claim_idempotency(
        self, *, scope: str, key: str, request_hash: str
    ) -> IdempotencyClaim: ...
    async def complete_idempotency(
        self, *, claim_id: UUID, response_type: str, response_id: UUID
    ) -> None: ...
    async def create_session(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        callsign: str,
        expires_at: datetime,
    ) -> ExerciseSession: ...
    async def get_session(self, session_id: UUID) -> ExerciseSession | None: ...
    async def lock_session(self, session_id: UUID) -> ExerciseSession | None: ...
    async def save_session(self, session: ExerciseSession) -> None: ...
    async def store_plan(
        self,
        *,
        session_id: UUID,
        checkpoint_key: str,
        input_hash: str,
        input_data: dict[str, object],
        output_data: dict[str, object],
        versions: dict[str, object],
        idempotency_key_id: UUID | None,
    ) -> ExercisePlanRun: ...
    async def get_event(self, event_id: UUID) -> ExerciseEvent | None: ...
    async def get_plan(self, plan_id: UUID) -> ExercisePlanRun | None: ...
    async def latest_plan(
        self, session_id: UUID, checkpoint_key: str
    ) -> ExercisePlanRun | None: ...
    async def latest_plan_for_session(
        self, session_id: UUID
    ) -> ExercisePlanRun | None: ...
    async def list_plans(self, session_id: UUID) -> tuple[ExercisePlanRun, ...]: ...
    async def list_events(self, session_id: UUID) -> tuple[ExerciseEvent, ...]: ...
    async def append_event(
        self,
        *,
        session_id: UUID,
        event_type: str,
        actor_callsign: str,
        display_name: str | None,
        expected_session_version: int,
        resulting_session_version: int,
        before_state: dict[str, object],
        after_state: dict[str, object],
        inputs: dict[str, object],
        note: str | None,
    ) -> ExerciseEvent: ...


class ExerciseError(ValueError):
    code = "exercise_error"


class ExerciseNotFound(ExerciseError):
    code = "exercise_not_found"


class ExerciseSessionNotFound(ExerciseError):
    code = "exercise_session_not_found"


class ExerciseSessionExpired(ExerciseError):
    code = "exercise_session_expired"


class ExerciseVersionConflict(ExerciseError):
    code = "exercise_session_version_conflict"


class ExerciseTransitionInvalid(ExerciseError):
    code = "exercise_transition_invalid"


class ExerciseCommandInvalid(ExerciseError):
    code = "exercise_command_invalid"


class ExerciseIdempotencyConflict(ExerciseError):
    code = "exercise_idempotency_conflict"


class ExerciseSessionService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        definition_digest: str,
        repository: ExerciseRepositoryProtocol,
        clock: Callable[[], datetime],
        callsign: Callable[[], str],
    ) -> None:
        self._definition = definition
        self._definition_digest = definition_digest
        self._repository = repository
        self._clock = clock
        self._callsign = callsign

    @property
    def exercise_id(self) -> str:
        return self._definition.exercise_id

    async def project(self, session: ExerciseSession) -> dict[str, object]:
        return await session_projection(
            self._definition, self._repository, session, self._clock()
        )

    async def create(self, *, idempotency_key: str) -> ExerciseSession:
        claim = await self._repository.claim_idempotency(
            scope=f"exercise:{self.exercise_id}:session-create",
            key=idempotency_key,
            request_hash=_request_hash({}),
        )
        replayed = await self._replay_event(claim)
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        session = await self._repository.create_session(
            exercise_id=self.exercise_id,
            definition_version=self._definition.version,
            definition_digest=self._definition_digest,
            callsign=self._callsign(),
            expires_at=self._clock() + timedelta(hours=24),
        )
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.session-created",
            actor_callsign=session.callsign,
            display_name=None,
            expected_session_version=0,
            resulting_session_version=1,
            before_state={},
            after_state=_session_state(session),
            inputs={},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        return session

    async def select_objective(
        self,
        session_id: UUID,
        objective: ObjectivePreset,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> ExerciseSession:
        session, claim, replayed = await self.lock_command(
            session_id,
            expected_version,
            idempotency_key,
            "select-objective",
            {"objective": objective},
        )
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        if objective not in self._definition.objectives:
            raise ExerciseCommandInvalid(f"unsupported objective: {objective}")
        latest = await self._repository.latest_plan_for_session(session.id)
        if latest is not None and latest.output_data.get("operatorOverride"):
            raise ExerciseTransitionInvalid(
                "objective cannot change after a validated override"
            )
        before = _session_state(session)
        session.objective = objective
        session.version += 1
        await self._repository.save_session(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.objective-selected",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs={"objective": objective},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        return session

    async def advance(
        self, session_id: UUID, *, expected_version: int, idempotency_key: str
    ) -> ExerciseSession:
        session, claim, replayed = await self.lock_command(
            session_id, expected_version, idempotency_key, "advance", {}
        )
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        if session.checkpoint_index >= 2:
            raise ExerciseTransitionInvalid("checkpoint three cannot advance")
        latest = await self._repository.latest_plan(
            session.id,
            self._definition.checkpoints[session.checkpoint_index].checkpoint_key,
        )
        if (
            latest is None
            or latest.output_data.get("status") not in {"FEASIBLE", "OPTIMAL"}
            or latest.input_data.get("objective") != session.objective
        ):
            raise ExerciseTransitionInvalid("current checkpoint has no actionable plan")
        consequences = dict(session.consequences)
        if session.checkpoint_index == 1:
            assignments = latest.output_data.get("assignments", [])
            if not isinstance(assignments, list):
                assignments = []
            consequences["corridorCleared"] = any(
                item.get("taskId") == "clear-primary-corridor"
                for item in assignments
                if isinstance(item, Mapping)
            )
        before = _session_state(session)
        session.checkpoint_index += 1
        session.consequences = consequences
        session.version += 1
        await self._repository.save_session(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.checkpoint-advanced",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs={"acceptedPlanId": str(latest.id)},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        return session

    async def decide(
        self,
        session_id: UUID,
        *,
        display_name: str | None,
        note: str,
        expected_version: int,
        idempotency_key: str,
    ) -> ExerciseSession:
        session, claim, replayed = await self.lock_command(
            session_id,
            expected_version,
            idempotency_key,
            "decide",
            {"displayName": display_name, "note": note},
        )
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        if session.checkpoint_index != 2:
            raise ExerciseTransitionInvalid("final decision requires checkpoint three")
        normalized_note = note.strip()
        if not normalized_note:
            raise ExerciseCommandInvalid("decision note must not be blank")
        normalized_name = None if display_name is None else display_name.strip()
        if normalized_name == "":
            raise ExerciseCommandInvalid("display name must not be blank")
        if normalized_name is not None and len(normalized_name) > 120:
            raise ExerciseCommandInvalid("display name must not exceed 120 characters")
        latest = await self._repository.latest_plan(session.id, "field-report")
        if (
            latest is None
            or latest.input_data.get("objective") != session.objective
            or not latest.output_data.get("operatorOverride")
        ):
            raise ExerciseTransitionInvalid(
                "final decision requires a validated override"
            )
        before = _session_state(session)
        session.display_name = normalized_name
        session.status = "completed"
        session.version += 1
        await self._repository.save_session(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.plan-approved",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs={"planId": str(latest.id)},
            note=normalized_note,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        return session

    async def _replay_event(self, claim: IdempotencyClaim) -> ExerciseEvent | None:
        if claim.created:
            return None
        if claim.response_type != "exercise_event" or claim.response_id is None:
            raise RuntimeError("exercise idempotency response is incomplete")
        event = await self._repository.get_event(claim.response_id)
        if event is None:
            raise RuntimeError("exercise idempotency event does not exist")
        return event

    async def lock_command(
        self,
        session_id: UUID,
        expected_version: int,
        idempotency_key: str,
        command: str,
        payload: Mapping[str, object],
    ) -> tuple[ExerciseSession, IdempotencyClaim, ExerciseEvent | None]:
        request_hash = _request_hash(
            {
                "sessionId": str(session_id),
                "expectedVersion": expected_version,
                "payload": dict(payload),
            }
        )
        claim = await self._repository.claim_idempotency(
            scope=f"exercise-session:{session_id}:{command}",
            key=idempotency_key,
            request_hash=request_hash,
        )
        if not claim.created:
            if claim.request_hash != request_hash:
                raise ExerciseIdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            event = await self._replay_event(claim)
            if event is None:
                raise RuntimeError("exercise replay response is missing")
            current = await self._repository.get_session(session_id)
            if current is None:
                raise ExerciseSessionNotFound("exercise session was not found")
            return current, claim, event
        session = await self._repository.lock_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        if self._clock() >= session.expires_at:
            raise ExerciseSessionExpired("exercise session has expired")
        if session.status != "active":
            raise ExerciseTransitionInvalid("exercise session is not active")
        if session.version != expected_version:
            raise ExerciseVersionConflict(
                f"expected session version {expected_version}, current version {session.version}"
            )
        return session, claim, None


class ExerciseQueryService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        repository: ExerciseRepositoryProtocol,
        clock: Callable[[], datetime],
    ) -> None:
        self._definition = definition
        self._repository = repository
        self._clock = clock

    async def metadata(self, exercise_id: str) -> dict[str, object]:
        if exercise_id != self._definition.exercise_id:
            raise ExerciseNotFound("exercise was not found")
        return {
            "exerciseId": self._definition.exercise_id,
            "version": self._definition.version,
            "name": self._definition.name,
            "description": self._definition.description,
            "checkpointCount": len(self._definition.checkpoints),
            "objectives": sorted(self._definition.objectives),
            "safetyStatement": self._definition.safety_statement,
            "assets": [
                item.model_dump(mode="json", by_alias=True)
                for item in self._definition.assets
            ],
            "resources": [
                item.model_dump(mode="json", by_alias=True)
                for item in self._definition.resources
            ],
        }

    async def session(self, session_id: UUID) -> dict[str, object]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        return await session_projection(
            self._definition, self._repository, session, self._clock()
        )

    async def audit(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        if await self._repository.get_session(session_id) is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        return await self._repository.list_events(session_id)

    async def debrief(self, session_id: UUID) -> dict[str, object]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        if session.status != "completed":
            raise ExerciseTransitionInvalid("debrief requires a completed exercise")
        plans = await self._repository.list_plans(session.id)
        events = await self._repository.list_events(session.id)
        if not plans:
            raise RuntimeError("completed exercise has no plan")
        return {
            "session": _session_state(session),
            "plans": [dict(item.output_data) for item in plans],
            "finalPlan": dict(plans[-1].output_data),
            "events": [
                {
                    "eventType": item.event_type,
                    "inputs": dict(item.inputs),
                    "note": item.note,
                    "occurredAt": item.occurred_at.isoformat(),
                }
                for item in events
            ],
        }


def _request_hash(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _session_state(session: ExerciseSession) -> dict[str, object]:
    return {
        "id": str(session.id),
        "exerciseId": session.exercise_id,
        "definitionVersion": session.definition_version,
        "definitionDigest": session.definition_digest,
        "callsign": session.callsign,
        "displayName": session.display_name,
        "checkpointIndex": session.checkpoint_index,
        "objective": session.objective,
        "status": session.status,
        "version": session.version,
        "consequences": dict(session.consequences),
        "expiresAt": session.expires_at.isoformat(),
    }


def _session_from_state(state: Mapping[str, object]) -> ExerciseSession:
    if set(state) != _STATE_KEYS:
        raise RuntimeError("stored exercise state is invalid")
    try:
        identifier = state["id"]
        exercise_id = state["exerciseId"]
        definition_version = state["definitionVersion"]
        definition_digest = state["definitionDigest"]
        callsign = state["callsign"]
        display_name = state["displayName"]
        checkpoint_index = state["checkpointIndex"]
        objective = state["objective"]
        status = state["status"]
        version = state["version"]
        consequences = state["consequences"]
        expires_at = state["expiresAt"]
        if (
            not isinstance(identifier, str)
            or not isinstance(exercise_id, str)
            or not isinstance(definition_version, str)
            or not isinstance(definition_digest, str)
            or not isinstance(callsign, str)
        ):
            raise ValueError
        if display_name is not None and not isinstance(display_name, str):
            raise ValueError
        if (
            isinstance(checkpoint_index, bool)
            or not isinstance(checkpoint_index, int)
            or checkpoint_index not in (0, 1, 2)
        ):
            raise ValueError
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError
        if objective is not None and objective not in _OBJECTIVES:
            raise ValueError
        if status not in {"active", "completed", "expired"}:
            raise ValueError
        if not isinstance(consequences, dict) or not all(
            isinstance(key, str) for key in consequences
        ):
            raise ValueError
        if not isinstance(expires_at, str):
            raise ValueError
        parsed_expiry = datetime.fromisoformat(expires_at)
        if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() != timedelta(0):
            raise ValueError
        return ExerciseSession(
            id=UUID(identifier),
            exercise_id=exercise_id,
            definition_version=definition_version,
            definition_digest=definition_digest,
            callsign=callsign,
            display_name=display_name,
            checkpoint_index=checkpoint_index,
            objective=cast(ObjectivePreset | None, objective),
            status=cast(SessionStatus, status),
            version=version,
            consequences=dict(consequences),
            expires_at=parsed_expiry.astimezone(UTC),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise RuntimeError("stored exercise state is invalid") from error


async def session_projection(
    definition: ExerciseDefinition,
    repository: ExerciseRepositoryProtocol,
    session: ExerciseSession,
    now: datetime,
) -> dict[str, object]:
    projected = ExerciseSession(
        **{
            field: getattr(session, field)
            for field in ExerciseSession.__dataclass_fields__
        }
    )
    if projected.status == "active" and now >= projected.expires_at:
        projected.status = "expired"
    latest = await repository.latest_plan_for_session(projected.id)
    return {
        **_session_state(projected),
        "allowedActions": _allowed_actions(projected, latest),
        "currentCheckpoint": definition.checkpoints[
            projected.checkpoint_index
        ].model_dump(mode="json", by_alias=True),
        "latestPlan": None if latest is None else dict(latest.output_data),
    }


def session_checkpoint_key(index: int) -> str:
    try:
        return {0: "initial", 1: "cascade", 2: "field-report"}[index]
    except KeyError:
        raise RuntimeError("invalid exercise checkpoint index") from None


def _allowed_actions(
    session: ExerciseSession, latest: ExercisePlanRun | None
) -> tuple[str, ...]:
    if session.status == "expired":
        return ("start-new-exercise",)
    if session.status == "completed":
        return ("view-debrief",)
    if session.objective is None:
        return ("select-objective",)
    if session.checkpoint_index < 2:
        actionable = (
            latest is not None
            and latest.checkpoint_key
            == session_checkpoint_key(session.checkpoint_index)
            and latest.input_data.get("objective") == session.objective
            and latest.output_data.get("status") in {"FEASIBLE", "OPTIMAL"}
        )
        return (
            ("select-objective", "advance")
            if actionable
            else ("select-objective", "generate-plan")
        )
    if (
        latest is None
        or latest.checkpoint_key != "field-report"
        or latest.input_data.get("objective") != session.objective
    ):
        return ("select-objective", "generate-plan")
    return (
        ("approve-plan",)
        if latest.output_data.get("operatorOverride")
        else ("select-objective", "apply-override")
    )
