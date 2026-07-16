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
