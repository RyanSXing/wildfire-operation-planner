# Task 6 report: deterministic checkpoint planning and override

## Changed files

- `backend/src/wildfireops/application/exercise_planning.py`
- `backend/tests/unit/application/test_exercise_planning.py`

## Implementation

- Materializes canonical checkpoint resources, tasks, road closures, source evidence,
  objective penalties, candidate routes, and SHA-256 planning inputs.
- Stores generated and overridden plans with exercise, digest, graph, and algorithm
  versions; events snapshot the exact persisted response projection for replay.
- Replays only a session-scoped plan that matches the active definition/digest.
- Validates the checkpoint-three evacuation-bus override through the joint solver;
  invalid, unreachable, incompatible, or `UNKNOWN` paths do not create plan/event rows.

## TDD evidence

RED:

```text
uv run pytest tests/unit/application/test_exercise_planning.py::test_checkpoint_materialization_combines_both_incidents -q
FAILED: ModuleNotFoundError: No module named 'wildfireops.application.exercise_planning'
```

GREEN:

```text
uv run pytest tests/unit/application/test_exercise_planning.py -q
9 passed
```

## Verification

```text
uv run pytest tests/unit/application/test_exercise_planning.py \
  tests/unit/application/test_exercises.py \
  tests/unit/decision/test_task_optimizer.py \
  tests/unit/decision/test_task_explanations.py -q
121 passed

uv run pytest tests/unit -q
700 passed, 3 pre-existing multiprocessing fork deprecation warnings

uv run ruff check src/wildfireops/application/exercise_planning.py \
  src/wildfireops/application/exercises.py \
  tests/unit/application/test_exercise_planning.py
All checks passed

uv run mypy src/wildfireops/application/exercise_planning.py
Success: no issues found in 1 source file

uv run pytest tests/architecture -q
3 passed
```

## Local default database note

The configured local PostgreSQL server lacks PostGIS. `uv run alembic upgrade
head` fails on migration `0001` with `extension "postgis" is not available`,
so `tests/integration/persistence/test_exercises.py` cannot create its schema.

## PostGIS verification follow-up

The designated test database was available at `localhost:55432` in container
`wildfireops-exercise-test-db`. With
`WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test`:

```text
uv run alembic upgrade head
uv run pytest tests/integration/persistence/test_exercises.py -q
16 passed in 3.02s
```

The non-PostGIS local default database limitation above is not a Task 6 defect.

## Review hardening follow-up

- Final checkpoint retries now preserve the latest actionable plan while failed
  attempts remain in audit history; `UNKNOWN` and infeasible attempts require
  regeneration and cannot enter override.
- Planning rechecks canonical stored inputs before override, solves from fresh
  materialization, freezes materialized evidence, and persists deterministic
  coverage/candidate evidence.

```text
uv run pytest tests/unit -q
701 passed, 3 existing fork warnings
uv run pytest tests/architecture -q
3 passed
designated PostGIS persistence: 16 passed
ruff + mypy: passed
```
