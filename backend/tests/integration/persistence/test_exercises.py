import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.persistence.decision_models import IdempotencyKeyModel
from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)
from wildfireops.persistence.exercises import ExerciseRepository


def session_values(
    *,
    callsign: str = "EMBER-101",
    expires_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "exercise_id": "park-fire-decision",
        "definition_version": "1",
        "definition_digest": "a" * 64,
        "callsign": callsign,
        "expires_at": expires_at or datetime.now(UTC) + timedelta(hours=24),
    }


async def create_session(
    repository: ExerciseRepository,
    *,
    callsign: str = "EMBER-101",
) -> ExerciseSessionModel:
    return await repository.create_session(**session_values(callsign=callsign))


async def append_event(
    repository: ExerciseRepository,
    session_id: UUID,
    *,
    resulting_session_version: int,
) -> None:
    await repository.append_event(
        session_id=session_id,
        event_type="session.started",
        actor_callsign="EMBER-101",
        display_name=None,
        expected_session_version=resulting_session_version - 1,
        resulting_session_version=resulting_session_version,
        before_state={"version": resulting_session_version - 1},
        after_state={"version": resulting_session_version},
        inputs={"source": "test"},
        note=None,
    )


@pytest.mark.asyncio
async def test_plan_runs_are_isolated_by_session(db_session: AsyncSession) -> None:
    repository = ExerciseRepository(db_session)
    first = await create_session(repository)
    second = await create_session(repository, callsign="EMBER-102")

    await repository.store_plan(
        session_id=first.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"session": "first"},
        output_data={"status": "OPTIMAL"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=None,
    )

    assert await repository.list_plans(first.id)
    assert await repository.list_plans(second.id) == ()


@pytest.mark.asyncio
async def test_session_defaults_json_and_timestamps_round_trip(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    expires_at = datetime(2030, 7, 25, 12, tzinfo=UTC)
    session = await repository.create_session(
        **session_values(expires_at=expires_at),
    )
    await db_session.refresh(session)

    assert session.checkpoint_index == 0
    assert session.status == "active"
    assert session.version == 1
    assert session.consequences == {}
    assert session.created_at.tzinfo is not None
    assert session.updated_at.tzinfo is not None
    assert session.expires_at == expires_at

    server_default = (
        await db_session.execute(
            insert(ExerciseSessionModel)
            .values(
                **session_values(callsign="EMBER-102"),
                checkpoint_index=0,
                version=1,
                status=text("DEFAULT"),
                consequences=text("DEFAULT"),
            )
            .returning(ExerciseSessionModel.status, ExerciseSessionModel.consequences)
        )
    ).one()

    assert tuple(server_default) == ("active", {})


@pytest.mark.asyncio
async def test_session_status_check_constraint(db_session: AsyncSession) -> None:
    db_session.add(ExerciseSessionModel(**session_values(), status="invalid"))

    with pytest.raises(IntegrityError, match="ck_exercise_sessions_status"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_event_session_version_is_unique(db_session: AsyncSession) -> None:
    repository = ExerciseRepository(db_session)
    session = await create_session(repository)
    await append_event(repository, session.id, resulting_session_version=2)

    with pytest.raises(IntegrityError, match="uq_exercise_event_session_version"):
        await append_event(repository, session.id, resulting_session_version=2)


@pytest.mark.asyncio
async def test_plan_run_is_not_updated_by_repository(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    session = await create_session(repository)
    first = await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"input": {"value": 1}},
        output_data={"status": "OPTIMAL"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=None,
    )
    second = await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="c" * 64,
        input_data={"input": {"value": 2}},
        output_data={"status": "FEASIBLE"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=None,
    )

    stored_first = await db_session.get(ExercisePlanRunModel, first.id)

    assert first.id != second.id
    assert stored_first is not None
    assert stored_first.input_data == {"input": {"value": 1}}


@pytest.mark.asyncio
async def test_repository_leaves_transaction_ownership_to_caller(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit_spy = AsyncMock(side_effect=AssertionError("repository must not commit"))
    rollback_spy = AsyncMock(
        side_effect=AssertionError("repository must not roll back")
    )
    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)

    await create_session(ExerciseRepository(db_session))

    assert db_session.in_transaction()
    commit_spy.assert_not_awaited()
    rollback_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_session_serializes_concurrent_commands() -> None:
    engine = create_engine(Settings())
    created_id: UUID | None = None
    try:
        async with engine.begin() as connection:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                created_id = (await create_session(ExerciseRepository(session))).id
        assert created_id is not None

        first_has_lock = asyncio.Event()
        release_first = asyncio.Event()
        second_attempted_lock = asyncio.Event()

        async def increment_first() -> int:
            async with engine.begin() as connection:
                async with AsyncSession(
                    bind=connection, expire_on_commit=False
                ) as session:
                    locked = await ExerciseRepository(session).lock_session(created_id)
                    assert locked is not None
                    assert locked.version == 1
                    first_has_lock.set()
                    await release_first.wait()
                    locked.version += 1
                    await session.flush()
                    return locked.version

        async def increment_second() -> int:
            await first_has_lock.wait()
            async with engine.begin() as connection:
                async with AsyncSession(
                    bind=connection, expire_on_commit=False
                ) as session:
                    second_attempted_lock.set()
                    locked = await ExerciseRepository(session).lock_session(created_id)
                    assert locked is not None
                    observed_version = locked.version
                    locked.version += 1
                    await session.flush()
                    return observed_version

        first_task = asyncio.create_task(increment_first())
        await first_has_lock.wait()
        second_task = asyncio.create_task(increment_second())
        await second_attempted_lock.wait()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second_task), timeout=0.1)
        release_first.set()

        assert await first_task == 2
        assert await second_task == 2
    finally:
        if created_id is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    delete(ExerciseSessionModel).where(
                        ExerciseSessionModel.id == created_id
                    )
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_deleting_session_cascades_plans_and_events(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    session = await create_session(repository)
    await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"session": "first"},
        output_data={"status": "OPTIMAL"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=None,
    )
    await append_event(repository, session.id, resulting_session_version=2)

    await db_session.delete(session)
    await db_session.flush()

    assert (
        await db_session.scalar(select(func.count()).select_from(ExercisePlanRunModel))
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(ExerciseEventModel))
        == 0
    )


@pytest.mark.asyncio
async def test_idempotency_key_cannot_back_two_plan_runs(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    session = await create_session(repository)
    idempotency_key = IdempotencyKeyModel(
        scope="exercise-session",
        key="test-idempotency-key",
        request_hash="d" * 64,
    )
    db_session.add(idempotency_key)
    await db_session.flush()
    await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"session": "first"},
        output_data={"status": "OPTIMAL"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=idempotency_key.id,
    )

    with pytest.raises(IntegrityError, match="uq_exercise_plan_idempotency"):
        await repository.store_plan(
            session_id=session.id,
            checkpoint_key="initial",
            input_hash="c" * 64,
            input_data={"session": "first"},
            output_data={"status": "OPTIMAL"},
            versions={"algorithm": "task-allocation-v1"},
            idempotency_key_id=idempotency_key.id,
        )


@pytest.mark.asyncio
async def test_migration_creates_session_indexes(db_session: AsyncSession) -> None:
    index_names = set(
        await db_session.scalars(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename IN ('exercise_sessions', 'exercise_plan_runs', "
                "'exercise_events')"
            )
        )
    )

    assert {
        "ix_exercise_sessions_expiry",
        "ix_exercise_plan_runs_session_checkpoint",
        "ix_exercise_events_session_time",
    } <= index_names
