# Park Fire Replay Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing WildfireOps preview run one deterministic Park Fire operator workflow using committed, sourced replay data.

**Architecture:** Reuse the replay builder, loader, seeder, database schema, API routes, and React workflow already in the repository. Commit one small canonical replay package containing archived FIRMS and NOAA observations, Census-derived exposure data, simulated resources, and a bounded OpenStreetMap road graph. An optional package path selects replay startup, fixes the API clock to the package end time, and loads the pinned road graph; a Compose override performs migration and idempotent seeding before starting the existing API and frontend.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL/PostGIS, NetworkX/OSMnx, React/TypeScript, Vitest, Playwright, Docker Compose.

## Global Constraints

- Keep the application a modular monolith; add no new service or endpoint.
- Treat the presence of `WILDFIREOPS_REPLAY_PACKAGE` as replay mode; add no second mode flag.
- Use real archived NASA FIRMS fire observations and NOAA/NCEI weather observations with source URLs preserved in package citations and raw payloads.
- Mark every resource record as simulated and keep the persistent life-safety disclaimer.
- Replay startup must perform no external network access and must use `manifest.end_at` as its clock.
- Keep live startup unchanged when no replay package is configured.
- The browser journey ends after incident selection, road-closure scenario comparison, recommendation approval with `Stage resources for replay exercise`, and audit verification.

---

### Task 1: Commit a validated Park Fire replay package

**Files:**
- Create: `data/replay/park-fire/manifest.json`
- Create: `data/replay/park-fire/fire_detections.jsonl`
- Create: `data/replay/park-fire/weather_observations.jsonl`
- Create: `data/replay/park-fire/static_data_versions.json`
- Create: `data/replay/park-fire/source_citations.json`
- Create: `data/replay/park-fire/exposed_assets.geojson`
- Create: `data/replay/park-fire/resources.json`
- Create: `data/replay/park-fire/roads.graphml.gz`
- Create: `backend/tests/unit/replay/test_park_fire_package.py`

**Interfaces:**
- Consumes: `ReplayLoader(Path)`, `RoadGraph.load(Path)`, and the existing replay builder/road-graph publisher.
- Produces: an offline package whose manifest has `package_id == "park-fire-2024-v1"`, complete static data, real `nasa_firms` and `noaa_ncei` observations, and one pinned road graph.

- [ ] **Step 1: Write the failing package contract test**

```python
def test_committed_park_fire_package_is_complete() -> None:
    package = Path(__file__).parents[4] / "data/replay/park-fire"
    loader = ReplayLoader(package)

    assert loader.manifest.package_id == "park-fire-2024-v1"
    assert loader.static_data is not None
    assert {item.source_name for item in loader.iter_until(loader.manifest.end_at)} == {
        "nasa_firms",
        "noaa_ncei",
    }
    assert loader.manifest.road_graph is not None
    graph = RoadGraph.load(package / loader.manifest.road_graph.filename)
    assert graph.graph_version == loader.manifest.road_graph.graph_version
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && uv run pytest tests/unit/replay/test_park_fire_package.py -q`

Expected: FAIL because `data/replay/park-fire` does not exist.

- [ ] **Step 3: Acquire and normalize only the bounded records**

Download the official FIRMS 2024 United States S-NPP CSV and NOAA/NCEI 2024 KCIC Global Hourly CSV outside the repository. Keep only observations inside the manifest time window and bbox. Convert FIRMS confidence to `[0, 1]`, use `bright_ti4` as intensity, decode NCEI `WND` speed from tenths of metres per second and `TMP` from tenths of degrees Celsius, and retain original source fields in `raw_payload`.

Use Census QuickFacts/Gazetteer values for exposed community records, OpenStreetMap data for the road graph, and a small explicitly simulated resource inventory. Build through `wildfireops.replay.build` and attach the graph through `wildfireops.geospatial.road_graph`; do not hand-edit manifest hashes.

- [ ] **Step 4: Run the package contract test and existing replay tests**

Run: `cd backend && uv run pytest tests/unit/replay/test_park_fire_package.py tests/unit/replay -q`

Expected: PASS, with every source citation HTTPS and no secret in any package file.

- [ ] **Step 5: Commit the package**

```bash
git add data/replay/park-fire backend/tests/unit/replay/test_park_fire_package.py
git commit -m "feat: add Park Fire replay package"
```

---

### Task 2: Start the API deterministically from the replay package

**Files:**
- Modify: `backend/src/wildfireops/config.py`
- Modify: `backend/src/wildfireops/main.py`
- Modify: `backend/tests/unit/test_health.py`
- Create: `compose.replay.yaml`

**Interfaces:**
- Consumes: `Settings.replay_package: Path | None`, `ReplayLoader`, `ReplayClock`, and `RoadGraph.load`.
- Produces: `create_app(Settings(replay_package=...))` with `app.state.clock()` fixed to `manifest.end_at` and `app.state.graphs` containing the verified pinned graph.

- [ ] **Step 1: Write failing replay-startup tests**

```python
def test_replay_startup_uses_manifest_clock_and_graph() -> None:
    app = create_app(Settings(replay_package=PARK_FIRE_PACKAGE))
    loader = ReplayLoader(PARK_FIRE_PACKAGE)
    assert app.state.clock() == loader.manifest.end_at
    assert tuple(app.state.graphs) == (loader.manifest.road_graph.graph_version,)


def test_live_startup_keeps_wall_clock_and_no_graphs() -> None:
    app = create_app(Settings(replay_package=None))
    assert app.state.graphs == {}
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend && uv run pytest tests/unit/test_health.py -q`

Expected: FAIL because `Settings` has no `replay_package` and `create_app` does not load replay state.

- [ ] **Step 3: Implement the minimum startup branch**

Add one optional path setting. In `create_app`, load the package before creating state, select `manifest.end_at` for the clock, load the manifest graph when present, and reject graph-version mismatches. Leave the current wall clock and empty graph registry untouched when the path is absent.

- [ ] **Step 4: Add the one-command replay Compose override**

Mount `./data/replay/park-fire` read-only at `/data/replay/park-fire`, set `WILDFIREOPS_REPLAY_PACKAGE`, and override the API command to run `alembic upgrade head`, the existing idempotent seed CLI, then Uvicorn. Start only `db api frontend`, so the live ingestion worker cannot mutate replay state.

- [ ] **Step 5: Verify focused and architecture tests**

Run: `cd backend && uv run pytest tests/unit/test_health.py tests/architecture -q && uv run ruff check src/wildfireops/config.py src/wildfireops/main.py tests/unit/test_health.py && uv run mypy src/wildfireops/config.py src/wildfireops/main.py`

Expected: PASS.

- [ ] **Step 6: Commit replay startup**

```bash
git add backend/src/wildfireops/config.py backend/src/wildfireops/main.py backend/tests/unit/test_health.py compose.replay.yaml
git commit -m "feat: start API in replay mode"
```

---

### Task 3: Prove the operator journey in a real browser

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/replay-decision.spec.ts`
- Modify only if the browser test exposes a real defect: existing React/API files on the failing path.

**Interfaces:**
- Consumes: the existing accessible incident, scenario, recommendation, decision, and audit controls.
- Produces: one Playwright test that runs against the Compose replay preview without mocking network requests.

- [ ] **Step 1: Write the browser test**

The test must select the highest-risk incident, assert risk and source freshness, create the baseline, close one listed road, generate and compare the scenario recommendation, approve it with `Stage resources for replay exercise`, and verify that note in the audit drawer. Use roles/labels visible in the existing UI; add no test-only production endpoint.

- [ ] **Step 2: Run the browser test and verify RED**

Run: `docker compose -f compose.yaml -f compose.replay.yaml up -d db api frontend && cd frontend && npx playwright test e2e/replay-decision.spec.ts`

Expected: FAIL at the first missing or broken browser behavior, proving the test reaches the real application.

- [ ] **Step 3: Fix only defects exposed by the journey**

Apply the smallest shared-path fix, then rerun the same Playwright test after each change. Do not add unrelated UI polish.

- [ ] **Step 4: Run the focused browser and frontend checks**

Run: `cd frontend && npm test -- --run && npm run build && npx playwright test e2e/replay-decision.spec.ts`

Expected: 196 or more Vitest tests pass, the production build passes, and the real browser journey passes.

- [ ] **Step 5: Commit the browser proof**

```bash
git add frontend
git commit -m "test: prove replay operator journey"
```

---

### Final verification

- [ ] Run all backend unit/architecture tests, all PostGIS integration tests, frontend tests/build, and the replay browser journey.
- [ ] Inspect the preview for meaningful Park Fire content, no error overlay, and no console errors.
- [ ] Push the branch and open a pull request; do not merge without user approval.
