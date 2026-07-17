# Deterministic Replay Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one credential-free command that loads a complete validated replay package into an empty PostGIS database and atomically creates the assets, simulated resources, observations, incidents, exposure snapshots, risk scores, and source freshness required by the WildfireOps UI.

**Architecture:** Add one focused `wildfireops.replay.seed` module. It derives canonical package/configuration identity, reuses the existing transaction-bound idempotency claim and incident advisory lock, and calls the existing observation, clustering, incident, exposure, and risk implementations inside one transaction. An identical committed seed is a no-op; changed contents or derivation settings conflict; a new seed refuses operational rows. The same module owns a thin CLI. No schema, API, worker, frontend, graph-loader, notification, or generic seeding framework is added.

**Tech Stack:** Python 3.12, asyncio, dataclasses, standard-library canonical JSON/SHA-256, SQLAlchemy async sessions, PostgreSQL/PostGIS, GeoAlchemy2, Shapely, existing replay and derivation services, pytest, Ruff, mypy.

## Global Constraints

- Construct `ReplayLoader` before opening the database transaction and require `loader.static_data` to be present. Legacy observation-only packages remain readable but are not seedable.
- Never acquire data, access the network, require live-source credentials, mutate the replay package, start the API/worker, or emit notifications.
- Preserve `ReplayManifest` schema version `1`; add no migration, table, column, endpoint, frontend code, dependency, framework, or parallel derivation implementation.
- Compute `package_digest` from canonical compact JSON of `ReplayManifest.to_payload()`. An attached road graph therefore participates through its manifest metadata and file hash.
- Compute `seed_request_hash` from the package digest plus every field of `ClusteringConfig`, `ExposureConfig`, and `RiskConfig`.
- Claim exactly `(scope="replay_seed", key=manifest.package_id, request_hash=seed_request_hash)` through `ScenarioRepository.claim_idempotency()`; do not call `complete_idempotency()`.
- Acquire `acquire_incident_refresh_lock()` before the idempotency claim or any database state inspection.
- An existing identical claim returns `already_seeded` before the emptiness check. An existing different request raises `ReplaySeedConflict`.
- A new claim requires `source_observations`, `quarantined_observations`, `exposed_assets`, `resource_units`, `wildfire_incidents`, and `source_status` to be empty. It never merges, deletes, replaces, repairs, or updates unrelated operational state.
- Insert assets/resources in stable ID order, materialize frozen metadata, preserve `raw_metadata.demand` and `raw_metadata.simulated`, and write geometry as SRID 4326.
- Seed every observation returned by `loader.iter_until(loader.manifest.end_at)` through `ObservationRepository.upsert_many()` and reject any nonzero deduplication count for a new seed.
- Derive state only with `load_current_fire_detections()`, `cluster_detections()`, `refresh_incidents()`, and `refresh_exposure_and_risk()`. Reject a package/configuration that produces zero clusters.
- Write one successful `SourceStatusModel` per actual observation source, not `replay:<package_id>`.
- Keep the idempotency claim, static rows, observations, derived state, and source statuses in one transaction. Any error must roll all of them back and must not leave a failure-status row.
- The CLI accepts exactly one package directory, prints one compact JSON result on success, returns nonzero on failure, sanitizes unexpected errors to their class name, and always disposes its engine.
- Test data remains explicitly synthetic; do not create or claim to have acquired `data/replay/park-fire` in this slice.

## Execution Routing

- Implementation tasks: `worker` role on `gpt-5.6-terra`, high reasoning, Fast.
- Architecture/correctness reviews: `reviewer` role on `gpt-5.6-sol`, xhigh reasoning, Fast.
- Prescribed test verification: `verifier` role on `gpt-5.6-luna`, low reasoning, Fast.
- Repository exploration, only if implementation discovers an unmapped contract: `explorer` role on `gpt-5.6-luna`, medium reasoning, Fast.

## File Structure

- Create `backend/src/wildfireops/replay/seed.py`: result/error contract, canonical identity, atomic seed service, and CLI.
- Create `backend/tests/unit/replay/test_seed.py`: pure digest coverage and CLI success/error serialization.
- Create `backend/tests/integration/replay/test_seed.py`: complete-package PostGIS success, idempotency, ownership, rollback, and concurrency proof.
- Modify `docs/superpowers/plans/2026-07-16-wildfireops-implementation.md`: place migration and the seed command in Task 14's repeatable offline workflow.

---

### Task 1: Define deterministic seed identity and result serialization

**Files:**

- Create: `backend/src/wildfireops/replay/seed.py`
- Create: `backend/tests/unit/replay/test_seed.py`

**Interfaces:**

- Consumes: `ReplayManifest.to_payload()`, `ClusteringConfig`, `ExposureConfig`, and `RiskConfig`.
- Produces: `ReplaySeedError`, `ReplaySeedConflict`, `ReplaySeedResult`, `_package_digest()`, `_seed_request_hash()`, and `_result_json()`.

- [ ] **Step 1: Write failing canonical identity tests**

In `test_seed.py`, construct semantic manifests directly and prove:

1. reversing `manifest.files` insertion order does not change `_package_digest()`;
2. changing a referenced file hash, replay end time, manifest algorithm label, or attached road-graph metadata changes `_package_digest()`;
3. `_seed_request_hash()` is stable for equal config objects;
4. changing clustering radius or exposure buffer changes `_seed_request_hash()`;
5. the canonical request payload contains every `RiskConfig` dataclass field. Current `RiskConfig` permits only registered `risk-v1` parameters, so test complete field inclusion rather than constructing an invalid risk configuration; any future registered risk configuration will consequently change the hash.

Use `dataclasses.fields(RiskConfig)` to compare the exact key set. Do not snapshot a hand-maintained subset.

- [ ] **Step 2: Write failing result serialization tests**

Construct:

```python
ReplaySeedResult(
    package_id="synthetic-replay-v1",
    package_digest="a" * 64,
    status="seeded",
    assets_inserted=1,
    resources_inserted=1,
    observations_inserted=3,
    incidents_created=1,
    snapshots_created=1,
)
```

Assert `_result_json()` returns one compact, sorted JSON object with those exact snake_case fields and no newline. Also construct `status="already_seeded"` with every count zero.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_seed.py -q
```

Expected: collection fails because `wildfireops.replay.seed` does not exist.

- [ ] **Step 4: Implement the immutable public contract and canonical helpers**

Define exactly:

```python
class ReplaySeedError(ValueError):
    """Raised when a replay package cannot produce valid seeded state."""


class ReplaySeedConflict(ReplaySeedError):
    """Raised when replay state is already owned by another seed request."""


@dataclass(frozen=True, slots=True)
class ReplaySeedResult:
    package_id: str
    package_digest: str
    status: Literal["seeded", "already_seeded"]
    assets_inserted: int
    resources_inserted: int
    observations_inserted: int
    incidents_created: int
    snapshots_created: int
```

Use one `_canonical_json(value) -> bytes` helper with `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")`.

Implement identity as:

```python
def _package_digest(manifest: ReplayManifest) -> str:
    return sha256(_canonical_json(manifest.to_payload())).hexdigest()


def _seed_request_payload(
    package_digest: str,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> dict[str, object]:
    return {
        "package_digest": package_digest,
        "clustering_config": asdict(clustering_config),
        "exposure_config": asdict(exposure_config),
        "risk_config": asdict(risk_config),
    }


def _seed_request_hash(
    package_digest: str,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> str:
    payload = _seed_request_payload(
        package_digest,
        clustering_config,
        exposure_config,
        risk_config,
    )
    return sha256(_canonical_json(payload)).hexdigest()
```

Serialize results with `asdict(result)` through the same compact JSON settings. Do not expose a second digest format or store raw config JSON in the database.

- [ ] **Step 5: Run focused quality checks**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_seed.py -q
uv run ruff format --check src/wildfireops/replay/seed.py tests/unit/replay/test_seed.py
uv run ruff check src/wildfireops/replay/seed.py tests/unit/replay/test_seed.py
uv run mypy src/wildfireops/replay/seed.py
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit deterministic identity**

```bash
git add backend/src/wildfireops/replay/seed.py backend/tests/unit/replay/test_seed.py
git commit -m "feat: define replay seed identity"
```

---

### Task 2: Seed complete replay state in one PostGIS transaction

**Files:**

- Modify: `backend/src/wildfireops/replay/seed.py`
- Create: `backend/tests/integration/replay/test_seed.py`

**Interfaces:**

- Consumes: `ReplayLoader.static_data`, `ReplayLoader.iter_until()`, `ScenarioRepository.claim_idempotency()`, `ObservationRepository.upsert_many()`, `acquire_incident_refresh_lock()`, `load_current_fire_detections()`, `cluster_detections()`, `refresh_incidents()`, `refresh_exposure_and_risk()`, persisted observed/decision models, `materialize_json_object()`, Shapely `shape()`, and GeoAlchemy2 `WKTElement`.
- Produces: `seed_replay_package(*, loader, session_factory, clustering_config, exposure_config, risk_config) -> ReplaySeedResult` with the exact approved keyword-only public signature.

```python
async def seed_replay_package(
    *,
    loader: ReplayLoader,
    session_factory: SessionFactory,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> ReplaySeedResult:
```

- [ ] **Step 1: Create the committed-transaction PostGIS fixture and synthetic package builder**

In `test_seed.py`, add a module-local `isolated_engine` async fixture following the established integration pattern:

- create the engine with `create_engine(Settings())`;
- truncate `quarantined_observations`, `source_status`, `idempotency_keys`, `resource_units`, `exposed_assets`, `wildfire_incidents`, and `source_observations` with `CASCADE` before each test;
- yield the engine so seed transactions commit normally and concurrent sessions use distinct connections;
- repeat the same truncate in `finally`, then dispose the engine.

Add `_build_synthetic_package(tmp_path, *, variant, package_id="synthetic-seed-v1", fire_intensity=327.4) -> ReplayLoader`. Use `variant` only to give the staging/output directories distinct test-local names, so two different packages may intentionally share one package ID. It must write a staging directory containing:

- two nearby `nasa_firms` fire observations within the test clustering window;
- one nearby `nws` weather observation;
- one nearby community asset with `raw_metadata.demand`;
- one nearby simulated engine resource with `raw_metadata.simulated is True`;
- metadata containing exact versions/citations for `nasa_firms`, `nws`, the asset source, and `simulated_resources`.

Call the existing `build_package()` with a synthetic package ID, bounded Northern California bbox, fixed UTC start/end, and a separate output directory. Return `ReplayLoader(output)`. Do not copy private helpers from the builder or call the network.

Define fixed configs:

```python
CLUSTERING = ClusteringConfig(
    spatial_radius_meters=1_000.0,
    temporal_window_seconds=3_600.0,
    minimum_points=2,
    algorithm_version="dbscan-v1",
)
EXPOSURE = ExposureConfig(buffer_meters=10_000.0)
RISK = default_risk_config()
```

- [ ] **Step 2: Write the successful complete-state test**

Call `seed_replay_package()` with `async_sessionmaker(isolated_engine, expire_on_commit=False)` and assert the returned result is `seeded` with exact static/observation counts and nonzero incident/snapshot counts.

In a fresh session, assert:

- one asset and one resource exist, with source/version provenance and exact materialized demand/simulation metadata;
- all three observations exist in deterministic source identity order;
- at least one active incident exists, every active incident has a non-null risk score, and an `IncidentSnapshotModel` exists for each active incident;
- source statuses are exactly `nasa_firms` and `nws` with `outcome="success"`, `last_attempted_at=manifest.end_at`, per-source latest observation time, exact accepted counts, zero deduplicated/quarantined counts, and no error;
- exactly one `IdempotencyKeyModel` exists with scope `replay_seed`, the package ID key, the expected request hash, and null response fields.

- [ ] **Step 3: Run the successful seed test and verify RED**

Run:

```bash
cd backend
uv run pytest tests/integration/replay/test_seed.py -q -k successful
```

Expected: fail because `seed_replay_package()` is not implemented.

- [ ] **Step 4: Implement the minimal atomic happy path**

Define a local session type alias compatible with `async_sessionmaker`:

```python
type SessionFactory = Callable[[], AsyncSession]
```

Require complete static data and materialize observations before opening the transaction:

```python
static_data = loader.static_data
if static_data is None:
    raise ReplaySeedError("replay seed requires a complete static data package")
observations = tuple(loader.iter_until(loader.manifest.end_at))
```

Inside `async with session_factory() as session` and `async with session.begin()`:

1. acquire the incident advisory lock;
2. claim `replay_seed` idempotency;
3. for the initial happy path, require the claim to be new;
4. insert sorted assets/resources;
5. insert observations and reject nonzero deduplication;
6. flush, load current fire detections at `manifest.end_at`, and cluster them;
7. reject zero clusters;
8. refresh incidents, flush, count created incident rows;
9. refresh exposure/risk and retain returned snapshot IDs;
10. iterate actual source names in sorted order; for each source, set accepted count to its observation count, `last_success_at` to its maximum `observed_at`, `last_attempted_at` to `manifest.end_at`, both rejected counts to zero, outcome to success, and error to null;
11. return `ReplaySeedResult` with the package ID/digest, `status="seeded"`, the two static lengths, `stats.inserted`, the committed incident count, and `len(snapshot_ids)`; let the transaction context commit.

Convert each validated geometry with:

```python
WKTElement(shape(item.geometry_geojson).wkt, srid=4326)
```

Convert metadata with `materialize_json_object()` and capabilities with `list(item.capabilities)`. Pass `clustering_config.algorithm_version` to exposure/risk refresh.

- [ ] **Step 5: Run the successful seed test and verify GREEN**

Run:

```bash
cd backend
uv run pytest tests/integration/replay/test_seed.py -q -k successful
```

Expected: the complete state commits and every assertion passes.

- [ ] **Step 6: Write ownership, conflict, precondition, and rollback tests**

Add tests for all of these contracts:

1. **Identical no-op:** seed once, record row counts for base rows, `IncidentDetectionModel`, `IncidentSnapshotModel`, source statuses, and idempotency claims; seed the same loader/config again; assert `already_seeded`, all result counts zero, and every row count unchanged.
2. **Changed package conflict:** build a second package with the same package ID but changed fire content/hash; after the first seed, assert `ReplaySeedConflict` and unchanged row counts.
3. **Changed config conflict:** after the first seed, rerun with a changed valid clustering radius and then a changed valid exposure buffer; each must raise `ReplaySeedConflict`. The unit test from Task 1 proves every currently registered risk field participates in the same request digest.
4. **Dirty database refusal:** parameterize the six protected base models. Insert one valid row into exactly one protected table, commit it, then seed a package with no existing replay claim. Assert `ReplaySeedConflict`, preserve the inserted row, and assert no `replay_seed` idempotency claim remains.
5. **Legacy package refusal:** use `ReplayLoader(Path("tests/fixtures/replay-small"))`; assert `ReplaySeedError` before any database row is written.
6. **No clusters:** use `minimum_points` greater than the package's fire count; assert `ReplaySeedError` and zero rows/claims after rollback.
7. **Injected refresh failure:** parameterize `wildfireops.replay.seed.refresh_incidents` and `wildfireops.replay.seed.refresh_exposure_and_risk`; replace the selected function with an async function that raises `RuntimeError("synthetic refresh failure")`. For each refresh boundary, assert that exact error propagates and all base, membership, snapshot, status, and idempotency tables remain empty.
8. **Concurrent distinct seeds:** build two complete packages with distinct IDs, start both seed calls with `asyncio.gather(seed_first(), seed_second(), return_exceptions=True)`, and use the real engine-backed session factory. Assert exactly one `ReplaySeedResult(status="seeded")`, exactly one `ReplaySeedConflict`, one committed `replay_seed` claim, and one package's rows. Do not assert which package wins.

- [ ] **Step 7: Run the protection tests and confirm the missing behavior is RED**

Run:

```bash
cd backend
uv run pytest tests/integration/replay/test_seed.py -q
```

Expected: the happy path passes; at minimum identical no-op and dirty-database ownership tests fail until the remaining guards are implemented.

- [ ] **Step 8: Implement idempotency and ownership guards**

Immediately after the advisory lock and claim:

```python
if not claim.created:
    if claim.request_hash != request_hash:
        raise ReplaySeedConflict(
            f"replay package_id already seeded with different contents or settings: {loader.manifest.package_id}"
        )
    return ReplaySeedResult(
        package_id=loader.manifest.package_id,
        package_digest=package_digest,
        status="already_seeded",
        assets_inserted=0,
        resources_inserted=0,
        observations_inserted=0,
        incidents_created=0,
        snapshots_created=0,
    )
```

For a new claim, check these columns in this exact stable order with `select(column).limit(1)`:

```python
_PROTECTED_TABLES = (
    ("source_observations", SourceObservationModel.id),
    ("quarantined_observations", QuarantinedObservationModel.id),
    ("exposed_assets", ExposedAssetModel.id),
    ("resource_units", ResourceUnitModel.id),
    ("wildfire_incidents", WildfireIncidentModel.id),
    ("source_status", SourceStatusModel.id),
)
```

Raise `ReplaySeedConflict(f"database contains operational data in {table_name}")` on the first row found. Because the claim is in the same transaction, the conflict rolls the new claim back. Do not include `idempotency_keys` in this ownership check: unrelated scopes are allowed, while the exact replay claim is handled first.

- [ ] **Step 9: Run focused integration and regression checks**

Run:

```bash
cd backend
uv run pytest tests/integration/replay/test_seed.py -q
uv run pytest tests/unit/replay tests/integration/ingestion tests/integration/geospatial -q
uv run ruff format --check src/wildfireops/replay/seed.py tests/integration/replay/test_seed.py
uv run ruff check src/wildfireops/replay/seed.py tests/integration/replay/test_seed.py
uv run mypy src/wildfireops/replay/seed.py
```

Expected: all commands exit `0`; concurrency completes without a uniqueness race, rollback leaves no replay claim, and existing ingestion/replay derivation behavior remains green.

- [ ] **Step 10: Commit the atomic seed service**

```bash
git add backend/src/wildfireops/replay/seed.py backend/tests/integration/replay/test_seed.py
git commit -m "feat: seed replay state atomically"
```

---

### Task 3: Add the credential-free CLI and repeatable Task 14 workflow

**Files:**

- Modify: `backend/src/wildfireops/replay/seed.py`
- Modify: `backend/tests/unit/replay/test_seed.py`
- Modify: `docs/superpowers/plans/2026-07-16-wildfireops-implementation.md`

**Interfaces:**

- Consumes: `Settings/get_settings`, `create_engine/create_session_factory`, existing settings-to-risk helpers, `ReplayLoader`, and `seed_replay_package()`.
- Produces: `python -m wildfireops.replay.seed PACKAGE` and an updated offline Task 14 command sequence.

- [ ] **Step 1: Write failing CLI behavior tests**

Keep the tests offline and database-free by monkeypatching module collaborators. Prove:

1. one positional `Path` reaches `ReplayLoader`;
2. settings construct all four clustering fields, the configured exposure buffer, and the complete registered risk config;
3. the successful `ReplaySeedResult` is printed as exactly one `_result_json()` line and exit code `0` is returned;
4. the engine is disposed in `finally`;
5. `ReplayPackageCorrupt` and `ReplaySeedError` print their safe messages to stderr and return `1`;
6. an unexpected exception prints only `TypeName`, not its message, and returns `1`.

Patch `wildfireops.replay.seed.seed_replay_package`; do not instantiate live adapters or patch environment credentials.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_seed.py -q -k cli
```

Expected: fail because parser/main orchestration is absent.

- [ ] **Step 3: Implement the thin CLI**

Add `_argument_parser()` with one positional `PACKAGE: Path`. `_async_main(package)` must:

1. load `Settings` and construct `ReplayLoader(package)` before engine creation;
2. create the engine/session factory;
3. construct `ClusteringConfig` from all four clustering settings;
4. reuse `build_exposure_config(settings)` and `build_risk_config(settings)` from `wildfireops.ingestion.worker` so the registered risk configuration is not duplicated;
5. await `seed_replay_package()`;
6. print `_result_json(result)`;
7. always dispose the engine in `finally`.

`main(argv: Sequence[str] | None = None) -> int` parses arguments and runs `_async_main`. Catch `ReplayPackageCorrupt` and `ReplaySeedError`, print `replay seed failed: {error}` to stderr, and return `1`. Catch other `Exception`, print only `replay seed failed: {type(error).__name__}`, and return `1`. Do not catch `KeyboardInterrupt` or `SystemExit`.

End the module with:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Update Task 14's exact offline command order**

In `docs/superpowers/plans/2026-07-16-wildfireops-implementation.md`, keep the existing package build and road-graph attachment commands, then append:

```bash
uv run alembic upgrade head
uv run python -m wildfireops.replay.seed ../data/replay/park-fire
```

State explicitly that the database must be empty for a new replay seed, an identical rerun is a no-op, and changed package/config contents conflict. Update Task 14 Step 3 to say the golden integration test consumes the already seeded operational state rather than implementing another loader-to-database path.

- [ ] **Step 5: Run focused CLI/documentation checks**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_seed.py tests/integration/replay/test_seed.py -q
uv run python -m wildfireops.replay.seed --help
uv run ruff format --check src/wildfireops/replay/seed.py tests/unit/replay/test_seed.py tests/integration/replay/test_seed.py
uv run ruff check src/wildfireops/replay/seed.py tests/unit/replay/test_seed.py tests/integration/replay/test_seed.py
uv run mypy src/wildfireops/replay/seed.py
cd ..
git diff --check
```

Expected: tests and static checks pass; help shows exactly one `PACKAGE` positional argument; documentation has no whitespace errors.

- [ ] **Step 6: Commit the seed command and workflow**

```bash
git add backend/src/wildfireops/replay/seed.py backend/tests/unit/replay/test_seed.py docs/superpowers/plans/2026-07-16-wildfireops-implementation.md
git commit -m "feat: add deterministic replay seed command"
```

---

### Task 4: Verify the complete slice and obtain independent review

**Files:**

- Verify only; modify implementation/tests/docs only for concrete review findings.

**Interfaces:**

- Consumes: Tasks 1-3.
- Produces: full backend regression evidence, independent correctness review, clean Git state, and an updated draft PR.

- [ ] **Step 1: Run complete backend verification from the repository environment**

Run:

```bash
cd backend
uv run pytest tests/unit tests/architecture -q
uv run pytest tests/integration -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
cd ..
git diff --check
git status --short
```

Expected: every command exits `0`; only intentional uncommitted review fixes may appear in status.

- [ ] **Step 2: Request independent architecture/correctness review**

Use `superpowers:requesting-code-review` with the reviewer routing above. Require the reviewer to inspect:

- canonical digest completeness and stable serialization;
- claim/lock ordering and same-claim no-op precedence;
- dirty-database ownership and unrelated idempotency scope behavior;
- transaction boundaries and rollback of the claim itself;
- concurrency behavior on distinct package IDs;
- source-status timestamp semantics;
- geometry/metadata preservation;
- CLI error sanitization and engine disposal;
- absence of a second derivation path, migration, network access, or speculative abstraction.

- [ ] **Step 3: Resolve findings with TDD and rerun affected/full checks**

For every accepted finding, first add or tighten the reproducing test, verify it fails, implement the smallest fix, rerun the focused test, then rerun Task 4 Step 1. Commit accepted fixes with a specific conventional commit message. Do not implement preference-only scope expansion.

- [ ] **Step 4: Push and update the draft pull request**

Push `feat/wildfireops-implementation`. Update draft PR #1 with:

- deterministic replay seed command and ownership rules;
- exact new unit/integration counts;
- transaction, idempotency, rollback, and concurrency evidence;
- explicit statement that the package fixture is synthetic and real Park Fire acquisition remains deferred.

Verify the remote PR head equals local `HEAD` and the local tracked worktree is clean.

---

## Spec Coverage

| Approved design requirement | Plan coverage |
|---|---|
| Complete package only; legacy remains readable | Task 2 Steps 1, 6, 8 |
| Semantic package digest including attached graph | Task 1 Steps 1, 4 |
| Request identity covers clustering/exposure/risk | Task 1 Steps 1, 4; Task 2 Step 6 |
| Same ID + same request is no-op | Task 2 Steps 6, 8 |
| Same ID + changed contents/settings conflicts | Task 2 Steps 6, 8 |
| Refuse unrelated operational data | Task 2 Steps 6, 8 |
| Serialize with ingestion via advisory lock | Task 2 Steps 4, 6, 8 |
| Atomic static/observation/derived/status transaction | Task 2 Steps 2, 4, 6 |
| Existing clustering/exposure/risk implementations only | Global Constraints; Task 2 Step 4 |
| Usable incidents/snapshots/risk after one command | Task 2 Steps 2, 4 |
| Actual-source freshness at manifest end | Task 2 Steps 2, 4 |
| Rollback includes idempotency claim | Task 2 Step 6 |
| Concurrent distinct seeds cannot both own an empty DB | Task 2 Step 6 |
| Credential-free CLI with sanitized failures | Task 3 Steps 1-3 |
| Task 14 build → graph → migrate → seed flow | Task 3 Step 4 |
| No migration/API/frontend/worker/notification/framework | Global Constraints; Task 4 review |

## Deferred Work

- replay-mode API startup and package provenance responses;
- road-graph pinning at process startup;
- semantic Park Fire golden outputs and degraded-mode proof;
- Playwright demonstration and measured benchmarks;
- real Park Fire acquisition, historical weather selection, graph curation, licensing, and attribution.
