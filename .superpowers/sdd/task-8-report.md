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
