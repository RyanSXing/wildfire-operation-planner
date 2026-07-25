# Task 9 report: bounded planning sandbox

## Delivered

- Added `POST /api/exercise-sessions/{session_id}/sandbox-plans` with no
  `Idempotency-Key` requirement.
- Added frozen transport-neutral `SandboxPlanControls`; all controls are bounded
  by the replay definition and the task solver validates locks.
- Reused checkpoint materialization, routing, solver, canonical input hashing,
  task explanation, candidate/coverage/lock facts, and guided-plan version
  evidence. Sandbox output carries definition digest, sources, objective, task
  algorithm, and not-applicable risk evidence.
- Added a dedicated provider context that does not call `session.begin()`.
  Sandbox requests never write plans, events, sessions, or idempotency rows.
- Reused the existing startup/runtime graph validator from Task 8; no duplicate
  `validate_exercise_graph` was introduced.

## Tests

The focused unit test was written first and initially failed because
`SandboxPlanControls` did not exist. The first API test then failed with the
expected `404` before the route was added.

Focused checks:

```text
52 passed in 7.68s
```

Full unit and architecture suite:

```text
733 passed, 3 known multiprocessing fork warnings in 8.02s
```

PostgreSQL/PostGIS HTTP integration at `localhost:55432`:

```text
27 passed in 7.85s
```

Static checks:

```text
ruff: All checks passed
mypy: Success: no issues found in 5 source files
```

API coverage proves unchanged plan/event/session-version/per-session
idempotency counts and audit for successful, invalid bounded-control, stale,
incomplete, concurrent, solver-lock, and forced-internal-failure requests.

## Commits

- Implementation: `8a1325150bbead4088767eedbe70d690a721caa9`
- Report: pending this commit

## Remaining risk

The solver is deterministic but still bounded to its existing two-second
budget; a future change to solver semantics needs to preserve the same
read-only response contract.

## Review follow-up

- Replaced the hardcoded checkpoint-key mapper in action eligibility with the
  actual key from the loaded definition. The committed Park Fire journey now
  asserts that plans for `initial-allocation` and `cascading-disruption` permit
  advance.
- Sandbox canonical input now records the wind preset and sorted resolved task
  priority preset/multiplier entries; equal wind values under different names
  therefore produce different hashes.
- Sandbox multipliers are strict positive signed-int64 values at load time.
  Replay validation also rejects priority products and worst-case task penalty
  aggregates outside CP-SAT signed-int64 range, with checkpoint/task paths.
- Sandbox responses are deep-frozen before returning. The route thaws only for
  Pydantic response validation.
- The sandbox provider requests SQLAlchemy `AUTOCOMMIT` isolation without an
  explicit transaction block. The committed-fixture integration test observes
  no explicit `BEGIN`/`COMMIT` SQL and verifies database-wide counts remain
  unchanged.

Follow-up verification:

```text
93 focused tests passed
738 unit + architecture tests passed (3 known multiprocessing fork warnings)
ruff: All checks passed
mypy: Success: no issues found in 5 source files
```

The final committed-fixture edge-case group expanded focused coverage to 94
passing tests, including `UNKNOWN`, definition mismatch, and strict version
coercion without database mutation.
