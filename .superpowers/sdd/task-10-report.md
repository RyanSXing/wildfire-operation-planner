# Task 10 Report: Constraint-based resource allocation

## Changed files

- `backend/src/wildfireops/decision/optimizer.py`
  - Added frozen allocation request/result types, boundary validation, deterministic
    CP-SAT modeling, stable result ordering, and constraint diagnostics.
- `backend/src/wildfireops/decision/explanations.py`
  - Added deterministic, JSON-compatible explanations with no LLM dependency.
- `backend/tests/unit/decision/test_optimizer.py`
  - Added deterministic examples, boundary validation, objective accounting,
    explanation, status-constructor, and ordering coverage.
- `backend/tests/unit/decision/test_optimizer_properties.py`
  - Added 30 bounded Hypothesis examples with at most eight resources and eight
    demands.
- `backend/pyproject.toml`
  - Added OR-Tools and the Hypothesis development dependency.
- `backend/uv.lock`
  - Locked the new direct and transitive dependencies.
- `.superpowers/sdd/task-10-report.md`
  - Recorded this implementation and its verification evidence.

## RED evidence

1. Before either production module existed:

   ```text
   uv run pytest tests/unit/decision/test_optimizer.py -v
   ModuleNotFoundError: No module named 'wildfireops.decision.optimizer'
   1 error during collection
   ```

   This was the expected missing-feature failure.

2. After the initial GREEN implementation, a new stable-explanation-order test
   was added and run before changing `explain_result`:

   ```text
   uv run pytest tests/unit/decision/test_optimizer.py::test_explanation_stably_sorts_every_collection -v
   AssertionError: assert ['zulu', 'alpha'] == ['alpha', 'zulu']
   1 failed
   ```

## GREEN evidence

- Initial deterministic example and validation suite: `18 passed`.
- Initial combined example/property run: `19 passed`.
- Stable-explanation-order test after its minimal fix: `1 passed`.
- Final focused Task 10 run:

  ```text
  uv run pytest tests/unit/decision/test_optimizer.py tests/unit/decision/test_optimizer_properties.py -q
  20 passed in 0.79s
  ```

## Verification commands and results

- `uv run pytest tests/unit -q`
  - `424 passed, 3 warnings in 5.35s`.
  - The warnings are existing macOS `fork()` deprecations in road-graph
    multiprocessing tests.
- `uv run mypy src`
  - `Success: no issues found in 57 source files`.
- `uv run ruff format --check .`
  - `93 files already formatted`.
- `uv run ruff check .`
  - `All checks passed!`.
- `git diff --check`
  - No whitespace errors.
- Full `uv run pytest -q` using the local default database configuration:
  - `429 passed, 84 errors`.
  - All errors occurred during integration setup because the expected local
    database role was absent; there were no assertion failures.
- Full suite rerun against the established test database (connection details
  intentionally omitted):
  - `429 passed, 84 errors`.
  - All errors occurred during integration setup because the database endpoint
    refused the connection; there were no assertion failures.

## Design choices

- Risk is validated as finite and within `0..100`, then integerized once as
  `round(1000 * weighted_risk / 100)` and reused for the model and result.
- Eligibility compares the exact route `travel_minutes` float with the response
  limit. The objective uses documented ceiling minutes so CP-SAT receives
  conservative integer travel coefficients.
- Inputs are validated and canonicalized before variable creation. Results and
  explanation collections are stably sorted.
- A resource can be assigned at most once. Destination assignments must supply
  required aggregate capacity, and assignments are prohibited when its covered
  variable is false.
- `num_search_workers=1` and `random_seed=0` make solver replay deterministic.
  Solver values are read only for `FEASIBLE` or `OPTIMAL`; any non-public solver
  status maps to `UNKNOWN` and produces no assignments.
- Explanations use fixed templates and JSON primitives. Constraint messages are
  derived only from request eligibility and selected capacity, with no
  persistence or API dependency.
- `OptimizationResult` retains the planned positional field order; only the two
  defaulted tail fields `unassigned_resource_ids` and `binding_constraints` were
  added.

## Risks

- The database-backed integration suite could not complete because neither the
  local nor established test database was reachable with a usable setup during
  verification. All DB-independent tests passed, but integration coverage remains
  an infrastructure-limited verification gap.
- OR-Tools adds its normal solver runtime and transitive dependency footprint.
