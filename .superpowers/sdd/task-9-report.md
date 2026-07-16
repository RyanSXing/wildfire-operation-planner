# Task 9 implementation report

## Status

Implemented immutable scenario branching, closure-aware directed multigraph routing,
and the explicit Park Fire road-graph build command. No live OSM request was made and
no Park Fire replay or graph artifact was fabricated.

## Files

- `backend/src/wildfireops/geospatial/road_graph.py`
  - Immutable, versioned `RoadGraph` loading and per-path load cache.
  - Directed/multiedge validation, deterministic routing, closure hashing, and route
    caching.
  - OSMnx retrieval boundary and `build` CLI with staged graph/manifest publication.
- `backend/src/wildfireops/decision/scenarios.py`
  - Persistence-neutral `ScenarioRepository` protocol.
  - `ScenarioService.create()` and `ScenarioService.add_version()` orchestration,
    canonical replacement hashing, pin validation, and stable conflict types.
- `backend/src/wildfireops/domain/scenario_versions.py`
  - Neutral immutable idempotency, snapshot, and stored-version envelopes.
  - The accepted Task 2 `ScenarioVersion` constructor remains unchanged.
- `backend/src/wildfireops/persistence/scenarios.py`
  - Session-bound, flush-only SQLAlchemy adapter.
  - PostgreSQL atomic idempotency claims and row-lock serialization.
- `backend/src/wildfireops/replay/manifest.py`
  - Optional, strictly typed `RoadGraphMetadata` extension.
  - Legacy schema-version-1 manifests remain valid and omit `road_graph` when absent.
  - Atomic serialization, metadata/file-digest consistency, and bbox validation.
- `backend/pyproject.toml`, `backend/uv.lock`
  - Locked runtime and typing dependency changes.
- `backend/tests/unit/geospatial/test_road_graph.py`
  - Routing, multiedge, malformed-data, deterministic-cache, loader, and CLI tests.
- `backend/tests/integration/decision/test_scenarios.py`
  - Immutability, tri-state replacement, pinned-state validation, idempotency,
    concurrency, and rollback tests.
- `backend/tests/unit/replay/test_manifest.py`
  - Legacy compatibility and typed metadata round-trip/validation tests.
- `backend/tests/architecture/test_api_boundaries.py`
  - Decision-layer dependency guard and relative-import resolution regression.
- `backend/tests/integration/conftest.py`
  - Isolates scenario resource/idempotency state for integration tests.

## Exact TDD evidence

### Routing red

Initial command:

```bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py -v
```

The first collection run failed with `ModuleNotFoundError: No module named
'networkx'`, proving the runtime dependency was absent. After adding dependencies
through `uv add`, the same command failed at the intended feature boundary:

```text
ModuleNotFoundError: No module named 'wildfireops.geospatial.road_graph'
collected 0 items / 1 error
```

After the minimal routing implementation, the same command produced:

```text
1 passed in 0.11s
```

Subsequent red/green cycles covered missing `RoadGraph.load`, OSMnx string
attributes, zero-cost cycles, one-read caching, malformed GraphML, missing nodes,
parallel-edge closure fallback, and the build CLI. The final routing/CLI file has
19 passing tests.

### Scenario red

Command:

```bash
cd backend
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@10.0.0.151:5432/wildfireops_test \
  uv run pytest tests/integration/decision/test_scenarios.py -v
```

Red result:

```text
ModuleNotFoundError: No module named 'wildfireops.decision.scenarios'
collected 0 items / 1 error
```

After the first persistence/service implementation:

```text
1 passed in 1.62s
```

The decision dependency test was then added and failed with the concrete forbidden
imports `sqlalchemy.ext.asyncio` and `wildfireops.persistence.scenarios`. The
service boundary was inverted to a neutral protocol/session-bound adapter, after
which the architecture test passed. The final scenario file has 11 passing tests.

### Manifest red

Command:

```bash
cd backend
uv run pytest tests/unit/replay/test_manifest.py -v
```

Red result:

```text
ImportError: cannot import name 'RoadGraphMetadata' from
'wildfireops.replay.manifest'
collected 0 items / 1 error
```

The typed backward-compatible extension then passed all manifest tests, including
legacy omission and atomic metadata round-trip.

## Public signatures and decisions

```python
RoadGraph.from_graph(graph: nx.Graph) -> RoadGraph
RoadGraph.load(path: Path) -> RoadGraph
compute_route(
    graph: RoadGraph,
    origin: Hashable,
    destination: Hashable,
    closed_edge_ids: tuple[str, ...] | list[str] | frozenset[str] | set[str],
) -> RouteResult
build_road_graph(
    *,
    bbox: tuple[float, float, float, float],
    output: Path,
    network_type: str = "drive",
    retriever: RoadGraphRetriever | None = None,
    clock: UtcClock | None = None,
) -> Path
ScenarioService(*, graphs: Mapping[str, RoadGraph], repository: ScenarioRepository)
ScenarioService.create(...) -> StoredScenarioVersion
ScenarioService.add_version(...) -> StoredScenarioVersion
ScenarioRepository(session: AsyncSession)
```

- Loaded graph versions are the SHA-256 digest of the exact GraphML/GZip bytes.
- Generated OSM edge IDs are SHA-256 identities of `(u, v, key)` and are stable
  across insertion order. GZip uses `mtime=0`.
- Route priority is `(travel_minutes, hop_count, edge_id_sequence)`, making parallel
  ties and zero-cost cycles deterministic.
- Edge IDs must be unique nonblank strings. Travel time and distance must be finite
  and nonnegative. OSMnx string attributes are explicitly converted.
- Distance uses `distance_meters`, then OSMnx `length`; literal Task 9 toy edges with
  neither deliberately contribute zero meters.
- Missing route endpoints return `RouteStatus.UNREACHABLE`. Unknown closure IDs are
  rejected.
- Closure input is stripped, deduplicated, sorted, and SHA-256 hashed. The cache key
  is `(graph_version, closure_hash, origin, destination)`.
- `RoadGraph.load` parses each resolved immutable version path once per process.
- Scenario overlays use an explicit tri-state contract per category: `None` inherits
  the prior category, while a tuple replaces it and `()` clears it.
- Replacement sets are normalized and sorted before canonical JSON SHA-256 hashing;
  duplicate road/resource identities and non-finite weather values are rejected.
- `IdempotencyConflict.code` is the transport-neutral stable value
  `idempotency_conflict`; Task 9 adds no HTTP mapping.
- Idempotency claims use PostgreSQL `INSERT ... ON CONFLICT DO NOTHING RETURNING`,
  then lock/read the winning claim. Scenario rows use `FOR UPDATE` before deriving
  `latest.version + 1`.
- The caller owns commit and rollback. The repository flushes only; version rows,
  children, and idempotency completion live in the caller's transaction.
- Every scenario version preserves the original incident snapshot ID and graph
  version. Road IDs resolve against that graph; resource IDs are strictly extracted
  from that snapshot's `resource_state` JSON, not inferred from live resources.
- `StoredScenarioVersion` carries the database version UUID and graph version around
  the unchanged Task 2 `ScenarioVersion` value object.
- `ReplayManifest.road_graph` is optional. When present it records filename,
  retrieval UTC timestamp, exact bbox, network type, OSMnx version, graph digest
  (also the graph version), and edge count. Its file entry must carry the same digest.
- The CLI validates the existing manifest and exact bbox before invoking retrieval,
  refuses overwrites, and stages both files. If manifest publication fails after the
  graph rename, it removes the new graph and leaves the old manifest unchanged.

Exact explicit invocation:

```bash
cd backend
uv run python -m wildfireops.geospatial.road_graph build \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --output ../data/replay/park-fire/roads.graphml.gz
```

## Dependency changes

Generated with `uv add`; the lockfile was not hand-edited:

- Runtime: `networkx>=3.6.1,<4`
- Runtime: `osmnx>=2.1.0,<3`
- Development typing: `types-networkx>=3.6.1.20260624`

Resolved versions during implementation were NetworkX 3.6.1, OSMnx 2.1.0, and
types-networkx 3.6.1.20260624.

## Verification

Focused Task 9:

```text
30 passed in 4.51s
```

Replay manifest/builder/loader regressions:

```text
80 passed in 1.01s
```

Architecture boundaries:

```text
3 passed in 1.01s
```

Full backend:

```text
477 passed in 20.70s
```

Formatting, lint, and typing:

```text
88 files already formatted
All checks passed!
Success: no issues found in 55 source files
```

All recorded verification output was warning-free.

## Caveats

- The repository does not yet contain the Task 14 Park Fire replay package. This
  task deliberately did not create `data/replay/park-fire`, fabricate a retrieval,
  or invoke OSM. Task 14 must build the replay package first; the explicit graph
  command can then retrieve and pin the graph, followed by replay validation.
- Live OSM retrieval occurs only when the explicit CLI is invoked. Every automated
  test injects a tiny recorded `MultiDiGraph` at the retrieval boundary.
- Graph paths are immutable version locations. Replacing bytes at the same path in a
  running process intentionally does not invalidate the one-read cache; a new graph
  version must use a new path/process.
- OSMnx derives speeds by road metadata/class and uses a 40 km/h fallback where speed
  metadata is absent before calculating travel time.
- A caller must roll back its transaction when a scenario command raises; rollback
  behavior for the idempotency claim, version, and child overlays is integration
  tested.

## Publication safety fix

Review found that the road-graph builder preflighted before retrieval and then used
`os.replace` for both final files. Concurrent builders could therefore interleave one
builder's graph with another builder's manifest, a late output could be overwritten,
and process death after graph publication left an unrecoverable orphan.

The builder now holds a package-local `fcntl.flock` from recovery through the
rechecked preflight, retrieval/build, and publication. It durably stages and validates
the graph and canonical updated manifest, then fsyncs a strict transaction journal
before claiming the graph with same-filesystem `os.link` no-replace semantics. The
journal records the output name, graph digest and inode, exact base-manifest digest,
and canonical updated manifest. Recovery rolls forward only when the current base
digest, base-plus-road-graph structure, journal metadata, final graph inode, and graph
digest all agree. File and package-directory fsyncs cover journal creation, graph
claim, manifest replacement, and journal removal. Recovery publishes through a
unique private staging directory and never removes unrelated output or temporary
files.

### Fix TDD evidence

Initial focused RED command:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py \
  -k 'concurrent_builds_are_serialized_across_processes or interrupted_publication_recovers_without_retrieval or output_created_after_preflight_is_never_overwritten' \
  -vv
```

Result: `3 failed, 19 deselected in 3.82s`. The second process entered retrieval
while the first was blocked, retry rejected the journal-less orphan as already
existing, and a late user file was overwritten.

Additional durability/trust-boundary RED checks produced:

```text
graph directory fsync recovery: 1 failed, 22 deselected in 2.15s
unrelated manifest temp + tampered journal: 2 failed, 22 deselected in 2.23s
changed exact base manifest: 1 failed, 24 deselected in 2.72s
```

Each check then passed after its minimal fix. The final road-graph file contains 25
passing tests, including cross-process serialization, manifest/graph digest agreement,
process-interruption recovery without a second retrieval, directory-fsync recovery,
exact-base and canonical-journal validation, preservation of unrelated manifest temp
content, and no-replace output publication. Every retrieval remains injected; no test
made a live OSM request.

### Fix verification

Road graph plus manifest:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py tests/unit/replay/test_manifest.py -q
```

```text
61 passed in 3.45s
```

Replay unit regressions:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest tests/unit/replay -q
```

```text
90 passed in 0.21s
```

Task 9 focused verification:

```bash
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@10.0.0.151:5432/wildfireops_test \
  UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py \
  tests/integration/decision/test_scenarios.py -q
```

```text
36 passed in 7.42s
```

The first sandboxed Task 9 attempt passed all 25 unit tests but could not open the
database socket (`PermissionError: [Errno 1] Operation not permitted`); the approved
database-enabled rerun above passed all 36 tests.

Formatting, lint, and typing:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run ruff format --check \
  src/wildfireops/geospatial/road_graph.py \
  tests/unit/geospatial/test_road_graph.py
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run ruff check \
  src/wildfireops/geospatial/road_graph.py \
  tests/unit/geospatial/test_road_graph.py
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run mypy src
```

```text
2 files already formatted
All checks passed!
Success: no issues found in 55 source files
```

An independent final publication review returned `APPROVE` with no concrete issues.

## Cumulative ownership review fixes

This section supersedes the cleanup and locking details in the preceding publication
safety section. Cumulative review found six remaining ownership defects: pathname
check-then-unlink cleanup, the fixed manifest temporary, a live-resource FK on
snapshot-owned overrides, a manifest check/replace window, an unpinned graph pathname
at manifest commit, and a swappable package-directory pathname.

The final protocol opens the replay package once with `O_DIRECTORY|O_NOFOLLOW`, takes
one package-writer `fcntl.flock`, and performs sensitive reads, hard links, renames,
replacements, and fsyncs relative to that directory descriptor. `ReplayManifest` uses
the same lock for every in-place manifest write. Road-graph publication holds the
staged graph descriptor through manifest commit, checks its inode and exact digest at
the final pathname immediately before and after commit, and restores the exact base
manifest from its private stage if the graph changes during the commit boundary.

No public graph or journal is conditionally unlinked. Failed graph/manifest
publication leaves the graph and journal for verified roll-forward. A completed or
unrecoverable fixed journal is atomically renamed into a fresh mode-0700 private
orphan directory; if the source pathname was raced, the unrelated replacement is
preserved there and the build reports the ownership change. Package staging
directories are deliberately retained for explicit cleanup instead of introducing a
second pathname-deletion race.

`ReplayManifest.write_atomic` now creates a per-call UUID stage with
`O_CREAT|O_EXCL`, fsyncs it, replaces the target under the shared writer lock, and
fsyncs the opened directory. It never unlinks a failed stage. A pre-existing legacy
`.manifest.json.tmp` is ignored and preserved.

Scenario resource overrides now use the immutable pinned snapshot as their sole
resource-identity authority. Alembic revision `0003_snapshot_resource_overrides`
drops only `scenario_resource_overrides_resource_id_fkey`; its downgrade recreates
that FK with `ON DELETE RESTRICT`. Recommendation assignments retain their separate
live-resource FK.

### Cumulative RED evidence

Manifest ownership:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/replay/test_manifest.py \
  -k 'preexisting_legacy_temporary or raced_unique_stage' -vv
```

```text
2 failed, 36 deselected in 0.08s
```

The legacy fixed temporary raised `FileExistsError` and was then deleted. The
replacement injected after stage creation was also deleted by the unconditional
`finally` unlink.

Publication ownership:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py \
  -k 'manifest_writer_cannot_enter or graph_path_replacement_at_manifest_commit or package_directory_swap or journal_replacement_during_retirement' \
  -vv
```

```text
4 failed, 25 deselected in 2.27s
```

The concurrent writer completed inside the manifest commit window, a graph
replacement at that boundary was committed, a package-directory replacement
redirected publication, and the old `lstat`/`unlink` sequence deleted the raced
journal bytes.

Pinned resource identity:

```bash
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@10.0.0.151:5432/wildfireops_test \
  UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/integration/decision/test_scenarios.py::test_newer_snapshot_and_graph_never_rebase_an_existing_scenario \
  -vv
```

```text
1 failed in 0.98s
ForeignKeyViolationError: scenario_resource_overrides_resource_id_fkey
Key (resource_id)=(engine-1) is not present in table "resource_units".
```

The first sandboxed database attempt could not open the socket with
`PermissionError: [Errno 1] Operation not permitted`; the approved database-enabled
rerun above reached PostgreSQL and reproduced the intended FK failure.

### Cumulative GREEN and verification evidence

All seven focused ownership regressions, including conservative recovery after an
ordinary manifest replace failure:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py \
  tests/unit/replay/test_manifest.py \
  -k 'manifest_writer_cannot_enter or graph_path_replacement_at_manifest_commit or package_directory_swap or journal_replacement_during_retirement or manifest_publish_failure_leaves or preexisting_legacy_temporary or raced_unique_stage' \
  -q
```

```text
7 passed, 60 deselected in 2.75s
```

Road graph plus manifest:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py tests/unit/replay/test_manifest.py -q
```

```text
67 passed in 3.40s
```

Replay unit regressions:

```bash
UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest tests/unit/replay -q
```

```text
92 passed in 0.18s
```

Pinned-snapshot and persistence constraints:

```bash
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@10.0.0.151:5432/wildfireops_test \
  UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/integration/decision/test_scenarios.py \
  tests/integration/persistence/test_scenario_constraints.py -q
```

```text
12 passed in 4.03s
```

Complete Task 9 focused group:

```bash
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@10.0.0.151:5432/wildfireops_test \
  UV_CACHE_DIR=/private/tmp/wildfireops-uv-cache uv run pytest \
  tests/unit/geospatial/test_road_graph.py \
  tests/integration/decision/test_scenarios.py -q
```

```text
40 passed in 7.24s
```

Migration verification completed the full reversible chain:

```bash
uv run alembic heads
uv run alembic upgrade head
uv run alembic downgrade 0002_exposure_geography_idx
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

```text
0003_snapshot_resource_overrides (head)
Running downgrade 0003_snapshot_resource_overrides -> 0002_exposure_geography_idx
Running upgrade 0002_exposure_geography_idx -> 0003_snapshot_resource_overrides
No new upgrade operations detected.
```

Formatting, lint, typing, and patch integrity:

```bash
uv run ruff format --check <seven touched Python files>
uv run ruff check <seven touched Python files>
uv run mypy src
git diff --check
```

```text
7 files already formatted
All checks passed!
Success: no issues found in 55 source files
git diff --check: clean
```

The deletion pass removed 23 net production lines from the first green version. The
settled production delta is +419/-253 in `road_graph.py`, +66/-9 in `manifest.py`,
-1 in the SQLAlchemy model, and +35 lines for the required migration. Automated graph
tests still inject recorded graphs; no test invoked live OSM retrieval.

## Stale manifest writer CAS follow-up

Final review found one remaining cooperative-writer race: a process could read the
legacy manifest before road-graph publication, wait on the package lock, and then
replace the newly published graph manifest with its stale update. The shared lock
serialized replacement but did not prove that the writer's source bytes were still
current.

`ReplayManifest.write_atomic()` now accepts an explicit `expected_digest`. First
creation remains valid without a digest. Replacing an existing manifest requires the
SHA-256 of the exact bytes previously read; a missing target with an expected digest,
an existing target without one, or a changed digest is rejected before a stage file is
created. The current target is reopened relative to the pinned package directory and
validated as a regular, nonsymlink file while the shared package lock is held. Unique
`O_CREAT|O_EXCL` staging and the no-cleanup-on-failure ownership rule are unchanged.
The road-graph builder retains its private exact-base commit while already holding the
same lock, so it does not call the public locking writer or acquire the lock twice.

### CAS RED and GREEN evidence

Focused RED command:

```bash
cd backend
.venv/bin/pytest \
  tests/unit/geospatial/test_road_graph.py::test_manifest_writer_cannot_enter_between_base_check_and_commit \
  -q
```

```text
1 failed in 2.16s
ReplayManifest.write_atomic() got an unexpected keyword argument 'expected_digest'
```

After implementing the locked exact-byte comparison, the same command produced:

```text
1 passed in 2.38s
```

The regression now proves that the stale process waits until graph publication
finishes, receives `manifest.json changed before write`, and leaves the original
package ID, road-graph metadata, and exact graph digest intact. Direct manifest tests
also cover token-free creation, rejection without a token, stale-token rejection,
matching-token replacement, and expected-token rejection for a missing target.

### CAS verification

Manifest and road graph:

```text
71 passed in 3.80s
```

Replay unit regressions:

```text
96 passed in 0.45s
```

Complete Task 9 focused group against PostgreSQL:

```text
40 passed in 6.56s
```

The initial sandboxed Task 9 run passed all 29 unit tests but could not open the
database socket. The database-enabled rerun above passed the full group.

Formatting, lint, typing, and patch integrity:

```text
3 files already formatted
All checks passed!
Success: no issues found in 55 source files
git diff --check: clean
```
