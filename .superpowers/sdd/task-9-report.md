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
