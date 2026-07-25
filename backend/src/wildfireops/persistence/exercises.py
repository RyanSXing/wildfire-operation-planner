from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)


class ExerciseRepository:
    """Session-bound adapter; the caller owns commit and rollback.

    Plan and event history is append-only through this adapter. Administrative
    deletion of a session cascades to its history at the database level.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        callsign: str,
        expires_at: datetime,
    ) -> ExerciseSessionModel:
        model = ExerciseSessionModel(
            exercise_id=exercise_id,
            definition_version=definition_version,
            definition_digest=definition_digest,
            callsign=callsign,
            expires_at=expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def lock_session(self, session_id: UUID) -> ExerciseSessionModel | None:
        return await self._session.scalar(
            select(ExerciseSessionModel)
            .where(ExerciseSessionModel.id == session_id)
            .with_for_update()
        )

    async def get_session(self, session_id: UUID) -> ExerciseSessionModel | None:
        return await self._session.get(ExerciseSessionModel, session_id)

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
    ) -> ExercisePlanRunModel:
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
        return model

    async def latest_plan(
        self,
        session_id: UUID,
        checkpoint_key: str,
    ) -> ExercisePlanRunModel | None:
        return await self._session.scalar(
            select(ExercisePlanRunModel)
            .where(
                ExercisePlanRunModel.session_id == session_id,
                ExercisePlanRunModel.checkpoint_key == checkpoint_key,
            )
            .order_by(
                ExercisePlanRunModel.insertion_order.desc(),
            )
            .limit(1)
        )

    async def list_plans(
        self,
        session_id: UUID,
    ) -> tuple[ExercisePlanRunModel, ...]:
        rows = await self._session.scalars(
            select(ExercisePlanRunModel)
            .where(ExercisePlanRunModel.session_id == session_id)
            .order_by(ExercisePlanRunModel.insertion_order)
        )
        return tuple(rows)

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
    ) -> ExerciseEventModel:
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
        return model

    async def list_events(
        self,
        session_id: UUID,
    ) -> tuple[ExerciseEventModel, ...]:
        rows = await self._session.scalars(
            select(ExerciseEventModel)
            .where(ExerciseEventModel.session_id == session_id)
            .order_by(ExerciseEventModel.resulting_session_version)
        )
        return tuple(rows)
