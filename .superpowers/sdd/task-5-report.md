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

## Review follow-up

RED: added focused tests for definition-bound sessions, preserved command replay
projections, scoped forged event claims, blank idempotency keys, non-object JSON
columns, and nested mutation isolation. The pre-change unit run failed on the
new scoped event lookup, missing definition guard, and blank-key validation.

GREEN:

- Sessions are bound to exercise ID, definition version, and configured digest
  at command, projection, replay, and query boundaries.
- Create claims replay by guarded session ID; command event and plan lookups are
  scoped by session ID. Replay stores a private event JSON response snapshot and
  public audit/debrief views omit it.
- Repository mappings validate/freeze JSON recursively, isolate mutable session
  consequences, normalize aware timestamps to UTC, and delegate only
  idempotency operations to `ScenarioRepository`.

Follow-up commands:

```bash
cd backend
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run pytest tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py
uv run pytest tests/unit tests/architecture -q
```

Results: focused suite `34 passed`; backend unit/architecture `682 passed`
(the same three multiprocessing fork warnings).

## Final replay follow-up

RED: froze fake persisted event/plan JSON to match PostgreSQL and added failing
creation replay, frozen-corridor, forged-snapshot, public-audit immutability,
and real-Postgres command regressions.

GREEN:

- Frozen stored consequences now decode into an isolated mutable session dict.
- Creation claims point to a definition-bound creation event and replay its
  immutable full projection; replay snapshots are structurally matched to the
  event state.
- `session_projection` enforces the common definition/digest guard, corridor
  assignment handling accepts frozen JSON sequences, and audit inputs remain
  deep frozen after private snapshot removal.

Final commands:

```bash
cd backend
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run pytest tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py
uv run pytest tests/unit tests/architecture -q
```

Results: focused suite `38 passed`; backend unit/architecture `684 passed`
(the same three multiprocessing fork warnings).

## Replay projection boundary

RED: added replay tests that forge missing and unexpected projection keys plus
malformed actions, checkpoint, and latest-plan values; all five initially
replayed successfully.

GREEN: replay snapshots now require exactly the session state keys plus
`allowedActions`, `currentCheckpoint`, and `latestPlan`. Actions must be the
frozen nonblank-string sequence, checkpoint must equal the frozen definition
checkpoint, and latest plan must be null or a frozen object.

```bash
cd backend
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run pytest tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py
```

Result: focused suite `43 passed`; Ruff and mypy passed.

## Replay action options

RED: added empty, unknown, padded, duplicate, and impossible replay action
tuples. Each passed the prior generic nonblank-string validation.

GREEN: one state-options helper now accepts only the exact tuples emitted by
`_allowed_actions`, narrowed for expired, completed, no-objective, active
pre-final, and final-checkpoint session states.

```bash
cd backend
WILDFIREOPS_DATABASE_URL='postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test' uv run pytest tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py tests/unit/application/test_exercises.py tests/integration/persistence/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py src/wildfireops/persistence/exercises.py
```

Result: focused suite `48 passed`; Ruff and mypy passed.
