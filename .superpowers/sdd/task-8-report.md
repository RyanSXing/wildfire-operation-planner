# Task 8: Park Fire decision fixture

## Source selection

Read-only Overpass query executed against `https://overpass-api.de/api/interpreter`
on 2026-07-25. The returned `timestamp_osm_base` was
`2026-07-25T14:03:09Z`; the historical FIRMS detection centroid was
`(-121.65282834437086, 40.15947960264901)`.

Nearest named, geometry-bearing candidates selected by `(distance, element type,
element ID)` were:

| Asset | OSM identity | Coordinates | Centroid distance |
| --- | --- | --- | --- |
| Paradise Substation | `way/1256348450` | `-121.61888, 39.7606558` | `0.400266` |
| Adventist Health Feather River | `way/577807430` | `-121.570327, 39.757417` | `0.410440` |
| CARD Community Center | `way/1392880190` | `-121.833301, 39.7340607` | `0.462116` |

The query returned no named, geometry-bearing communications-tower candidate in
the replay bounds, so no communications asset was invented. Census communities
are copied exactly from `exposed_assets.geojson`; Live Monitor assets and
resources were not changed.

## Behavioral tuning

The checkpoint-one closure is
`osm-20100003f58c64e9ea9c5b1b82874110b4315c6fe6c421cb4cc484111874e91f`.
It is on the protected-services/max-population checkpoint-one selected routes.
At checkpoint two, all selected routes avoid it, all presets retain uncovered
demand, and the road crew is selected for `clear-primary-corridor`. Its accepted
consequence reopens only that edge at checkpoint three. The direct planner and
PostGIS journey both showed two distinct objective assignment sets; each final
path accepted `exercise-bus-1 -> shelter-capacity-transport`.

## Commands and results

```text
cd backend && uv run pytest tests/unit/replay/test_manifest.py::test_with_files_returns_valid_replacement_without_mutating_original tests/unit/replay/test_park_fire_package.py::test_committed_park_fire_exercise_is_complete -q
2 passed

cd backend && uv run pytest tests/unit/replay/test_park_fire_package.py tests/integration/replay/test_park_fire_exercise_golden.py -q
3 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/unit tests/architecture -q
718 passed, 3 existing fork warnings

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/integration/replay -q
24 passed

cd backend && uv run ruff check src/wildfireops/replay/manifest.py tests/unit/replay/test_manifest.py tests/unit/replay/test_park_fire_package.py tests/integration/replay/test_park_fire_exercise_golden.py
All checks passed

cd backend && uv run mypy src/wildfireops/replay/manifest.py
Success: no issues found in 1 source file
```

The golden journey used
`postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test`,
seeded and truncated inside the fixture, and invokes the exercise HTTP services
for all three objective presets. `exercise_golden_outputs.json` pins planning
input hashes, task penalties, assignments and exact route edge IDs, coverage,
objective components, constraints, causal codes, corridor consequences,
override semantics, and audit event types.

## Review follow-up

The replay contract now requires the canonical external source name
`OpenStreetMap` (case-sensitive); Census matching is unchanged. Startup calls
the graph-dependent validator after loading the exercise definition and graph.
It validates all asset/resource snaps, every checkpoint and sandbox closure
edge, and an optimal locked shelter-bus plan for every objective under both
corridor-cleared states.

Golden normalization now includes plan version markers and ordered audit
semantics (actor/display, session versions, deterministic state, public inputs,
note, and consequences), while removing UUID-backed plan references and private
response snapshots. The test fixture uses the fixed `EMBER-GOLDEN` callsign.

```text
cd backend && uv run pytest tests/unit/replay/test_exercise.py tests/unit/replay/test_manifest.py tests/unit/replay/test_park_fire_package.py tests/unit/application/test_exercise_planning.py tests/unit/test_health.py tests/integration/replay/test_park_fire_exercise_golden.py -q
102 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/integration/replay -q
24 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/unit tests/architecture -q
723 passed, 3 existing fork warnings

cd backend && uv run ruff check [touched files]
All checks passed

cd backend && uv run mypy src/wildfireops/replay/exercise.py src/wildfireops/application/exercise_planning.py src/wildfireops/main.py
Success: no issues found in 3 source files
```

Final hashes:

```text
exercise.json: f98966af9cce464e132d899ae1bcc952a421a0845390667a8852fbd7a773c5e0
exercise_golden_outputs.json: 570db014d930a1a8c5b7704c92ab5a004d4b977e87fdf5287daf7035103fbe88
```

## Final hardening

Runtime validation now derives a deterministic public node-coordinate envelope
from the pinned road graph. Every asset and resource must be inside that
envelope and within 1,000 geodesic meters of a road node; the distance uses
WGS84 geodesics rather than degree differences. Closure and locked-shelter-plan
failures preserve their `exercise.json` origin and indexed source path.

The complete HTTP journey now submits the final decision with the fixed display
name `Golden Operator` and note `Approve the validated shelter transport
override.`, and it pins the completed session and `exercise.plan-approved`
audit event. UUID-backed plan references normalize to the deterministic aliases
`initial`, `cascade`, `field`, and `override`; an unrecognized linkage UUID is a
test failure.

```text
cd backend && uv run pytest tests/unit/geospatial/test_road_graph.py tests/unit/application/test_exercise_planning.py tests/integration/replay/test_park_fire_exercise_golden.py -q
61 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/integration/replay -q
25 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/unit tests/architecture -q
726 passed, 3 existing macOS fork warnings

cd backend && uv run ruff check src/wildfireops/application/exercise_planning.py src/wildfireops/geospatial/road_graph.py tests/unit/application/test_exercise_planning.py tests/unit/geospatial/test_road_graph.py tests/integration/replay/test_park_fire_exercise_golden.py
All checks passed

cd backend && uv run mypy src/wildfireops/application/exercise_planning.py src/wildfireops/geospatial/road_graph.py
Success: no issues found in 2 source files
```

Final hashes:

```text
exercise.json: f98966af9cce464e132d899ae1bcc952a421a0845390667a8852fbd7a773c5e0
exercise_golden_outputs.json: 0af70036f55718a2ccfe3d9ec256439ed162cf620d6c5bca32dec01df48fee47
```

## Final reviewer corrections

Snap-distance validation now measures the WGS84 distance to the exact node
chosen by `nearest_road_node`, rather than independently choosing a geodesic
nearest node. The public `RoadGraph.node_position` accessor rejects unknown or
non-finite nodes. Position failures include the authored longitude/latitude;
distance failures additionally identify the selected node, its coordinates, and
the measured distance.

`sandbox.closureEdgeIds` is now an ordered tuple, rejects duplicate values while
loading the definition, and retains authored indices in diagnostics. The
anisotropic latitude-80 test proves a degree-nearest selected node beyond 1 km
is rejected even when another graph node is geodesically nearer than 1 km.

```text
cd backend && uv run pytest tests/unit/replay/test_exercise.py tests/unit/application/test_exercise_planning.py tests/unit/geospatial/test_road_graph.py -q
92 passed

cd backend && uv run pytest tests/unit/replay/test_park_fire_package.py tests/integration/replay/test_park_fire_exercise_golden.py -q
4 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/integration/replay -q
25 passed

cd backend && WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test uv run pytest tests/unit tests/architecture -q
728 passed, 3 existing macOS fork warnings

cd backend && uv run ruff check [touched files]
All checks passed

cd backend && uv run mypy src/wildfireops/replay/exercise.py src/wildfireops/geospatial/road_graph.py src/wildfireops/application/exercise_planning.py
Success: no issues found in 3 source files
```

The serialized fixture bytes and its golden output are unchanged, so no manifest
regeneration was required.
