from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.application.exercises import (
    ExerciseEvent,
    ExercisePlanRun,
    ExerciseSession,
    _session_from_state,
)
from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)
from wildfireops.persistence.scenarios import ScenarioRepository


class ExerciseRepository(ScenarioRepository):
    """Session-bound adapter; the caller owns commit and rollback."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

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

    async def get_plan(self, plan_id: UUID) -> ExercisePlanRun | None:
        model = await self._session.get(ExercisePlanRunModel, plan_id)
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

    async def get_event(self, event_id: UUID) -> ExerciseEvent | None:
        model = await self._session.get(ExerciseEventModel, event_id)
        return None if model is None else _event(model)

    async def list_events(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        rows = await self._session.scalars(
            select(ExerciseEventModel)
            .where(ExerciseEventModel.session_id == session_id)
            .order_by(ExerciseEventModel.resulting_session_version)
        )
        return tuple(_event(item) for item in rows)


def _session(model: ExerciseSessionModel) -> ExerciseSession:
    if not isinstance(model.consequences, dict):
        raise RuntimeError("stored exercise state is invalid")
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
            "consequences": dict(model.consequences),
            "expiresAt": model.expires_at.isoformat(),
        }
    )


def _plan(model: ExercisePlanRunModel) -> ExercisePlanRun:
    return ExercisePlanRun(
        id=model.id,
        session_id=model.session_id,
        checkpoint_key=model.checkpoint_key,
        input_hash=model.input_hash,
        input_data=dict(model.input_data),
        output_data=dict(model.output_data),
        versions=dict(model.versions),
        created_at=model.created_at,
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
        before_state=dict(model.before_state),
        after_state=dict(model.after_state),
        inputs=dict(model.inputs),
        note=model.note,
        occurred_at=model.occurred_at,
    )
