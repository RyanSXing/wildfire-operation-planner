import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.application.exercises import ExerciseSession, ExerciseSessionService
from wildfireops.config import Settings
from wildfireops.db import create_engine
from wildfireops.persistence.decision_models import IdempotencyKeyModel
from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)
from wildfireops.persistence.exercises import ExerciseRepository
from tests.unit.application.test_exercises import definition


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
) -> ExerciseSession:
    return await repository.create_session(**session_values(callsign=callsign))


def command_service(
    repository: ExerciseRepository, *, now: datetime
) -> ExerciseSessionService:
    return ExerciseSessionService(
        definition=definition(),
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: now,
        callsign=lambda: "EMBER-101",
    )


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
async def test_postgres_create_replay_uses_original_projection(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    repository = ExerciseRepository(db_session)
    commands = command_service(repository, now=now)
    created = await commands.create(idempotency_key="create")
    original = await commands.project(created)
    await commands.select_objective(
        created.id,
        "fastest-response",
        expected_version=1,
        idempotency_key="objective",
    )

    replay = await command_service(repository, now=now + timedelta(hours=25)).create(
        idempotency_key="create"
    )

    assert await commands.project(replay) == original


@pytest.mark.asyncio
async def test_postgres_corridor_assignment_survives_frozen_json(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    repository = ExerciseRepository(db_session)
    commands = command_service(repository, now=now)
    session = await commands.create(idempotency_key="create")
    session.objective = "fastest-response"
    session.checkpoint_index = 1
    session.version = 2
    await repository.save_session(session)
    await repository.store_plan(
        session_id=session.id,
        checkpoint_key="cascade",
        input_hash="b" * 64,
        input_data={"objective": "fastest-response"},
        output_data={
            "status": "OPTIMAL",
            "assignments": [{"taskId": "clear-primary-corridor"}],
        },
        versions={},
        idempotency_key_id=None,
    )

    advanced = await commands.advance(
        session.id, expected_version=2, idempotency_key="advance"
    )

    assert advanced.consequences == {"corridorCleared": True}


@pytest.mark.asyncio
async def test_session_defaults_json_and_timestamps_round_trip(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    expires_at = datetime(2030, 7, 25, 12, tzinfo=UTC)
    session = await repository.create_session(
        **session_values(expires_at=expires_at),
    )
    model = await db_session.get(ExerciseSessionModel, session.id)
    assert model is not None

    assert session.checkpoint_index == 0
    assert session.status == "active"
    assert session.version == 1
    assert session.consequences == {}
    assert model.created_at.tzinfo is not None
    assert model.updated_at.tzinfo is not None
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
async def test_repository_rejects_non_object_json_columns(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    session = await create_session(repository)
    plan = await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={},
        output_data={},
        versions={},
        idempotency_key_id=None,
    )
    await db_session.execute(
        ExercisePlanRunModel.__table__.update()
        .where(ExercisePlanRunModel.id == plan.id)
        .values(input_data=[["not", "an object"]])
    )
    await db_session.flush()

    with pytest.raises(
        RuntimeError, match="stored exercise plan input_data is invalid"
    ):
        await repository.get_plan(session.id, plan.id)


@pytest.mark.asyncio
async def test_repository_deep_freezes_plan_json_and_isolates_consequences(
    db_session: AsyncSession,
) -> None:
    repository = ExerciseRepository(db_session)
    session_model = ExerciseSessionModel(
        **session_values(), consequences={"nested": {"items": ["original"]}}
    )
    db_session.add(session_model)
    await db_session.flush()
    session = await repository.get_session(session_model.id)
    assert session is not None
    session.consequences["nested"]["items"].append("changed")  # type: ignore[index,union-attr]
    plan = await repository.store_plan(
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"nested": {"items": ["original"]}},
        output_data={},
        versions={},
        idempotency_key_id=None,
    )

    with pytest.raises(TypeError):
        plan.input_data["nested"]["items"] = "changed"  # type: ignore[index]
    await db_session.refresh(session_model)
    assert session_model.consequences == {"nested": {"items": ["original"]}}


@pytest.mark.asyncio
async def test_plan_runs_keep_insertion_order_within_one_transaction(
    db_session: AsyncSession,
) -> None:
    session = await create_session(ExerciseRepository(db_session))
    first = ExercisePlanRunModel(
        id=UUID(int=3),
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"position": "first"},
        output_data={},
        versions={},
    )
    second = ExercisePlanRunModel(
        id=UUID(int=1),
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="c" * 64,
        input_data={"position": "second"},
        output_data={},
        versions={},
    )
    third = ExercisePlanRunModel(
        id=UUID(int=2),
        session_id=session.id,
        checkpoint_key="initial",
        input_hash="d" * 64,
        input_data={"position": "third"},
        output_data={},
        versions={},
    )
    db_session.add_all([first, second, third])
    await db_session.flush()

    repository = ExerciseRepository(db_session)

    assert tuple(item.id for item in await repository.list_plans(session.id)) == (
        first.id,
        second.id,
        third.id,
    )
    assert (await repository.latest_plan(session.id, "initial")).id == third.id


@pytest.mark.asyncio
async def test_events_are_ordered_by_resulting_session_version(
    db_session: AsyncSession,
) -> None:
    session = await create_session(ExerciseRepository(db_session))
    events = [
        ExerciseEventModel(
            id=UUID(int=1),
            session_id=session.id,
            event_type="session.changed",
            actor_callsign="EMBER-101",
            expected_session_version=2,
            resulting_session_version=3,
            before_state={},
            after_state={},
            inputs={},
        ),
        ExerciseEventModel(
            id=UUID(int=3),
            session_id=session.id,
            event_type="session.changed",
            actor_callsign="EMBER-101",
            expected_session_version=0,
            resulting_session_version=1,
            before_state={},
            after_state={},
            inputs={},
        ),
        ExerciseEventModel(
            id=UUID(int=2),
            session_id=session.id,
            event_type="session.changed",
            actor_callsign="EMBER-101",
            expected_session_version=1,
            resulting_session_version=2,
            before_state={},
            after_state={},
            inputs={},
        ),
    ]
    db_session.add_all(events)
    await db_session.flush()

    listed = await ExerciseRepository(db_session).list_events(session.id)

    assert tuple(item.resulting_session_version for item in listed) == (1, 2, 3)


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
    first_task: asyncio.Task[int] | None = None
    second_task: asyncio.Task[int] | None = None
    release_first = asyncio.Event()
    try:
        async with engine.begin() as connection:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                created_id = (await create_session(ExerciseRepository(session))).id
        assert created_id is not None

        first_has_lock = asyncio.Event()
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
                    await ExerciseRepository(session).save_session(locked)
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
                    await ExerciseRepository(session).save_session(locked)
                    return observed_version

        first_task = asyncio.create_task(increment_first())
        await asyncio.wait_for(first_has_lock.wait(), timeout=1)
        second_task = asyncio.create_task(increment_second())
        await asyncio.wait_for(second_attempted_lock.wait(), timeout=1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second_task), timeout=0.1)
        release_first.set()

        assert await asyncio.wait_for(
            asyncio.gather(first_task, second_task), timeout=1
        ) == [2, 2]
    finally:
        release_first.set()
        tasks = tuple(task for task in (first_task, second_task) if task is not None)
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        if tasks:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=1
            )
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

    await db_session.execute(
        delete(ExerciseSessionModel).where(ExerciseSessionModel.id == session.id)
    )
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
