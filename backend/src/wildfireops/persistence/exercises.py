from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.application.exercises import (
    ExerciseEvent,
    ExercisePlanRun,
    ExerciseSession,
    _session_from_state,
)
from wildfireops.domain.observations import freeze_json_object
from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)
from wildfireops.persistence.scenarios import ScenarioRepository


class ExerciseRepository:
    """Session-bound adapter; the caller owns commit and rollback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._idempotency = ScenarioRepository(session)

    async def claim_idempotency(
        self, *, scope: str, key: str, request_hash: str
    ) -> IdempotencyClaim:
        return await self._idempotency.claim_idempotency(
            scope=scope, key=key, request_hash=request_hash
        )

    async def complete_idempotency(
        self, *, claim_id: UUID, response_type: str, response_id: UUID
    ) -> None:
        await self._idempotency.complete_idempotency(
            claim_id=claim_id, response_type=response_type, response_id=response_id
        )

    async def create_session(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        callsign: str,
        expires_at: datetime,
    ) -> ExerciseSession:
        model = ExerciseSessionModel(
            exercise_id=exercise_id,
            definition_version=definition_version,
            definition_digest=definition_digest,
            callsign=callsign,
            expires_at=expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        return _session(model)

    async def lock_session(self, session_id: UUID) -> ExerciseSession | None:
        model = await self._session.scalar(
            select(ExerciseSessionModel)
            .where(ExerciseSessionModel.id == session_id)
            .with_for_update()
        )
        return None if model is None else _session(model)

    async def get_session(self, session_id: UUID) -> ExerciseSession | None:
        model = await self._session.get(ExerciseSessionModel, session_id)
        return None if model is None else _session(model)

    async def save_session(self, session: ExerciseSession) -> None:
        model = await self._session.scalar(
            select(ExerciseSessionModel)
            .where(ExerciseSessionModel.id == session.id)
            .with_for_update()
        )
        if model is None:
            raise RuntimeError("exercise session does not exist")
        model.display_name = session.display_name
        model.checkpoint_index = session.checkpoint_index
        model.objective = session.objective
        model.status = session.status
        model.version = session.version
        model.consequences = dict(session.consequences)
        await self._session.flush()

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
    ) -> ExercisePlanRun:
        model = ExercisePlanRunModel(
            session_id=session_id,
            checkpoint_key=checkpoint_key,
            input_hash=input_hash,
            input_data=input_data,
            output_data=output_data,
            versions=versions,
            idempotency_key_id=idempotency_key_id,
        )
        self._session.add(model)
        await self._session.flush()
        return _plan(model)

    async def get_plan(self, session_id: UUID, plan_id: UUID) -> ExercisePlanRun | None:
        model = await self._session.scalar(
            select(ExercisePlanRunModel).where(
                ExercisePlanRunModel.id == plan_id,
                ExercisePlanRunModel.session_id == session_id,
            )
        )
        return None if model is None else _plan(model)

    async def latest_plan(
        self,
        session_id: UUID,
        checkpoint_key: str,
    ) -> ExercisePlanRun | None:
        model = await self._session.scalar(
            select(ExercisePlanRunModel)
            .where(
                ExercisePlanRunModel.session_id == session_id,
                ExercisePlanRunModel.checkpoint_key == checkpoint_key,
            )
            .order_by(ExercisePlanRunModel.insertion_order.desc())
            .limit(1)
        )
        return None if model is None else _plan(model)

    async def latest_plan_for_session(
        self,
        session_id: UUID,
    ) -> ExercisePlanRun | None:
        model = await self._session.scalar(
            select(ExercisePlanRunModel)
            .where(ExercisePlanRunModel.session_id == session_id)
            .order_by(ExercisePlanRunModel.insertion_order.desc())
            .limit(1)
        )
        return None if model is None else _plan(model)

    async def list_plans(self, session_id: UUID) -> tuple[ExercisePlanRun, ...]:
        rows = await self._session.scalars(
            select(ExercisePlanRunModel)
            .where(ExercisePlanRunModel.session_id == session_id)
            .order_by(ExercisePlanRunModel.insertion_order)
        )
        return tuple(_plan(item) for item in rows)

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
    ) -> ExerciseEvent:
        model = ExerciseEventModel(
            session_id=session_id,
            event_type=event_type,
            actor_callsign=actor_callsign,
            display_name=display_name,
            expected_session_version=expected_session_version,
            resulting_session_version=resulting_session_version,
            before_state=before_state,
            after_state=after_state,
            inputs=inputs,
            note=note,
        )
        self._session.add(model)
        await self._session.flush()
        return _event(model)

    async def get_event(self, session_id: UUID, event_id: UUID) -> ExerciseEvent | None:
        model = await self._session.scalar(
            select(ExerciseEventModel).where(
                ExerciseEventModel.id == event_id,
                ExerciseEventModel.session_id == session_id,
            )
        )
        return None if model is None else _event(model)

    async def get_creation_event(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        event_id: UUID,
    ) -> ExerciseEvent | None:
        model = await self._session.scalar(
            select(ExerciseEventModel)
            .join(
                ExerciseSessionModel,
                ExerciseEventModel.session_id == ExerciseSessionModel.id,
            )
            .where(
                ExerciseEventModel.id == event_id,
                ExerciseEventModel.event_type == "exercise.session-created",
                ExerciseSessionModel.exercise_id == exercise_id,
                ExerciseSessionModel.definition_version == definition_version,
                ExerciseSessionModel.definition_digest == definition_digest,
            )
        )
        return None if model is None else _event(model)

    async def list_events(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        rows = await self._session.scalars(
            select(ExerciseEventModel)
            .where(ExerciseEventModel.session_id == session_id)
            .order_by(ExerciseEventModel.resulting_session_version)
        )
        return tuple(_event(item) for item in rows)


def _session(model: ExerciseSessionModel) -> ExerciseSession:
    consequences = _json_object(model.consequences, "session consequences")
    return _session_from_state(
        {
            "id": str(model.id),
            "exerciseId": model.exercise_id,
            "definitionVersion": model.definition_version,
            "definitionDigest": model.definition_digest,
            "callsign": model.callsign,
            "displayName": model.display_name,
            "checkpointIndex": model.checkpoint_index,
            "objective": model.objective,
            "status": model.status,
            "version": model.version,
            "consequences": _mutable_json_object(consequences),
            "expiresAt": _utc_timestamp(model.expires_at, "session expiry").isoformat(),
        }
    )


def _plan(model: ExercisePlanRunModel) -> ExercisePlanRun:
    return ExercisePlanRun(
        id=model.id,
        session_id=model.session_id,
        checkpoint_key=model.checkpoint_key,
        input_hash=model.input_hash,
        input_data=_json_object(model.input_data, "plan input_data"),
        output_data=_json_object(model.output_data, "plan output_data"),
        versions=_json_object(model.versions, "plan versions"),
        created_at=_utc_timestamp(model.created_at, "plan timestamp"),
    )


def _event(model: ExerciseEventModel) -> ExerciseEvent:
    return ExerciseEvent(
        id=model.id,
        session_id=model.session_id,
        event_type=model.event_type,
        actor_callsign=model.actor_callsign,
        display_name=model.display_name,
        expected_session_version=model.expected_session_version,
        resulting_session_version=model.resulting_session_version,
        before_state=_json_object(model.before_state, "event before_state"),
        after_state=_json_object(model.after_state, "event after_state"),
        inputs=_json_object(model.inputs, "event inputs"),
        note=model.note,
        occurred_at=_utc_timestamp(model.occurred_at, "event timestamp"),
    )


def _json_object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"stored exercise {field} is invalid")
    try:
        return freeze_json_object(value)
    except (RecursionError, ValueError) as error:
        raise RuntimeError(f"stored exercise {field} is invalid") from error


def _mutable_json_object(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _mutable_json_value(item) for key, item in value.items()}


def _mutable_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _mutable_json_object(value)
    if isinstance(value, tuple):
        return [_mutable_json_value(item) for item in value]
    return value


def _utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RuntimeError(f"stored exercise {field} is invalid")
    if value.utcoffset() is None:
        raise RuntimeError(f"stored exercise {field} is invalid")
    return value.astimezone(UTC)
