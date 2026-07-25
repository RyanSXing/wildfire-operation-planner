import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, Protocol, cast
from uuid import UUID

from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.domain.observations import freeze_json_object
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
_RESPONSE_SNAPSHOT = "_responseProjection"
_PROJECTION_KEYS = _STATE_KEYS | {
    "allowedActions",
    "currentCheckpoint",
    "latestPlan",
}
_ACTION_OPTIONS = {
    "expired": frozenset({("start-new-exercise",)}),
    "completed": frozenset({("view-debrief",)}),
    "objective": frozenset({("select-objective",)}),
    "checkpoint": frozenset(
        {
            ("select-objective", "advance"),
            ("select-objective", "generate-plan"),
        }
    ),
    "final": frozenset(
        {
            ("select-objective", "generate-plan"),
            ("approve-plan",),
            ("select-objective", "apply-override"),
        }
    ),
}


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
    response_projection: Mapping[str, object] | None = field(
        default=None, repr=False, compare=False
    )


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
    async def get_event(
        self, session_id: UUID, event_id: UUID
    ) -> ExerciseEvent | None: ...
    async def get_creation_event(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        event_id: UUID,
    ) -> ExerciseEvent | None: ...
    async def get_plan(
        self, session_id: UUID, plan_id: UUID
    ) -> ExercisePlanRun | None: ...
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

    def __init__(self, message: str, *, fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.fields = fields


class ExerciseIdempotencyConflict(ExerciseError):
    code = "exercise_idempotency_conflict"


def _require_definition(
    session: ExerciseSession,
    definition: ExerciseDefinition,
    definition_digest: str,
) -> None:
    if (
        session.exercise_id != definition.exercise_id
        or session.definition_version != definition.version
        or session.definition_digest != definition_digest
    ):
        raise ExerciseSessionNotFound("exercise session was not found")


def _validate_replay_snapshot(
    snapshot: object,
    session: ExerciseSession,
    definition: ExerciseDefinition,
) -> None:
    if not isinstance(snapshot, MappingProxyType) or set(snapshot) != _PROJECTION_KEYS:
        raise RuntimeError("exercise replay response is invalid")
    actions = snapshot["allowedActions"]
    if not isinstance(actions, tuple) or actions not in _allowed_action_options(
        session
    ):
        raise RuntimeError("exercise replay response is invalid")
    checkpoint = snapshot["currentCheckpoint"]
    expected_checkpoint = freeze_json_object(
        definition.checkpoints[session.checkpoint_index].model_dump(
            mode="json", by_alias=True
        )
    )
    if (
        not isinstance(checkpoint, MappingProxyType)
        or checkpoint != expected_checkpoint
    ):
        raise RuntimeError("exercise replay response is invalid")
    latest_plan = snapshot["latestPlan"]
    if latest_plan is not None and not isinstance(latest_plan, MappingProxyType):
        raise RuntimeError("exercise replay response is invalid")
    try:
        snapshot_session = _session_from_state(
            {key: snapshot.get(key) for key in _STATE_KEYS}
        )
    except RuntimeError as error:
        raise RuntimeError("exercise replay response is invalid") from error
    if _session_state(snapshot_session) != _session_state(session):
        raise RuntimeError("exercise replay response is invalid")


def _allowed_action_options(session: ExerciseSession) -> frozenset[tuple[str, ...]]:
    if session.status == "expired":
        return _ACTION_OPTIONS["expired"]
    if session.status == "completed":
        return _ACTION_OPTIONS["completed"]
    if session.objective is None:
        return _ACTION_OPTIONS["objective"]
    return _ACTION_OPTIONS["checkpoint" if session.checkpoint_index < 2 else "final"]


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
        _require_definition(session, self._definition, self._definition_digest)
        if session.response_projection is not None:
            return _copy_json_object(session.response_projection)
        return await session_projection(
            self._definition,
            self._definition_digest,
            self._repository,
            session,
            self._clock(),
        )

    async def create(self, *, idempotency_key: str) -> ExerciseSession:
        key = _idempotency_key(idempotency_key)
        request_hash = _request_hash({})
        claim = await self._repository.claim_idempotency(
            scope=f"exercise:{self.exercise_id}:session-create",
            key=key,
            request_hash=request_hash,
        )
        if not claim.created:
            if claim.request_hash != request_hash:
                raise ExerciseIdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            if claim.response_type != "exercise_event" or claim.response_id is None:
                raise RuntimeError("exercise idempotency response is incomplete")
            event = await self._repository.get_creation_event(
                exercise_id=self.exercise_id,
                definition_version=self._definition.version,
                definition_digest=self._definition_digest,
                event_id=claim.response_id,
            )
            if event is None:
                raise RuntimeError("exercise idempotency event does not exist")
            return self._replay_session(event)
        session = await self._repository.create_session(
            exercise_id=self.exercise_id,
            definition_version=self._definition.version,
            definition_digest=self._definition_digest,
            callsign=self._callsign(),
            expires_at=self._clock() + timedelta(hours=24),
        )
        snapshot = await self._response_snapshot(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.session-created",
            actor_callsign=session.callsign,
            display_name=None,
            expected_session_version=0,
            resulting_session_version=1,
            before_state={},
            after_state=_session_state(session),
            inputs=_event_inputs({}, snapshot),
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        session.response_projection = freeze_json_object(snapshot)
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
            return self._replay_session(replayed)
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
        snapshot = await self._response_snapshot(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.objective-selected",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs=_event_inputs({"objective": objective}, snapshot),
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        session.response_projection = freeze_json_object(snapshot)
        return session

    async def advance(
        self, session_id: UUID, *, expected_version: int, idempotency_key: str
    ) -> ExerciseSession:
        session, claim, replayed = await self.lock_command(
            session_id, expected_version, idempotency_key, "advance", {}
        )
        if replayed is not None:
            return self._replay_session(replayed)
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
            if not isinstance(assignments, Sequence) or isinstance(
                assignments, (str, bytes, bytearray, Mapping)
            ):
                assignments = ()
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
        snapshot = await self._response_snapshot(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.checkpoint-advanced",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs=_event_inputs({"acceptedPlanId": str(latest.id)}, snapshot),
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        session.response_projection = freeze_json_object(snapshot)
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
            return self._replay_session(replayed)
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
        snapshot = await self._response_snapshot(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.plan-approved",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs=_event_inputs({"planId": str(latest.id)}, snapshot),
            note=normalized_note,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id, response_type="exercise_event", response_id=event.id
        )
        session.response_projection = freeze_json_object(snapshot)
        return session

    async def _replay_event(
        self, session_id: UUID, claim: IdempotencyClaim
    ) -> ExerciseEvent | None:
        if claim.created:
            return None
        if claim.response_type != "exercise_event" or claim.response_id is None:
            raise RuntimeError("exercise idempotency response is incomplete")
        event = await self._repository.get_event(session_id, claim.response_id)
        if event is None:
            raise RuntimeError("exercise idempotency event does not exist")
        return event

    async def _response_snapshot(self, session: ExerciseSession) -> dict[str, object]:
        return _copy_json_object(
            freeze_json_object(
                await session_projection(
                    self._definition,
                    self._definition_digest,
                    self._repository,
                    session,
                    self._clock(),
                )
            )
        )

    def _replay_session(self, event: ExerciseEvent) -> ExerciseSession:
        session = _session_from_state(event.after_state)
        _require_definition(session, self._definition, self._definition_digest)
        snapshot = event.inputs.get(_RESPONSE_SNAPSHOT)
        _validate_replay_snapshot(snapshot, session, self._definition)
        assert isinstance(snapshot, Mapping)
        session.response_projection = freeze_json_object(snapshot)
        return session

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
        key = _idempotency_key(idempotency_key)
        claim = await self._repository.claim_idempotency(
            scope=f"exercise-session:{session_id}:{command}",
            key=key,
            request_hash=request_hash,
        )
        if not claim.created:
            if claim.request_hash != request_hash:
                raise ExerciseIdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            event = await self._replay_event(session_id, claim)
            if event is None:
                raise RuntimeError("exercise replay response is missing")
            current = await self._repository.get_session(session_id)
            if current is None:
                raise ExerciseSessionNotFound("exercise session was not found")
            _require_definition(current, self._definition, self._definition_digest)
            return current, claim, event
        session = await self._repository.lock_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        _require_definition(session, self._definition, self._definition_digest)
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
        definition_digest: str,
        repository: ExerciseRepositoryProtocol,
        clock: Callable[[], datetime],
    ) -> None:
        self._definition = definition
        self._definition_digest = definition_digest
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
        _require_definition(session, self._definition, self._definition_digest)
        return await session_projection(
            self._definition,
            self._definition_digest,
            self._repository,
            session,
            self._clock(),
        )

    async def audit(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        _require_definition(session, self._definition, self._definition_digest)
        return tuple(
            _public_event(item)
            for item in await self._repository.list_events(session_id)
        )

    async def debrief(self, session_id: UUID) -> Mapping[str, object]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        _require_definition(session, self._definition, self._definition_digest)
        if session.status != "completed":
            raise ExerciseTransitionInvalid("debrief requires a completed exercise")
        plans = await self._repository.list_plans(session.id)
        events = await self._repository.list_events(session.id)
        if not plans:
            raise RuntimeError("completed exercise has no plan")
        public_plans = tuple(_plan_envelope(item) for item in plans)
        return freeze_json_object(
            {
                "session": _session_state(session),
                "plans": public_plans,
                "finalPlan": public_plans[-1],
                "events": tuple(_event_envelope(_public_event(item)) for item in events),
            }
        )


def _idempotency_key(value: str) -> str:
    if not isinstance(value, str):
        raise ExerciseCommandInvalid(
            "idempotency key must be between 1 and 255 characters"
        )
    key = value.strip()
    if not key or len(key) > 255:
        raise ExerciseCommandInvalid(
            "idempotency key must be between 1 and 255 characters"
        )
    return key


def _event_inputs(
    inputs: Mapping[str, object], response_projection: Mapping[str, object]
) -> dict[str, object]:
    return {
        **dict(inputs),
        _RESPONSE_SNAPSHOT: _json_for_storage(response_projection),
    }


def _public_inputs(inputs: Mapping[str, object]) -> Mapping[str, object]:
    return freeze_json_object(
        {key: value for key, value in inputs.items() if key != _RESPONSE_SNAPSHOT}
    )


def _public_event(event: ExerciseEvent) -> ExerciseEvent:
    return ExerciseEvent(
        id=event.id,
        session_id=event.session_id,
        event_type=event.event_type,
        actor_callsign=event.actor_callsign,
        display_name=event.display_name,
        expected_session_version=event.expected_session_version,
        resulting_session_version=event.resulting_session_version,
        before_state=event.before_state,
        after_state=event.after_state,
        inputs=_public_inputs(event.inputs),
        note=event.note,
        occurred_at=event.occurred_at,
    )


def _plan_envelope(plan: ExercisePlanRun) -> Mapping[str, object]:
    return freeze_json_object(
        {
            "id": str(plan.id),
            "sessionId": str(plan.session_id),
            "checkpointKey": plan.checkpoint_key,
            "inputHash": plan.input_hash,
            "inputData": plan.input_data,
            "outputData": plan.output_data,
            "versions": plan.versions,
            "createdAt": plan.created_at.isoformat(),
        }
    )


def _event_envelope(event: ExerciseEvent) -> Mapping[str, object]:
    return freeze_json_object(
        {
            "id": str(event.id),
            "sessionId": str(event.session_id),
            "eventType": event.event_type,
            "actorCallsign": event.actor_callsign,
            "displayName": event.display_name,
            "expectedSessionVersion": event.expected_session_version,
            "resultingSessionVersion": event.resulting_session_version,
            "beforeState": event.before_state,
            "afterState": event.after_state,
            "inputs": event.inputs,
            "note": event.note,
            "occurredAt": event.occurred_at.isoformat(),
        }
    )


def _copy_json_object(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _copy_json_value(item) for key, item in value.items()}


def _copy_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _copy_json_object(value)
    if isinstance(value, tuple):
        return tuple(_copy_json_value(item) for item in value)
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _mutable_json_object(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _mutable_json_value(item) for key, item in value.items()}


def _mutable_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _mutable_json_object(value)
    if isinstance(value, tuple):
        return [_mutable_json_value(item) for item in value]
    return value


def _json_for_storage(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_for_storage(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_for_storage(item) for item in value]
    if isinstance(value, list):
        return [_json_for_storage(item) for item in value]
    return value


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
        if not isinstance(consequences, Mapping):
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
            consequences=_mutable_json_object(freeze_json_object(consequences)),
            expires_at=parsed_expiry.astimezone(UTC),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise RuntimeError("stored exercise state is invalid") from error


async def session_projection(
    definition: ExerciseDefinition,
    definition_digest: str,
    repository: ExerciseRepositoryProtocol,
    session: ExerciseSession,
    now: datetime,
) -> dict[str, object]:
    _require_definition(session, definition, definition_digest)
    projected = ExerciseSession(
        id=session.id,
        exercise_id=session.exercise_id,
        definition_version=session.definition_version,
        definition_digest=session.definition_digest,
        callsign=session.callsign,
        display_name=session.display_name,
        checkpoint_index=session.checkpoint_index,
        objective=session.objective,
        status=session.status,
        version=session.version,
        consequences=_copy_json_object(freeze_json_object(session.consequences)),
        expires_at=session.expires_at,
    )
    if projected.status == "active" and now >= projected.expires_at:
        projected.status = "expired"
    plans = await repository.list_plans(projected.id)
    latest = plans[-1] if plans else None
    latest_valid = next(
        (
            item
            for item in reversed(plans)
            if item.output_data.get("status") in {"FEASIBLE", "OPTIMAL"}
        ),
        None,
    )
    return {
        **_session_state(projected),
        "allowedActions": _allowed_actions(
            projected,
            latest,
            definition.checkpoints[projected.checkpoint_index].checkpoint_key,
        ),
        "currentCheckpoint": definition.checkpoints[
            projected.checkpoint_index
        ].model_dump(mode="json", by_alias=True),
        "latestPlan": None if latest_valid is None else dict(latest_valid.output_data),
    }


def _allowed_actions(
    session: ExerciseSession,
    latest: ExercisePlanRun | None,
    checkpoint_key: str,
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
            == checkpoint_key
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
        or latest.checkpoint_key != checkpoint_key
        or latest.input_data.get("objective") != session.objective
        or latest.output_data.get("status") not in {"FEASIBLE", "OPTIMAL"}
    ):
        return ("select-objective", "generate-plan")
    return (
        ("approve-plan",)
        if latest.output_data.get("operatorOverride")
        else ("select-objective", "apply-override")
    )
