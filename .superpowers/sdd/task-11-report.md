# Task 11 implementation report

## Outcome

Task 11 turns immutable scenario versions into persisted optimizer
recommendations, atomic operator decisions, final assignments, and queryable audit
events. Command APIs use the constant actor `demo-operator`; the application
provider owns transaction scope while session-bound repositories only flush.

## Changed files

- `backend/migrations/versions/0004_auditable_operator_decisions.py`
- `backend/src/wildfireops/api/command_errors.py`
- `backend/src/wildfireops/api/dependencies.py`
- `backend/src/wildfireops/api/routes/audit.py`
- `backend/src/wildfireops/api/routes/decisions.py`
- `backend/src/wildfireops/api/routes/scenarios.py`
- `backend/src/wildfireops/api/schemas/decisions.py`
- `backend/src/wildfireops/api/schemas/scenarios.py`
- `backend/src/wildfireops/application/commands.py`
- `backend/src/wildfireops/decision/commands.py`
- `backend/src/wildfireops/decision/optimizer.py`
- `backend/src/wildfireops/decision/recommendations.py`
- `backend/src/wildfireops/decision/scenarios.py`
- `backend/src/wildfireops/geospatial/road_graph.py`
- `backend/src/wildfireops/main.py`
- `backend/src/wildfireops/persistence/decision_models.py`
- `backend/src/wildfireops/persistence/decisions.py`
- `backend/src/wildfireops/persistence/recommendations.py`
- `backend/tests/integration/api/test_decision_flow.py`
- `backend/tests/integration/decision/test_audit_transaction.py`
- `backend/tests/integration/decision/test_scenarios.py`
- `backend/tests/unit/decision/test_commands.py`
- `.superpowers/sdd/task-11-report.md`

## RED evidence

All database-backed runs used the required API-container database URL.

1. Complete decision-flow API test, before Task 11 production code:

   ```text
   docker compose run --rm -e WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@db:5432/wildfireops_test api uv run pytest tests/integration/api/test_decision_flow.py -v
   collected 1 item
   FAILED test_generate_approve_and_audit_complete_decision_flow
   assert 404 == 201
   route=unmatched
   ```

   Expected reason: recommendation, decision, and audit routers were absent.

2. Stale/reject/edit behavior set:

   ```text
   collected 7 items
   5 failed, 2 passed
   ```

   Expected product failures were:

   - stale approval returned `201` instead of `409 recommendation_stale`;
   - reject returned the approve-only slice's `422` instead of `201`;
   - valid edit returned the approve-only slice's `422` instead of `201`;
   - invalid edit returned the generic "decision action is not implemented"
     rather than a capacity validation failure.

   One fifth failure was a test-authoring placement error: a final-assignment
   count assertion from the complete-flow test was accidentally attached to the
   pinned-input test. It was moved back before GREEN. Recommendation and decision
   replay/conflict plus stale-generation behavior already passed in this run
   because the initial vertical slice reused the existing idempotency pattern.

3. Audit transaction injection:

   The first attempt did not collect because `tests` is not an importable package;
   the test was corrected to use a local minimal seed. The corrected RED was:

   ```text
   collected 1 item
   FAILED test_assignment_audit_failure_rolls_back_and_same_key_retries
   TypeError: DecisionRepository.__init__() got an unexpected keyword argument
   'after_assignment_insert'
   ```

   Expected reason: no post-assignment/pre-audit failure hook existed.

4. Invalid weather command boundary:

   ```text
   collected 1 item
   FAILED test_scenario_command_routes_create_version_and_require_idempotency
   assert 500 == 422
   ```

   Expected reason: `WeatherOverride` validation escaped through a generic
   scenario error instead of `ScenarioValidationError`.

5. Strict immutable resource snapshot parsing:

   ```text
   collected 1 item
   FAILED test_generation_rejects_malformed_snapshot_resource_json
   assert 201 == 422
   ```

   Expected reason: the first parser slice did not require snapshot resource
   `status`, `resource_type`, and `raw_metadata` fields.

## GREEN evidence

- Initial full vertical slice: `1 passed`.
- Stale/reject/edit/idempotency API set: `7 passed`.
- Rollback/retry transaction test: `1 passed`.
- Expanded API contract set: `11 passed`.
- Final focused API and transaction run: `13 passed in 3.74s`.
- Architecture boundaries: `3 passed`; API imports neither persistence nor
  SQLAlchemy, and decision imports neither API nor persistence.
- Final full backend suite: `531 passed, 3 warnings in 18.62s`.
- Ruff format check: `107 files already formatted`.
- Ruff check: `All checks passed!`.
- Mypy: `Success: no issues found in 68 source files`.

The three full-suite warnings are existing Python multiprocessing `fork()`
deprecation warnings from road-graph concurrency tests; there were no test
failures or Task 11 warnings.

## Migration evidence

All commands targeted `wildfireops_test` at `db:5432`.

1. Upgrade:

   ```text
   Running upgrade 0003_snapshot_resource_overrides ->
   0004_auditable_decisions
   ```

2. Downgrade:

   ```text
   Running downgrade 0004_auditable_decisions ->
   0003_snapshot_resource_overrides
   ```

3. Re-upgrade:

   ```text
   Running upgrade 0003_snapshot_resource_overrides ->
   0004_auditable_decisions
   ```

Each command exited successfully. Migration `0004` creates final decision
assignments, the active-resource partial unique index, and unique terminal
decision/audit constraints; downgrade removes them in dependency order.

## Design choices

- `CommandServiceProvider` is the only transaction owner. API code depends on
  transport-neutral services, and repositories remain session-bound flush-only
  adapters.
- Generation locks the incident-refresh advisory lock and then the parent
  scenario row before reading latest scenario/snapshot versions. It queries
  source observations only by the exact `(source_name, source_record_id)` pairs
  pinned in the snapshot and requires the snapshot asset pin set to match every
  exposure exactly; it never falls back to live latest source rows.
- One deterministic O(N) nearest-node scan is public in the road-graph module;
  callers never access `RoadGraph._graph`.
- All closure-aware candidate routes are stored in canonical request inputs so
  edits resolve route, time, closure hash, and capacity from the immutable
  recommendation rather than client data.
- Approve/edit lock the recommendation row, acquire the incident-refresh
  advisory lock, lock the parent scenario row while recomputing current inputs,
  and then lock selected live resources in stable order. The recomputed token
  uses the provider's current risk/allocation versions, and the service rejects
  unavailable or mismatched pinned graphs. Reject skips these staleness checks
  because it creates no active assignment.
- Proposal assignments stay immutable. Final assignments, terminal decision,
  audit event, and completed idempotency response share one transaction.
- Audit JSON records proposal/final pairs, actor/note, scenario and snapshot
  identities, staleness token, source versions, and graph/risk/allocation
  versions. API mapping recursively applies camel case to nested audit state.

## Concerns

No Task 11 correctness concern remains. Deployment still must populate the
application road-graph registry with the immutable graph versions it serves,
which is the existing Task 9 dependency-injection contract rather than new Task
11 scope.

## Review-gap follow-up evidence

The release-blocking review gaps were reproduced before the follow-up production
changes:

1. Malformed edit tuples and persisted-route validation:

   ```text
   pytest -q tests/unit/decision/test_commands.py
   FFFFFF
   6 failed in 0.49s
   ```

   The failures showed raw tuple-unpacking `ValueError`, accepted `NaN` and
   negative travel, the wrong infinity error, and an accepted graph mismatch.

2. Immutable pin reads and runtime staleness:

   ```text
   pytest -q tests/integration/api/test_decision_flow.py -k \
     'exact_canonical_asset_input_pins or reads_only_observations_pinned or \
      runtime_algorithm_version_drift or unavailable_pinned_graph'
   FFFFFFFF
   8 failed in 2.89s
   ```

   All four bad asset-pin censuses returned `201`; the observation SQL had no
   `WHERE`; risk/allocation drift and an unavailable graph also returned `201`.

3. Scenario-version serialization:

   ```text
   pytest -q tests/integration/decision/test_scenarios.py \
     -k recommendation_context_read_blocks_concurrent_add_version
   FF
   2 failed in 7.73s
   ```

   Both generation and current-approval context paths failed with
   `add-version never waited on the scenario row lock`.

After the minimal fixes, the combined focused command passed:

```text
pytest -q tests/unit/decision/test_commands.py \
  tests/integration/api/test_decision_flow.py \
  tests/integration/decision/test_audit_transaction.py \
  tests/integration/decision/test_scenarios.py
40 passed in 8.47s
```

Fresh final verification:

- Full backend: `547 passed, 3 warnings in 20.63s`.
- Ruff format: `3 files reformatted, 100 files left unchanged`.
- Ruff check: `All checks passed!`.
- Mypy source gate: `Success: no issues found in 68 source files`.
- `git diff --check`: clean.

The three warnings remain the existing Python multiprocessing `fork()`
deprecation warnings from road-graph concurrency tests.
