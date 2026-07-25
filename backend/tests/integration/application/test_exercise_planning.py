from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.application.test_exercise_planning import definition, graph
from wildfireops.application.exercise_planning import ExercisePlanningService
from wildfireops.application.exercises import ExerciseSessionService
from wildfireops.persistence.exercises import ExerciseRepository


NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_checkpoint_three_override_persists_json_evidence(db_session: AsyncSession) -> None:
    exercise = definition()
    repository = ExerciseRepository(db_session)
    sessions = ExerciseSessionService(
        definition=exercise,
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: NOW,
        callsign=lambda: "EMBER-101",
    )
    planning = ExercisePlanningService(
        definition=exercise,
        definition_digest="a" * 64,
        graph=graph(),
        repository=repository,
        session_service=sessions,
        clock=lambda: NOW,
    )
    created = await sessions.create(idempotency_key="create")
    selected = await sessions.select_objective(
        created.id, "fastest-response", expected_version=1, idempotency_key="objective"
    )
    selected.checkpoint_index = 2
    selected.consequences = {"corridorCleared": True}
    await repository.save_session(selected)
    plan, _ = await planning.generate_plan(
        selected.id, expected_version=2, idempotency_key="plan"
    )
    override, _ = await planning.apply_override(
        selected.id,
        resource_id="bus-1",
        task_id="shelter-capacity-transport",
        expected_version=3,
        idempotency_key="override",
    )

    stored = await repository.get_plan(selected.id, override.id)
    assert stored is not None
    assert stored.output_data["operatorOverride"]["beforePlanId"] == str(plan.id)
    assert stored.output_data["explanation"]["changes"]
