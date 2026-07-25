# Task 5 report

## RED

Added `backend/tests/unit/application/test_exercises.py` before the service.
The initial focused run failed as expected with:

```text
ModuleNotFoundError: No module named 'wildfireops.application.exercises'
```

## GREEN

- Added transport-neutral session, plan, and event projections; command/query
  services; idempotency/transition/expiry/version checks; audit events; and
  strict stored-state decoding.
- Converted `ExerciseRepository` public methods to application projections,
  reused `ScenarioRepository` idempotency operations, and retained caller-owned
  transactions.
- Applied the existing `0005_exercise_sessions` migration to the requested
  local PostGIS test database before persistence verification.

Commands run:

```bash
cd backend
uv run pytest tests/unit/application/test_exercises.py -q
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run alembic upgrade head
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run pytest tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py tests/unit/application/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py
uv run pytest tests/unit tests/architecture -q
```

Results: focused suite `27 passed`; backend unit/architecture `677 passed`
(three pre-existing multiprocessing fork warnings).

## Self-review / concerns

- Expiry is projection-only on reads and mutation commands do not save or append
  an event after detecting expiry.
- Idempotency claims are created inside the caller's transaction; callers must
  roll back a rejected command so an incomplete claim is not retained.
- The test database schema was advanced locally; no migration files changed.
