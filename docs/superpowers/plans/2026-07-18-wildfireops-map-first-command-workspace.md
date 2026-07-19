# WildfireOps Map-First Command Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scroll-heavy three-column WildfireOps interface with a map-first command workspace that supports reversible local planning, validated scenario-only resource relocation, locked manual assignments, visual recommendations, and the existing human decision and audit loop.

**Architecture:** A new React command workspace owns one local `planningDraft`, derives preview overlays, and sends semantic interaction events to and from the existing MapLibre component. One deliberate Run plan uses the existing scenario and recommendation commands; backend scenario versions gain validated relocations and locked assignments, while the existing optimizer fixes manual pairs and fills remaining demand. Existing incident, scenario, comparison, recommendation, decision, and audit components move into a nonmodal Details & evidence drawer rather than being rewritten.

**Tech Stack:** React 19, TypeScript, Vite, TanStack Query, MapLibre GL JS, Vitest, Testing Library, Playwright, Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL/PostGIS, NetworkX, Shapely, pyproj, OR-Tools CP-SAT, pytest, Hypothesis.

## Global Constraints

- Do not execute this plan until the currently verified basemap and first-time-workflow changes are committed, reviewed, merged, and the implementation worktree is clean.
- Reuse the existing React/TypeScript, MapLibre, FastAPI, scenario, recommendation, decision, and audit paths; add no UI framework, game engine, global state framework, or workflow state machine.
- The desktop command-center layout applies at widths of 1024px and above; smaller widths use the complete stacked/list fallback.
- Map gestures only change one reversible local draft. Run plan is the only planning write action.
- Observed resource geometry is immutable. Relocation changes only the routing origin stored on an immutable scenario version.
- Manual assignments are locked, validated, preserved exactly, and identified separately from optimized assignments.
- Operational surfaces use human-readable labels. Exact IDs stay in audit and technical evidence.
- Keep the existing label **Priority score** and top driver; do not invent scientific severity categories.
- Keep the persistent portfolio-simulation safety notice on every primary screen.
- Every map action must have a keyboard-accessible list/form equivalent in Details & evidence.
- Use text, icons, fill patterns, and line styles in addition to color; primary pointer targets are at least 44px.
- Honor `prefers-reduced-motion`; no essential state may depend on animation.
- Preserve existing loading, error, disabled, stale, basemap-fallback, and replay-unavailable behavior.
- The browser workflow must pass at 1280×720 and 1024×768 without scrolling through evidence lists.
- Temporal replay repair, degraded-mode/performance proof, CI, production packaging, deployment, screenshots, README expansion, benchmark reporting, and demo video are tracked by separate plans and are not implemented here.

## Preflight Baseline Gate

Before Task 1, finish the existing branch through the `superpowers:finishing-a-development-branch` workflow, merge it, and create a clean implementation worktree from the merged branch with `superpowers:using-git-worktrees`.

Run:

```bash
git status --short
cd frontend
npm test -- --run
npm run build
cd ../backend
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy src
```

Expected: `git status --short` prints nothing; frontend tests/build and backend unit/lint/type checks exit 0. If the baseline is dirty or any check fails, stop and finish that work before executing this plan.

---

### Task 1: Persist Immutable Relocation and Locked-Assignment Inputs

**Files:**
- Create: `backend/migrations/versions/0005_map_first_scenario_inputs.py`
- Modify: `backend/src/wildfireops/domain/scenarios.py`
- Modify: `backend/src/wildfireops/persistence/decision_models.py`
- Modify: `backend/src/wildfireops/persistence/scenarios.py`
- Test: `backend/tests/integration/decision/test_scenarios.py`
- Test: `backend/tests/integration/persistence/test_scenario_constraints.py`

**Interfaces:**
- Produces stored `ResourceRelocation` and `LockedAssignment(resource_id, destination_id)` domain values.
- Extends `ScenarioVersion` with `resource_relocations` and `locked_assignments`, both empty for legacy versions.
- Extends the concrete persistence repository with replacement collections; request validation and route mapping intentionally wait until Task 3 so no unvalidated coordinates can be persisted.

- [ ] **Step 1: Write failing persistence and compatibility tests**

Construct one stored relocation and one locked assignment in the repository test:

```python
relocation = ResourceRelocation(
    resource_id="engine-1",
    requested_longitude=-121.61,
    requested_latitude=39.75,
    snapped_longitude=-121.60,
    snapped_latitude=39.75,
    snap_distance_meters=850.0,
)
locked = LockedAssignment(
    resource_id="engine-1",
    destination_id="community-1",
)
```

Pass the values directly to `ScenarioRepository.add_version`, then assert they round-trip, a replacement version can clear them with empty tuples, and a legacy version loads empty tuples:

```python
assert version.scenario.resource_relocations == (
    ResourceRelocation(
        resource_id="engine-1",
        requested_longitude=-121.61,
        requested_latitude=39.75,
        snapped_longitude=-121.60,
        snapped_latitude=39.75,
        snap_distance_meters=850.0,
    ),
)
assert version.scenario.locked_assignments == (
    LockedAssignment("engine-1", "community-1"),
)
assert cleared.scenario.resource_relocations == ()
assert cleared.scenario.locked_assignments == ()
assert legacy.scenario.resource_relocations == ()
assert legacy.scenario.locked_assignments == ()
```

- [ ] **Step 2: Run focused tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/integration/decision/test_scenarios.py tests/integration/persistence/test_scenario_constraints.py -q -k 'relocation or locked_assignment or legacy_scenario'
```

Expected: FAIL because the domain values, tables, and repository arguments do not exist.

- [ ] **Step 3: Add the domain contracts**

Extend `backend/src/wildfireops/domain/scenarios.py`:

```python
@dataclass(frozen=True, slots=True)
class ResourceRelocation:
    resource_id: str
    requested_longitude: float
    requested_latitude: float
    snapped_longitude: float
    snapped_latitude: float
    snap_distance_meters: float


@dataclass(frozen=True, slots=True)
class LockedAssignment:
    resource_id: str
    destination_id: str


@dataclass(frozen=True, slots=True)
class ScenarioVersion:
    scenario_id: str
    version: int
    incident_snapshot_id: str
    road_closures: tuple[RoadClosure, ...]
    weather_overrides: tuple[WeatherOverride, ...]
    resource_overrides: tuple[ResourceOverride, ...]
    resource_relocations: tuple[ResourceRelocation, ...] = ()
    locked_assignments: tuple[LockedAssignment, ...] = ()
```

- [ ] **Step 4: Add the migration and ORM models**

Create two immutable child tables and assignment-source columns for later tasks. Existing rows remain compatible because child collections are empty and assignment columns default to `optimized`:

```python
revision: str = "0005_map_first_scenario_inputs"
down_revision: str | None = "0004_auditable_decisions"


def upgrade() -> None:
    op.create_table(
        "scenario_resource_relocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("requested_longitude", sa.Float(), nullable=False),
        sa.Column("requested_latitude", sa.Float(), nullable=False),
        sa.Column("snapped_longitude", sa.Float(), nullable=False),
        sa.Column("snapped_latitude", sa.Float(), nullable=False),
        sa.Column("snap_distance_meters", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "scenario_version_id",
            "resource_id",
            name="uq_scenario_relocations_version_resource",
        ),
    )
    op.create_table(
        "scenario_locked_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("destination_id", sa.String(255), nullable=False),
        sa.UniqueConstraint(
            "scenario_version_id",
            "resource_id",
            name="uq_scenario_locks_version_resource",
        ),
    )
    for table in ("recommendation_assignments", "decision_assignments"):
        op.add_column(
            table,
            sa.Column(
                "assignment_source",
                sa.String(16),
                nullable=False,
                server_default="optimized",
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_assignment_source",
            table,
            "assignment_source IN ('manual', 'optimized')",
        )
```

Implement the matching downgrade in reverse order and add `ScenarioResourceRelocationModel` and `ScenarioLockedAssignmentModel` with UUID defaults and the same constraints. Map the assignment-source columns in Task 5, when the domain assignment type gains the field.

- [ ] **Step 5: Persist and reload the new child collections**

Extend concrete `ScenarioRepository.add_version` parameters with default-empty tuples and add rows after the existing override rows:

```python
self._session.add_all(
    ScenarioResourceRelocationModel(
        scenario_version_id=version.id,
        resource_id=item.resource_id,
        requested_longitude=item.requested_longitude,
        requested_latitude=item.requested_latitude,
        snapped_longitude=item.snapped_longitude,
        snapped_latitude=item.snapped_latitude,
        snap_distance_meters=item.snap_distance_meters,
    )
    for item in resource_relocations
)
self._session.add_all(
    ScenarioLockedAssignmentModel(
        scenario_version_id=version.id,
        resource_id=item.resource_id,
        destination_id=item.destination_id,
    )
    for item in locked_assignments
)
```

Load both tables in `get_version`, order them deterministically, and pass them to `ScenarioVersion`. Baseline `create` requires no child rows and therefore returns empty collections.

- [ ] **Step 6: Run migration and persistence checks**

Run:

```bash
cd backend
uv run alembic upgrade head
uv run pytest tests/integration/decision/test_scenarios.py tests/integration/persistence/test_scenario_constraints.py -q -k 'scenario or relocation or locked_assignment'
uv run ruff check src/wildfireops/domain/scenarios.py src/wildfireops/persistence/decision_models.py src/wildfireops/persistence/scenarios.py tests/integration/decision/test_scenarios.py tests/integration/persistence/test_scenario_constraints.py
uv run mypy src
```

Expected: migration succeeds; legacy, populated, and cleared scenario round trips pass; Ruff and mypy exit 0.

- [ ] **Step 7: Commit the immutable persistence slice**

```bash
git add backend/migrations/versions/0005_map_first_scenario_inputs.py backend/src/wildfireops/domain/scenarios.py backend/src/wildfireops/persistence/decision_models.py backend/src/wildfireops/persistence/scenarios.py backend/tests/integration/decision/test_scenarios.py backend/tests/integration/persistence/test_scenario_constraints.py
git commit -m "feat: persist map planning assumptions"
```

---

### Task 2: Add Viewport-Bounded Road Reads and Human Road Labels

**Files:**
- Modify: `backend/src/wildfireops/geospatial/road_graph.py` (`RoadEdge`, `_road_edge_catalog`, bounds helpers)
- Modify: `backend/src/wildfireops/api/routes/road_graphs.py` (`get_road_edges`)
- Test: `backend/tests/unit/geospatial/test_road_graph.py`
- Test: `backend/tests/integration/api/test_decision_flow.py`

**Interfaces:**
- Consumes: existing `RoadGraph.road_edges`, exact `edgeId` reads, and search/limit behavior.
- Produces: `type Wgs84Bounds = tuple[float, float, float, float]`, `parse_wgs84_bounds(value: str) -> Wgs84Bounds`, and `road_edges_in_bounds(graph: RoadGraph, bounds: Wgs84Bounds) -> tuple[RoadEdge, ...]`.
- API: `GET /api/road-graphs/{graph_version}/edges?bbox=west,south,east,north&limit=200`; exact `edgeId` reads remain unbounded by viewport.

- [ ] **Step 1: Add failing road bounds and fallback-label unit tests**

Add focused tests that build a small graph with named, unnamed, intersecting, and nonintersecting edges:

```python
from wildfireops.geospatial.road_graph import (
    RoadGraph,
    RoadGraphInvalid,
    parse_wgs84_bounds,
    road_edges_in_bounds,
)


def test_road_catalog_uses_readable_deterministic_fallback_labels() -> None:
    graph = RoadGraph.from_graph(_graph_with_named_and_unnamed_edges())

    labels = {edge.edge_id: edge.label for edge in graph.road_edges}

    assert labels["edge-named"] == "Skyway"
    assert labels["edge-unnamed"] == "Unnamed road 2"
    assert all(edge_id not in label for edge_id, label in labels.items())


def test_viewport_reads_return_only_intersecting_edges_in_stable_order() -> None:
    graph = RoadGraph.from_graph(_graph_crossing_viewport())

    edges = road_edges_in_bounds(
        graph,
        parse_wgs84_bounds("-121.7,39.7,-121.5,39.9"),
    )

    assert [edge.edge_id for edge in edges] == ["edge-a", "edge-crossing"]


@pytest.mark.parametrize(
    "value",
    ("", "-121,39,-122,40", "-181,39,-121,40", "nan,39,-121,40"),
)
def test_wgs84_bounds_reject_invalid_values(value: str) -> None:
    with pytest.raises(RoadGraphInvalid, match="ordered WGS84 bounding box"):
        parse_wgs84_bounds(value)
```

- [ ] **Step 2: Run the unit tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py -q -k 'viewport or fallback_labels or wgs84_bounds'
```

Expected: FAIL because the bounds helpers do not exist and unnamed roads still expose raw edge IDs.

- [ ] **Step 3: Implement bounds parsing, intersection, and deterministic labels**

Add these public helpers and build labels after stable edge ordering:

```python
type Wgs84Bounds = tuple[float, float, float, float]


def parse_wgs84_bounds(value: str) -> Wgs84Bounds:
    try:
        west, south, east, north = (float(part.strip()) for part in value.split(","))
    except (TypeError, ValueError):
        raise RoadGraphInvalid("bbox must be an ordered WGS84 bounding box") from None
    if (
        not all(isfinite(item) for item in (west, south, east, north))
        or not -180 <= west < east <= 180
        or not -90 <= south < north <= 90
    ):
        raise RoadGraphInvalid("bbox must be an ordered WGS84 bounding box")
    return west, south, east, north


def road_edges_in_bounds(
    graph: RoadGraph,
    bounds: Wgs84Bounds,
) -> tuple[RoadEdge, ...]:
    viewport = shapely.box(*bounds)
    return tuple(
        edge
        for edge in graph.road_edges
        if edge.geometry is not None
        and shapely.LineString(edge.geometry).intersects(viewport)
    )
```

Replace `_road_edge_catalog` with a two-pass stable catalog so fallback ordinals do not depend on NetworkX iteration order:

```python
def _road_edge_catalog(graph: nx.MultiDiGraph) -> tuple[RoadEdge, ...]:
    rows = sorted(
        graph.edges(keys=True, data=True),
        key=lambda row: str(row[3]["edge_id"]),
    )
    return tuple(
        RoadEdge(
            edge_id=data["edge_id"],
            label=_road_edge_label(data, index),
            geometry=_road_edge_geometry(graph, origin, destination, data),
            travel_minutes=data["travel_minutes"],
            distance_meters=data["distance_meters"],
        )
        for index, (origin, destination, _, data) in enumerate(rows, start=1)
    )


def _road_edge_label(data: dict[str, object], ordinal: int) -> str:
    name = data.get("name")
    if isinstance(name, str) and (normalized := " ".join(name.split())):
        return normalized
    return f"Unnamed road {ordinal}"
```

- [ ] **Step 4: Add failing API tests for bbox semantics**

Extend `test_road_edge_reads_support_browse_search_exact_and_stable_errors` with:

```python
bounds = "-121.7,39.7,-121.5,39.9"
bounded = await client.get(
    f"/api/road-graphs/{graph_version}/edges",
    params={"bbox": bounds, "limit": 1},
)
assert bounded.status_code == 200
assert bounded.json()["total"] >= len(bounded.json()["items"])
assert len(bounded.json()["items"]) == 1

exact = await client.get(
    f"/api/road-graphs/{graph_version}/edges",
    params=[("bbox", bounds), ("edgeId", outside_edge_id)],
)
assert exact.status_code == 200
assert [item["edgeId"] for item in exact.json()["items"]] == [outside_edge_id]

invalid = await client.get(
    f"/api/road-graphs/{graph_version}/edges",
    params={"bbox": "-121,40,-122,39"},
)
assert invalid.status_code == 422
assert invalid.json()["error"]["code"] == "road_bounds_invalid"
```

- [ ] **Step 5: Extend the endpoint without changing exact-ID behavior**

Add the optional query and filter only the browse/search branch:

```python
bbox: Annotated[str | None, Query(max_length=200)] = None,
```

After the existing `edge_ids is not None` early return:

```python
try:
    catalog = (
        graph.road_edges
        if bbox is None
        else road_edges_in_bounds(graph, parse_wgs84_bounds(bbox))
    )
except RoadGraphInvalid as error:
    raise ApiError(
        status_code=422,
        code="road_bounds_invalid",
        message=str(error),
    ) from error

term = "" if q is None else q.strip().casefold()
matched = tuple(
    edge
    for edge in catalog
    if not term or term in edge.label.casefold() or term in edge.edge_id.casefold()
)
return _edge_list(matched[:limit], total=len(matched))
```

- [ ] **Step 6: Run focused backend checks**

Run:

```bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py tests/integration/api/test_decision_flow.py -q -k 'road or viewport or bounds'
uv run ruff check src/wildfireops/geospatial/road_graph.py src/wildfireops/api/routes/road_graphs.py tests/unit/geospatial/test_road_graph.py tests/integration/api/test_decision_flow.py
uv run mypy src
```

Expected: focused tests pass; Ruff and mypy exit 0.

- [ ] **Step 7: Commit the road slice**

```bash
git add backend/src/wildfireops/geospatial/road_graph.py backend/src/wildfireops/api/routes/road_graphs.py backend/tests/unit/geospatial/test_road_graph.py backend/tests/integration/api/test_decision_flow.py
git commit -m "feat: add selectable viewport road reads"
```

---

### Task 3: Validate Relocations and Locked Assignments Before Persistence

**Files:**
- Modify: `backend/src/wildfireops/config.py`
- Modify: `backend/src/wildfireops/application/commands.py`
- Modify: `backend/src/wildfireops/domain/scenarios.py`
- Modify: `backend/src/wildfireops/domain/scenario_versions.py`
- Modify: `backend/src/wildfireops/geospatial/road_graph.py`
- Create: `backend/src/wildfireops/decision/snapshot_inputs.py`
- Modify: `backend/src/wildfireops/decision/scenarios.py`
- Modify: `backend/src/wildfireops/decision/recommendations.py`
- Modify: `backend/src/wildfireops/persistence/scenarios.py`
- Modify: `backend/src/wildfireops/api/command_errors.py`
- Modify: `backend/src/wildfireops/api/schemas/scenarios.py`
- Modify: `backend/src/wildfireops/api/routes/scenarios.py`
- Create: `backend/tests/unit/decision/test_snapshot_inputs.py`
- Test: `backend/tests/unit/geospatial/test_road_graph.py`
- Test: `backend/tests/integration/decision/test_scenarios.py`
- Test: `backend/tests/integration/api/test_decision_flow.py`
- Test: `backend/tests/unit/test_risk_settings.py`

**Interfaces:**
- Adds request-only `ResourceRelocationRequest(resource_id, longitude, latitude)`.
- Extends `PinnedIncidentSnapshot` with the pinned `asset_state` and `resource_state` needed for semantic validation.
- Adds `RoadNodeMatch(node, longitude, latitude, distance_meters)` and `nearest_road_node_match(...)`; keeps `nearest_road_node(...)` as a compatibility wrapper.
- Adds settings `scenario_relocation_max_snap_meters=5000.0` and `scenario_locked_assignment_max_response_minutes=30`.
- New scenario fields use replacement semantics: `None` inherits the preceding version, `()` deliberately clears it.
- API input uses requested coordinates only; the response exposes requested and snapped coordinates plus snap distance.
- New API collections are capped at 500 items and are also rejected when they exceed the pinned snapshot’s resource count before any snapping/routing loop.
- `ScenarioValidationError.details` carries snake_case domain fields for field, constraint, resource/destination IDs, numeric limits, and technical detail; `command_api_error` converts those known keys to camelCase JSON while the safe top-level message remains label-neutral.

- [ ] **Step 1: Write failing nearest-node distance and configuration tests**

Add a deterministic geodesic match test and settings validation:

```python
def test_nearest_road_node_match_returns_coordinate_and_geodesic_distance() -> None:
    graph = RoadGraph.from_graph(_two_node_graph())

    match = nearest_road_node_match(graph, longitude=-121.6005, latitude=39.75)

    assert match.node == "west"
    assert match.longitude == pytest.approx(-121.60)
    assert match.latitude == pytest.approx(39.75)
    assert match.distance_meters == pytest.approx(42.7, abs=1.0)
    assert nearest_road_node(graph, -121.6005, 39.75) == "west"


@pytest.mark.parametrize("value", (0, -1, float("inf"), True))
def test_relocation_snap_distance_must_be_finite_and_positive(value: object) -> None:
    with pytest.raises(ValueError, match="relocation snap distance"):
        Settings(scenario_relocation_max_snap_meters=value)
```

- [ ] **Step 2: Write failing service tests for every semantic rejection**

In `test_scenarios.py`, add a pinned snapshot with one available engine and one destination. Add one focused `ScenarioService.add_version(...)` test for each request/detail pair below; use the real domain request values rather than a generic mutation test wrapper. Assert the public exception message is label-neutral and the exact fragment is in `error.details["technical_message"]`:

| Test | Exact technical-detail fragment |
|---|---|
| duplicate relocation resource | `duplicate resource relocation: engine-1` |
| nonfinite relocation | `resource relocation engine-1 coordinates must be finite` |
| relocation outside planning bounds | `resource relocation engine-1 is outside the planning region` |
| relocation beyond snap limit | `resource relocation engine-1 is more than 5000 meters from a routable road` |
| unknown relocated resource | `resource relocation is not in pinned snapshot: missing` |
| duplicate locked resource | `duplicate locked assignment resource: engine-1` |
| unknown locked resource | `locked assignment resource is not in pinned snapshot: missing` |
| unknown locked destination | `locked assignment destination is not in pinned snapshot: missing` |
| unavailable locked resource | `locked assignment engine-1 uses an unavailable resource` |
| capability mismatch | `locked assignment engine-1 cannot satisfy capability medical` |
| capacity mismatch | `locked assignment engine-1 capacity is below destination demand` |
| closure makes route unreachable | `locked assignment engine-1 cannot reach community-1` |
| response limit exceeded | `locked assignment engine-1 exceeds the 30 minute response limit` |

Also assert that valid requested coordinates are snapped and persisted, valid locks persist, observed `resource_state` geometry is byte-for-byte unchanged, omitted fields inherit, empty tuples clear, collection order is canonical, and idempotency conflicts when either new payload changes.

Add a 501-item API request assertion and a service request with more relocation/lock rows than pinned resources. The API returns 422 before service work for the hard cap; the service returns `scenario_invalid` before calling `nearest_road_node_match` or `compute_route` for the pinned-count case.

Use named tests rather than hiding the setup in one opaque parameterization; share only the pinned-snapshot fixture and an assertion helper:

```python
def assert_scenario_detail(
    error: ScenarioValidationError,
    *,
    constraint: str,
    technical_fragment: str,
) -> None:
    assert str(error) == "Scenario planning inputs are invalid"
    assert error.details["constraint"] == constraint
    assert technical_fragment in error.details["technical_message"]


async def test_add_version_rejects_unreachable_locked_assignment(
    scenario_service: ScenarioService,
) -> None:
    with pytest.raises(ScenarioValidationError) as raised:
        await scenario_service.add_version(
            **version_request(
                locked_assignments=(
                    LockedAssignment("engine-1", "community-1"),
                ),
                road_closures=(RoadClosure("only-access-road"),),
            )
        )
    assert_scenario_detail(
        raised.value,
        constraint="reachability",
        technical_fragment="engine-1 cannot reach community-1",
    )
```

- [ ] **Step 3: Write failing API contract tests**

POST a version using camelCase JSON:

```python
response = await client.post(
    f"/api/scenarios/{scenario_id}/versions",
    headers={"Idempotency-Key": "map-draft-1"},
    json={
        "resourceRelocations": [
            {
                "resourceId": resource_id,
                "longitude": -121.61,
                "latitude": 39.75,
            }
        ],
        "lockedAssignments": [
            {"resourceId": resource_id, "destinationId": destination_id}
        ],
    },
)

assert response.status_code == 201
body = response.json()
assert body["resourceRelocations"][0]["resourceId"] == resource_id
assert body["resourceRelocations"][0]["requestedLongitude"] == -121.61
assert body["resourceRelocations"][0]["snapDistanceMeters"] <= 5000
assert body["lockedAssignments"] == [
    {"resourceId": resource_id, "destinationId": destination_id}
]
```

Add one invalid relocation and one invalid lock request; assert status 422, `scenario_invalid`, a label-neutral message, and structured `details` such as `{ field, constraint, resourceId, destinationId, limit, technicalMessage }`. Assert snake_case keys such as `resource_id` and `technical_message` never cross the HTTP boundary. Preserve the existing old request body test unchanged to prove backward compatibility.

- [ ] **Step 4: Run the focused tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py tests/unit/decision/test_snapshot_inputs.py tests/unit/test_risk_settings.py tests/integration/decision/test_scenarios.py tests/integration/api/test_decision_flow.py -q -k 'nearest_road_node_match or snapshot_inputs or relocation or locked_assignment or legacy_request'
```

Expected: FAIL because configuration, request types, semantic validation, and API mapping are absent.

- [ ] **Step 5: Add distance-aware road snapping without changing callers**

Use the already installed `pyproj` package:

```python
_WGS84 = Geod(ellps="WGS84")


@dataclass(frozen=True, slots=True)
class RoadNodeMatch:
    node: Hashable
    longitude: float
    latitude: float
    distance_meters: float


def nearest_road_node_match(
    graph: RoadGraph,
    longitude: float,
    latitude: float,
) -> RoadNodeMatch:
    node = _nearest_node_id(graph, longitude, latitude)
    data = graph._graph.nodes[node]
    snapped_longitude = float(data["x"])
    snapped_latitude = float(data["y"])
    _, _, distance = _WGS84.inv(
        longitude,
        latitude,
        snapped_longitude,
        snapped_latitude,
    )
    return RoadNodeMatch(
        node=node,
        longitude=snapped_longitude,
        latitude=snapped_latitude,
        distance_meters=float(distance),
    )


def nearest_road_node(graph: RoadGraph, longitude: float, latitude: float) -> Hashable:
    return nearest_road_node_match(graph, longitude, latitude).node
```

Keep the current deterministic nearest-node tie behavior inside `_nearest_node_id`.

- [ ] **Step 6: Centralize pinned resource and demand parsing**

Create `decision/snapshot_inputs.py` with `SnapshotInputsInvalid`, `parse_resource_units(resource_state: object, overrides: Iterable[tuple[str, bool]]) -> tuple[ResourceUnit, ...]`, `parse_snapshot_demands(asset_state: object, weighted_risk: float) -> tuple[DemandPoint, ...]`, and a shared demand-metadata helper. Move the current resource parsing rules out of `decision/recommendations.py`; have recommendation generation translate `SnapshotInputsInvalid` to `RecommendationInputsInvalid`. Scenario validation translates it to `ScenarioValidationError` with structured details.

Both paths must use identical rules for resource availability, capabilities, capacity, geometry, destination capability/capacity demand, and duplicate IDs. Keep recommendation-only source-pin/exposure/risk validation in `recommendations.py`; do not create a second recommendation engine. Add unit tests that feed the same malformed resource/demand state through both callers and assert both reject it.

Move the current `_resources` body to `parse_resource_units` and the current `_demands` body plus demand-metadata extraction to `parse_snapshot_demands`; replace only the exception type and public argument shapes. Keep caller-specific exception translation at each boundary:

```python
class SnapshotInputsInvalid(ValueError):
    def __init__(self, message: str, *, details: Mapping[str, JsonValue]) -> None:
        super().__init__(message)
        self.details = MappingProxyType(dict(details))


try:
    resources = parse_resource_units(
        context.resource_state,
        context.resource_overrides,
    )
    demands = parse_snapshot_demands(context.asset_state, risk.score)
except SnapshotInputsInvalid as error:
    raise RecommendationInputsInvalid(str(error)) from error
```

In the scenario service, catch the same exception and retain its structured details in `ScenarioValidationError`. Delete the old recommendation-private `_resources` and `_demands` after both callers use the shared functions.

- [ ] **Step 7: Expose validated snapshot inputs to the scenario service**

Extend `PinnedIncidentSnapshot`:

```python
@dataclass(frozen=True, slots=True)
class PinnedIncidentSnapshot:
    id: UUID
    resource_ids: frozenset[str]
    asset_state: object
    resource_state: object
```

Have `_snapshot` retain the persisted JSON values after its existing resource-ID validation. Feed those values through the canonical Task 3 parsers and convert parser failures to structured scenario-validation details. Do not mutate the JSON values.

Call `parse_snapshot_demands(snapshot.asset_state, 0.0)` in scenario validation because only capability, capacity, identity, and geometry are needed there; recommendation generation passes the computed `risk.score`. Weighted risk must never affect whether a manual pair is structurally valid.

- [ ] **Step 8: Add configuration and inject it through the existing provider**

In `Settings`, add finite-positive validation for `scenario_relocation_max_snap_meters` and nonnegative-integer validation for `scenario_locked_assignment_max_response_minutes`. Store parsed `firms_bbox` and the two limits on `ScenarioService`:

```python
yield ScenarioService(
    graphs=self._graphs(),
    repository=ScenarioRepository(session),
    planning_bounds=parse_wgs84_bounds(self._settings.firms_bbox),
    relocation_max_snap_meters=self._settings.scenario_relocation_max_snap_meters,
    locked_assignment_max_response_minutes=(
        self._settings.scenario_locked_assignment_max_response_minutes
    ),
)
```

Retain `self._settings = settings` in `CommandServiceProvider`. Unit-test service constructors with explicit values so behavior is not coupled to environment variables.

- [ ] **Step 9: Normalize, validate, hash, and persist new inputs**

Add `ResourceRelocationRequest` to `domain/scenarios.py`. Extend the service protocol and `add_version` signature with nullable replacement tuples. Normalize by resource ID, reject repeated resources in either collection, and include both normalized collections in `_request_hash` before claiming idempotency.

After loading the previous version, pinned graph, and snapshot:

1. derive effective inherited/replacement values;
2. reject relocation/lock counts above the pinned resource count before geospatial work;
3. reject closure IDs outside `graph.edge_ids` and resource-override IDs outside `snapshot.resource_ids`, preserving the current duplicate/replacement checks;
4. validate each relocation is finite and inside `planning_bounds`, snap with `nearest_road_node_match`, reject beyond the configured distance, and build stored `ResourceRelocation` values;
5. derive effective resource availability and origins after overrides/relocations;
6. validate each locked resource and destination belongs to the snapshot, the resource is available, capability and capacity meet demand, and `compute_route(...)` through the pinned graph and effective closures is reachable within the configured limit; and
7. call the concrete repository once with all five replacement collections.

Do not write a scenario version until every item passes. The relocation collection uses validated stored values; an omitted relocation field inherits the preceding stored values without re-snapping.

Keep replacement resolution and validation explicit in `add_version`:

```python
effective_relocations = (
    previous.scenario.resource_relocations
    if normalized_relocations is None
    else await self._validated_relocations(
        normalized_relocations,
        snapshot=snapshot,
        graph=graph,
    )
)
effective_locks = (
    previous.scenario.locked_assignments
    if normalized_locks is None
    else normalized_locks
)
resources = parse_resource_units(
    snapshot.resource_state,
    tuple((item.resource_id, item.available) for item in effective_resources),
)
demands = parse_snapshot_demands(snapshot.asset_state, 0.0)
await self._validate_locked_assignments(
    effective_locks,
    resources=resources,
    demands=demands,
    graph=graph,
    closures=effective_roads,
    relocations=effective_relocations,
)
stored = await self._repository.add_version(
    previous=previous,
    created_by=normalized_author,
    road_closures=effective_roads,
    weather_overrides=effective_weather,
    resource_overrides=effective_resources,
    resource_relocations=effective_relocations,
    locked_assignments=effective_locks,
)
```

- [ ] **Step 10: Add input-only and output-only API schemas**

```python
class ResourceRelocationInput(ApiModel):
    resource_id: str
    longitude: float
    latitude: float


class ResourceRelocationResponse(ApiModel):
    resource_id: str
    requested_longitude: float
    requested_latitude: float
    snapped_longitude: float
    snapped_latitude: float
    snap_distance_meters: float


class LockedAssignmentInput(ApiModel):
    resource_id: str
    destination_id: str
```

Add nullable `resource_relocations` and `locked_assignments` to `ScenarioVersionCreateRequest` with `Field(default=None, max_length=500)`, and nonnullable tuples to `ScenarioVersionResponse`. Map API inputs to domain request values and serialize only the validated stored relocation. Do not let clients supply snapped values.

Give `ScenarioValidationError` a read-only details mapping and pass it through `command_api_error`. Keep domain/service tests on snake_case details, then explicitly map the known keys (`resource_id`, `destination_id`, `technical_message`) to (`resourceId`, `destinationId`, `technicalMessage`) in the API error body. Use a generic safe message such as “Scenario planning inputs are invalid” plus structured details; preserve an exact technical message only inside details for the drawer. Add an API assertion for that mapping rather than introducing a generic recursive serializer.

- [ ] **Step 11: Run focused backend checks**

Run:

```bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py tests/unit/decision/test_snapshot_inputs.py tests/unit/test_risk_settings.py tests/integration/decision/test_scenarios.py tests/integration/api/test_decision_flow.py -q -k 'nearest_road_node_match or snapshot_inputs or relocation or locked_assignment or legacy_request'
uv run ruff check src/wildfireops/config.py src/wildfireops/application/commands.py src/wildfireops/domain/scenarios.py src/wildfireops/domain/scenario_versions.py src/wildfireops/geospatial/road_graph.py src/wildfireops/decision/snapshot_inputs.py src/wildfireops/decision/scenarios.py src/wildfireops/decision/recommendations.py src/wildfireops/persistence/scenarios.py src/wildfireops/api/command_errors.py src/wildfireops/api/schemas/scenarios.py src/wildfireops/api/routes/scenarios.py tests/unit/geospatial/test_road_graph.py tests/unit/decision/test_snapshot_inputs.py tests/unit/test_risk_settings.py tests/integration/decision/test_scenarios.py tests/integration/api/test_decision_flow.py
uv run mypy src
```

Expected: all focused tests pass; Ruff and mypy exit 0.

- [ ] **Step 12: Commit the validation slice**

```bash
git add backend/src/wildfireops/config.py backend/src/wildfireops/application/commands.py backend/src/wildfireops/domain/scenarios.py backend/src/wildfireops/domain/scenario_versions.py backend/src/wildfireops/geospatial/road_graph.py backend/src/wildfireops/decision/snapshot_inputs.py backend/src/wildfireops/decision/scenarios.py backend/src/wildfireops/decision/recommendations.py backend/src/wildfireops/persistence/scenarios.py backend/src/wildfireops/api/command_errors.py backend/src/wildfireops/api/schemas/scenarios.py backend/src/wildfireops/api/routes/scenarios.py backend/tests/unit/geospatial/test_road_graph.py backend/tests/unit/decision/test_snapshot_inputs.py backend/tests/unit/test_risk_settings.py backend/tests/integration/decision/test_scenarios.py backend/tests/integration/api/test_decision_flow.py
git commit -m "feat: validate map planning inputs"
```

---

### Task 4: Preserve Manual Assignments in the Optimizer

**Files:**
- Modify: `backend/src/wildfireops/decision/optimizer.py`
- Test: `backend/tests/unit/decision/test_optimizer.py`
- Test: `backend/tests/unit/decision/test_optimizer_properties.py`

**Interfaces:**
- Adds `AssignmentSource = Literal["manual", "optimized"]`.
- Extends `OptimizationRequest` with `locked_assignments: tuple[LockedAssignment, ...] = ()`.
- Extends optimizer `Assignment` with `assignment_source`.
- A locked pair must reference a known resource, destination, and supplied candidate route. The scenario service remains the authority for its operational validity.

- [ ] **Step 1: Write failing locked-allocation examples**

Add tests proving a manually locked pair is retained even when the unconstrained optimum chooses another pair, and the remaining resources are still optimized:

```python
result = solve_allocation(
    OptimizationRequest(
        resources=(engine_a, engine_b),
        demands=(community_a, community_b),
        routes=routes_where_engine_a_to_b_is_cheapest,
        max_response_minutes=30,
        locked_assignments=(
            LockedAssignment(engine_a.resource_id, community_a.destination_id),
        ),
    )
)

assert [
    (item.resource_id, item.destination_id, item.assignment_source)
    for item in result.assignments
] == [
    (engine_a.resource_id, community_a.destination_id, "manual"),
    (engine_b.resource_id, community_b.destination_id, "optimized"),
]
```

Also add focused failures for duplicate locked resources, unknown resources, unknown destinations, and a locked pair without a candidate route.

- [ ] **Step 2: Extend the property suite**

Generate zero or more valid unique locked pairs from the same resource/demand/route fixture. Preserve all existing invariants and add:

```python
manual_pairs = {
    (item.resource_id, item.destination_id)
    for item in result.assignments
    if item.assignment_source == "manual"
}
assert manual_pairs == {
    (item.resource_id, item.destination_id)
    for item in request.locked_assignments
}
assert len({item.resource_id for item in result.assignments}) == len(result.assignments)
```

- [ ] **Step 3: Run optimizer tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_optimizer.py tests/unit/decision/test_optimizer_properties.py -q -k 'locked or manual or invariants'
```

Expected: FAIL because the request and result do not carry locked/manual semantics.

- [ ] **Step 4: Canonicalize structural lock inputs**

Sort locked pairs by `(resource_id, destination_id)`. Reject more than one lock for a resource, pairs outside the request resource/destination sets, and pairs missing from `routes`. Do not re-run scenario-level availability, capability, capacity, closure, or response-limit validation here; Task 3 validates those inputs against the immutable pinned scenario before they are stored.

```python
locked_assignments = tuple(
    sorted(
        request.locked_assignments,
        key=lambda item: (item.resource_id, item.destination_id),
    )
)
locked_resources = [item.resource_id for item in locked_assignments]
if len(set(locked_resources)) != len(locked_resources):
    raise ValueError("locked resources must be unique")
for item in locked_assignments:
    pair = (item.resource_id, item.destination_id)
    if item.resource_id not in resources_by_id:
        raise ValueError("locked resource is unknown")
    if item.destination_id not in demands_by_id:
        raise ValueError("locked destination is unknown")
    if pair not in routes_by_pair:
        raise ValueError("locked assignment has no candidate route")
```

- [ ] **Step 5: Force locked variables and mark assignment provenance**

When building eligible routes, always retain a structurally valid locked candidate. Apply the existing eligibility function only to unlocked candidates. After variables are created:

```python
locked_pairs = {
    (item.resource_id, item.destination_id) for item in locked_assignments
}
for pair in locked_pairs:
    model.add(assigned[pair] == 1)
```

The existing per-resource `<= 1` constraint prevents any second assignment for that resource. Construct results with:

```python
assignment_source="manual" if pair in locked_pairs else "optimized"
```

Keep deterministic ordering by resource ID then destination ID. Objective, coverage, travel cost, uncovered demand, unassigned resources, and binding explanations continue to include the combined result.

- [ ] **Step 6: Run optimizer checks**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_optimizer.py tests/unit/decision/test_optimizer_properties.py -q
uv run ruff check src/wildfireops/decision/optimizer.py tests/unit/decision/test_optimizer.py tests/unit/decision/test_optimizer_properties.py
uv run mypy src
```

Expected: example and property tests pass; Ruff and mypy exit 0.

- [ ] **Step 7: Commit the optimizer slice**

```bash
git add backend/src/wildfireops/decision/optimizer.py backend/tests/unit/decision/test_optimizer.py backend/tests/unit/decision/test_optimizer_properties.py
git commit -m "feat: preserve manual optimizer assignments"
```

---

### Task 5: Route From Relocations and Carry Planning Provenance Through Audit

**Files:**
- Modify: `backend/src/wildfireops/decision/recommendations.py`
- Modify: `backend/src/wildfireops/persistence/recommendations.py`
- Modify: `backend/src/wildfireops/persistence/decision_models.py`
- Modify: `backend/src/wildfireops/decision/commands.py`
- Modify: `backend/src/wildfireops/persistence/decisions.py`
- Modify: `backend/src/wildfireops/api/schemas/scenarios.py`
- Modify: `backend/src/wildfireops/api/routes/scenarios.py`
- Test: `backend/tests/unit/decision/test_commands.py`
- Test: `backend/tests/integration/api/test_decision_flow.py`
- Test: `backend/tests/integration/decision/test_audit_transaction.py`
- Test: `backend/tests/integration/persistence/test_scenario_constraints.py`

**Interfaces:**
- Extends `RecommendationContext` with stored relocations and locked assignments.
- Extends `StoredRecommendationAssignment` and API assignment responses with `assignment_source`.
- Extends recommendation outcome responses with deterministic `unreachable_route_pairs` derived from stored candidate routes, so the map can connect named resources and destinations without exposing the full candidate table.
- Adds `technical_evidence` to `RecommendationResponse`, populated from the immutable stored `request_inputs` for the optional drawer only.
- Recommendation input/staleness payloads include the immutable scenario relocation and lock assumptions.
- Decision edits must retain every `manual` pair unchanged; edited unlocked pairs are `optimized`.
- Decision assignment rows and audit inputs retain assignment provenance and scenario assumptions.

- [ ] **Step 1: Write failing recommendation integration tests**

Extend the decision-flow fixture with a resource whose observed origin has a long route and whose stored relocation snaps near a destination. Generate a recommendation and assert:

```python
assignment = next(
    item for item in body["assignments"] if item["resourceId"] == resource_id
)
assert assignment["destinationId"] == destination_id
assert assignment["assignmentSource"] == "manual"
assert assignment["route"]["travelMinutes"] < observed_origin_minutes

inputs = stored_recommendation.request_inputs
assert inputs["overlays"]["resource_relocations"][0]["resource_id"] == resource_id
assert inputs["overlays"]["locked_assignments"] == [
    {"resource_id": resource_id, "destination_id": destination_id}
]
assert body["technicalEvidence"]["limits"]["maxResponseMinutes"] == 30
assert body["technicalEvidence"]["candidateRoutes"]
```

Add a companion legacy scenario assertion: observed origin is used, all assignments report `optimized`, and both new overlay arrays are empty.

For a fixture where every candidate route to one destination is unreachable, assert `outcome.unreachableRoutePairs` contains the sorted resource/destination pairs and `unreachableDestinationIds` retains the destination summary.

- [ ] **Step 2: Write failing decision and audit tests**

Cover these cases:

1. approve preserves the manual assignment source in `decision_assignments` and the decision response;
2. edit may change unlocked pairs but rejects removal or reassignment of a manual pair with `decision_invalid`;
3. audit `inputs.scenarioAssumptions` includes closures, weather, availability, relocations, and locks;
4. audit `beforeState.proposedPairs` and `afterState.finalPairs` include `assignmentSource`; and
5. transaction rollback still removes the decision, assignment, and audit rows together.

Use an explicit rejection assertion:

```python
with pytest.raises(
    DecisionValidationError,
    match="manual assignment must remain unchanged: engine-1 -> community-1",
):
    _validate_decision(recommendation, edit_without_manual_pair)
```

- [ ] **Step 3: Run focused tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_commands.py tests/integration/api/test_decision_flow.py tests/integration/decision/test_audit_transaction.py tests/integration/persistence/test_scenario_constraints.py -q -k 'relocation or manual or assignment_source or scenario_assumptions'
```

Expected: FAIL because recommendation context, stored assignments, decision validation, and audit payloads omit the new fields.

- [ ] **Step 4: Load scenario assumptions into recommendation context**

In `RecommendationRepository.load_context`, query `ScenarioResourceRelocationModel` and `ScenarioLockedAssignmentModel`, order them deterministically, and populate:

```python
resource_relocations: tuple[ResourceRelocation, ...]
locked_assignments: tuple[LockedAssignment, ...]
```

Include both arrays in `_staleness_payload`, `recommendation_input_version`, and `request_inputs["overlays"]` so retries and stale checks are tied to the exact immutable planning inputs.

- [ ] **Step 5: Use relocated routing origins and pass locks to CP-SAT**

Derive resource nodes with stored snapped coordinates when present:

```python
relocations_by_resource = {
    item.resource_id: item for item in context.resource_relocations
}


def resource_node(resource: ResourceUnit) -> Hashable:
    relocation = relocations_by_resource.get(resource.resource_id)
    longitude = (
        resource.longitude if relocation is None else relocation.snapped_longitude
    )
    latitude = (
        resource.latitude if relocation is None else relocation.snapped_latitude
    )
    return nearest_road_node(graph, longitude, latitude)


resource_nodes = {
    resource.resource_id: resource_node(resource) for resource in resources
}
```

Pass `context.locked_assignments` to `OptimizationRequest`. Convert optimizer assignments to `StoredRecommendationAssignment` while copying `assignment_source`.

- [ ] **Step 6: Persist and serialize assignment provenance**

Map the migration columns created in Task 1 on `RecommendationAssignmentModel` and `DecisionAssignmentModel`. Read and write `assignment_source` in both repositories. Add `assignment_source: Literal["manual", "optimized"]` to `RecommendationAssignmentResponse` and populate it in recommendation and decision responses.

Add `technical_evidence: dict[str, JsonValue]` to `RecommendationResponse` and recursively camel-case the validated stored `request_inputs` with the same JSON-key behavior used by audit responses. Do not copy it into the compact dock; only `RecommendationPanel` inside Details & evidence renders it under a collapsed technical disclosure.

Add `UnreachableRoutePairResponse(resource_id, destination_id)` and derive it in `recommendation_outcome(...)` from candidate routes whose status is `unreachable`, filtered to destinations for which every candidate is unreachable and sorted by `(destination_id, resource_id)`. This is compact operational exception data; the full candidate route payload remains technical evidence.

```diff
 class RecommendationAssignmentResponse(ApiModel):
+    assignment_source: Literal["manual", "optimized"]

+class UnreachableRoutePairResponse(ApiModel):
+    resource_id: str
+    destination_id: str

 class RecommendationResponse(ApiModel):
+    technical_evidence: dict[str, JsonValue]
```

- [ ] **Step 7: Protect manual pairs during human edits**

Before `_edited_assignments`, derive manual proposal pairs. Reject an edit unless every manual resource appears at the identical destination. When rebuilding edited assignments, copy the original manual assignment object for manual pairs and mark every other validated pair `optimized`. This preserves the already validated manual route and avoids reinterpreting it against the recommendation request limit.

```python
manual_by_resource = {
    item.resource_id: item
    for item in recommendation.assignments
    if item.assignment_source == "manual"
}
edited_by_resource = {item.resource_id: item for item in requested_assignments}
for resource_id, original in manual_by_resource.items():
    edited = edited_by_resource.get(resource_id)
    if edited is None or edited.destination_id != original.destination_id:
        raise DecisionValidationError(
            "manual assignment must remain unchanged: "
            f"{resource_id} -> {original.destination_id}"
        )
```

- [ ] **Step 8: Append complete scenario assumptions to audit**

In `DecisionRepository.append_audit_event`, copy the already frozen recommendation overlay payload:

```python
"scenario_assumptions": recommendation.request_inputs.get("overlays", {}),
```

Serialize proposed and final pairs as objects with `resource_id`, `destination_id`, and `assignment_source`, not two-element arrays. Keep exact stable IDs here because audit is a technical evidence surface.

- [ ] **Step 9: Run focused backend checks**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_commands.py tests/integration/api/test_decision_flow.py tests/integration/decision/test_audit_transaction.py tests/integration/persistence/test_scenario_constraints.py -q -k 'recommendation or relocation or manual or assignment_source or scenario_assumptions'
uv run ruff check src/wildfireops/decision/recommendations.py src/wildfireops/persistence/recommendations.py src/wildfireops/persistence/decision_models.py src/wildfireops/decision/commands.py src/wildfireops/persistence/decisions.py src/wildfireops/api/schemas/scenarios.py src/wildfireops/api/routes/scenarios.py tests/unit/decision/test_commands.py tests/integration/api/test_decision_flow.py tests/integration/decision/test_audit_transaction.py tests/integration/persistence/test_scenario_constraints.py
uv run mypy src
```

Expected: recommendation, decision, audit, rollback, lint, and type checks pass.

- [ ] **Step 10: Commit the recommendation-to-audit slice**

```bash
git add backend/src/wildfireops/decision/recommendations.py backend/src/wildfireops/persistence/recommendations.py backend/src/wildfireops/persistence/decision_models.py backend/src/wildfireops/decision/commands.py backend/src/wildfireops/persistence/decisions.py backend/src/wildfireops/api/schemas/scenarios.py backend/src/wildfireops/api/routes/scenarios.py backend/tests/unit/decision/test_commands.py backend/tests/integration/api/test_decision_flow.py backend/tests/integration/decision/test_audit_transaction.py backend/tests/integration/persistence/test_scenario_constraints.py
git commit -m "feat: carry map planning provenance through audit"
```

---

### Task 6: Add Deterministic Human-Readable Resource Labels

**Files:**
- Modify: `backend/src/wildfireops/application/read_models.py`
- Modify: `backend/src/wildfireops/persistence/read_queries.py`
- Modify: `backend/src/wildfireops/api/schemas/incidents.py`
- Modify: `backend/src/wildfireops/api/mappers/incidents.py`
- Test: `backend/tests/integration/api/test_incidents.py`
- Test: `backend/tests/integration/replay/test_park_fire_golden.py`

**Interfaces:**
- Adds `display_label` / `displayLabel` to `SimulatedResourceReadModel` and `SimulatedResourceResponse` without replacing `resource_id`.
- Label priority: nonblank `raw_metadata.display_name` or `raw_metadata.name`; otherwise type plus nearest named exposed asset within 5,000 meters; otherwise deterministic type ordinal ordered by resource ID.
- Labels describe only known type/location data and never imply real agency ownership.

- [ ] **Step 1: Write failing API and replay label tests**

For Park Fire, assert the incident response contains human labels and still carries stable IDs:

```python
resources = {
    item["resourceId"]: item for item in response.json()["simulatedResources"]
}
assert resources["sim-engine-butte-meadows"]["displayLabel"] == (
    "Engine — Butte Meadows CDP"
)
assert resources["sim-engine-butte-meadows"]["resourceId"] == (
    "sim-engine-butte-meadows"
)
```

Add fixture-level cases for source-provided `display_name`, equidistant assets (asset name then ID breaks ties), no nearby asset (`Engine unit 2`), and shuffled resource input producing identical labels.

- [ ] **Step 2: Run focused tests and verify the red state**

Run:

```bash
cd backend
uv run pytest tests/integration/api/test_incidents.py tests/integration/replay/test_park_fire_golden.py -q -k 'resource_label or display_label or park_fire'
```

Expected: FAIL because the read model and response do not expose a label.

- [ ] **Step 3: Derive labels while building the incident read model**

In `get_incident`, build assets once, then pass them into `_simulated_resources`. Parse the source label before freezing metadata. For fallback labels:

1. sort resources by `(resource_type.casefold(), resource_id)`;
2. compute WGS84 distance to named assets with `pyproj.Geod`;
3. choose the closest asset within 5,000 meters, breaking equal-distance ties by normalized asset name then asset ID; and
4. if none is close, count the resource’s 1-based ordinal among the same normalized type.

Format types with spaces and title case, e.g. `water_tender` → `Water Tender`. Do not render the raw ID inside `display_label`.

```python
def _resource_display_label(
    *,
    raw_metadata: Mapping[str, object],
    resource_type: str,
    nearby_asset_name: str | None,
    type_ordinal: int,
) -> str:
    for key in ("display_name", "name"):
        value = raw_metadata.get(key)
        if isinstance(value, str) and (normalized := " ".join(value.split())):
            return normalized
    kind = resource_type.replace("_", " ").title()
    if nearby_asset_name is not None:
        return f"{kind} — {nearby_asset_name}"
    return f"{kind} unit {type_ordinal}"
```

- [ ] **Step 4: Map the label through the existing API**

Add `display_label: str` to the read model and response schema, and map it in `_resource`. Do not remove or rename the exact ID fields used by commands and audit.

```python
return SimulatedResourceResponse(
    resource_id=model.resource_id,
    display_label=model.display_label,
    resource_type=model.resource_type,
    status=model.status,
    available=model.available,
    capabilities=model.capabilities,
    capacity=model.capacity,
    geometry=_object(model.geometry),
)
```

- [ ] **Step 5: Run focused backend checks**

Run:

```bash
cd backend
uv run pytest tests/integration/api/test_incidents.py tests/integration/replay/test_park_fire_golden.py -q
uv run ruff check src/wildfireops/application/read_models.py src/wildfireops/persistence/read_queries.py src/wildfireops/api/schemas/incidents.py src/wildfireops/api/mappers/incidents.py tests/integration/api/test_incidents.py tests/integration/replay/test_park_fire_golden.py
uv run mypy src
```

Expected: labels are deterministic; tests, Ruff, and mypy pass.

- [ ] **Step 6: Commit the labeling slice**

```bash
git add backend/src/wildfireops/application/read_models.py backend/src/wildfireops/persistence/read_queries.py backend/src/wildfireops/api/schemas/incidents.py backend/src/wildfireops/api/mappers/incidents.py backend/tests/integration/api/test_incidents.py backend/tests/integration/replay/test_park_fire_golden.py
git commit -m "feat: label simulated resources clearly"
```

---

### Task 7: Extend Frontend API Contracts for Map Planning

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/hooks.ts`
- Modify: `frontend/src/api/types.test.ts`
- Modify: `frontend/src/api/client.test.ts`
- Modify: `frontend/src/api/hooks.test.tsx`
- Modify: `frontend/src/test/fixtures.ts`
- Modify: `frontend/src/test/server.ts`

**Interfaces:**
- Adds frontend resource `displayLabel`, scenario relocation and lock schemas/types, and assignment source.
- Adds `unreachableRoutePairs` plus `technicalEvidence` to the recommendation schema; technical evidence remains a collapsed drawer-only object.
- Extends `ScenarioVersionCreateRequest` with nullable `resourceRelocations` and `lockedAssignments`.
- Exports `Wgs84Bounds = readonly [number, number, number, number]` and extends `RoadEdgeQuery` with `bbox?: Wgs84Bounds`.
- Includes `bbox` in the road query key and request URL so TanStack Query cancels/ignores superseded viewport reads normally; `useRoadEdges` gains an optional `enabled` argument so no unbounded initial browse occurs before the first map bounds event.
- Updates `useExactRoadEdges` to batch sorted unique recommendation/closure IDs into requests of at most 200 and merge their data/error/loading state; exact route geometry is never sourced from a truncated bbox browse. Until Task 11 removes the old caller, it preserves the current `{ query, requestedEdgeIds, queriedEdgeIds, omittedEdgeIds }` facade, with all valid IDs queried and `omittedEdgeIds` always empty.

- [ ] **Step 1: Write failing schema tests for every new response field**

Add valid and invalid parsing cases for:

```typescript
const relocation = {
  resourceId: "sim-engine-1",
  requestedLongitude: -121.61,
  requestedLatitude: 39.75,
  snappedLongitude: -121.60,
  snappedLatitude: 39.75,
  snapDistanceMeters: 850,
};

expect(scenarioVersionSchema.parse({
  ...scenarioVersionFixture,
  resourceRelocations: [relocation],
  lockedAssignments: [
    { resourceId: "sim-engine-1", destinationId: "community-1" },
  ],
}).resourceRelocations).toEqual([relocation]);
expect(recommendationAssignmentSchema.parse({
  ...assignmentFixture,
  assignmentSource: "manual",
}).assignmentSource).toBe("manual");
```

Reject nonfinite relocation coordinates, negative snap distance, unknown assignment source, and a simulated resource without nonblank `displayLabel`.
Add `unreachableRoutePairs` to recommendation outcome fixtures and reject blank resource/destination IDs. Assert `technicalEvidence` parses resources, demands, candidate routes, limits, overlays, and binding constraints as a `jsonObjectSchema`, and reject a missing/nonobject field.

- [ ] **Step 2: Write failing client and hook tests for bbox behavior**

Call:

```typescript
await apiClient.listRoadEdges("park-fire-v1", {
  bbox: [-121.7, 39.7, -121.5, 39.9],
  limit: 200,
});
```

Assert the request contains one `bbox=-121.7%2C39.7%2C-121.5%2C39.9` parameter. Assert `queryKeys.roadGraphs.edges` differs for two bounds, remains stable for equal tuples, `useRoadEdges(..., false)` makes no request, and the enabled hook forwards its abort signal when bounds change/unmount.

Pass 201 exact edge IDs to `useExactRoadEdges`; assert two requests (200 + 1), stable chunk keys, merged deterministic items/missing IDs, and aggregate pending/error/refetch behavior. Each request receives its own TanStack Query abort signal. Assert the compatibility result still exposes `.query.data`, `.query.isSuccess`, `.query.isError`, `.query.isPending`, `.query.refetch()`, `requestedEdgeIds`, `queriedEdgeIds`, and `omittedEdgeIds`; all 201 IDs appear in both requested/queried arrays and the omitted array is empty.

- [ ] **Step 3: Run focused tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/api/types.test.ts src/api/client.test.ts src/api/hooks.test.tsx
```

Expected: FAIL because the schemas and bbox query do not exist.

- [ ] **Step 4: Add schemas and request types**

Add:

```typescript
export const resourceRelocationSchema = z.object({
  resourceId: nonblankStringSchema,
  requestedLongitude: z.number().finite().min(-180).max(180),
  requestedLatitude: z.number().finite().min(-90).max(90),
  snappedLongitude: z.number().finite().min(-180).max(180),
  snappedLatitude: z.number().finite().min(-90).max(90),
  snapDistanceMeters: nonnegativeNumberSchema,
});

export const lockedAssignmentSchema = z.object({
  resourceId: nonblankStringSchema,
  destinationId: nonblankStringSchema,
});

export const assignmentSourceSchema = z.enum(["manual", "optimized"]);

export const unreachableRoutePairSchema = z.object({
  resourceId: nonblankStringSchema,
  destinationId: nonblankStringSchema,
});

export type Wgs84Bounds = readonly [number, number, number, number];
```

Extend `scenarioVersionSchema`, `recommendationAssignmentSchema`, `recommendationOutcomeSchema`, `recommendationSchema` (`technicalEvidence: jsonObjectSchema`), `simulatedResourceSchema`, and exported inferred types. Define request-only relocation coordinates separately so the client cannot send snapped fields:

```typescript
export type ResourceRelocationInput = {
  resourceId: string;
  longitude: number;
  latitude: number;
};
```

- [ ] **Step 5: Add bbox serialization and query-key identity**

Add `bbox` to `RoadEdgeQuery`, serialize it with `query.bbox.join(",")`, and include the tuple values in `queryKeys.roadGraphs.edges`. Add `enabled = true` as the third `useRoadEdges` argument and combine it with the existing graph-version guard.

Keep exact lookups without bbox, but replace the current first-200 truncation with `useQueries` over 200-ID chunks and a deterministic combined result. The existing `fetch` `AbortSignal` path supplies cancellation; do not add a second request manager.

Preserve the facade used by the current `AppShell` until Task 11 replaces that caller:

```typescript
export type ExactRoadEdgesResult = {
  query: {
    data: RoadEdgeList | undefined;
    error: Error | null;
    isPending: boolean;
    isError: boolean;
    isSuccess: boolean;
    refetch: () => Promise<unknown>;
  };
  requestedEdgeIds: readonly string[];
  queriedEdgeIds: readonly string[];
  omittedEdgeIds: readonly string[];
};

return {
  query: {
    data: mergedData,
    error: firstError,
    isPending: queries.some((item) => item.isPending),
    isError: queries.some((item) => item.isError),
    isSuccess: queries.length === 0 || queries.every((item) => item.isSuccess),
    refetch: async () => { await Promise.all(queries.map((item) => item.refetch())); },
  },
  requestedEdgeIds,
  queriedEdgeIds: requestedEdgeIds,
  omittedEdgeIds: [],
};
```

`mergedData.items` and `mergedData.missingEdgeIds` are de-duplicated and sorted by edge ID; `mergedData.total` is the merged item count, not the sum of per-chunk totals.

- [ ] **Step 6: Update shared fixtures and handlers once**

Add empty relocation/lock/unreachable-pair arrays, `optimized` assignment sources, and a minimal valid technical-evidence object to legacy fixtures; add human labels to simulated resources. Teach the MSW scenario handler to echo requested relocation/lock fields using deterministic snapped fixture values. Teach the road handler to accept bbox but retain exact-ID behavior.

```typescript
const mapPlanningFixtureFields = {
  assignments: recommendationFixture.assignments.map((item) => ({
    ...item,
    assignmentSource: "optimized" as const,
  })),
  technicalEvidence: {
    resources: [], demands: [], candidateRoutes: [], limits: {},
    overlays: {}, bindingConstraints: [],
  },
  outcome: {
    ...recommendationFixture.outcome,
    unreachableRoutePairs: [],
  },
} satisfies Pick<Recommendation, "assignments" | "technicalEvidence" | "outcome">;

const relocationResponse = body.resourceRelocations?.map((item) => ({
  resourceId: item.resourceId,
  requestedLongitude: item.longitude,
  requestedLatitude: item.latitude,
  snappedLongitude: item.longitude,
  snappedLatitude: item.latitude,
  snapDistanceMeters: 0,
})) ?? previous.resourceRelocations;
```

- [ ] **Step 7: Run frontend API checks**

Run:

```bash
cd frontend
npm test -- --run src/api/types.test.ts src/api/client.test.ts src/api/hooks.test.tsx
npm run build
```

Expected: focused tests pass and TypeScript/Vite build succeeds.

- [ ] **Step 8: Commit the client-contract slice**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/hooks.ts frontend/src/api/types.test.ts frontend/src/api/client.test.ts frontend/src/api/hooks.test.tsx frontend/src/test/fixtures.ts frontend/src/test/server.ts
git commit -m "feat: add map planning API contracts"
```

---

### Task 8: Implement the Reversible Local Planning Draft

**Files:**
- Create: `frontend/src/features/planning/planningDraft.ts`
- Create: `frontend/src/features/planning/planningDraft.test.ts`

**Interfaces:**
- `PlanningDraftBasis = { incidentId; incidentSnapshotId; graphVersion }`.
- `PlanningDraftValues` contains closed road IDs, zero-or-one wind override, resource availability changes, requested relocations, and locked assignments.
- `PlanningDraft = { basis; present; past }`; `past` stores immutable prior values for Undo.
- `DraftAction` is a discriminated union for road, wind, availability, relocation, and assignment mutations.
- Pure helpers: `createPlanningDraft`, `reducePlanningDraft`, `undoPlanningDraft`, `clearPlanningDraft`, `draftChangeCount`, `isPlanningDraftEmpty`, `validatePlanningDraft`, `planningDraftSignature`, and `planningDraftRequest`.

- [ ] **Step 1: Write failing reducer tests**

Cover every mutation and its inverse behavior:

```typescript
let draft = createPlanningDraft({
  incidentId: "park-fire",
  incidentSnapshotId: "snapshot-3",
  graphVersion: "park-fire-v1",
});
draft = reducePlanningDraft(draft, { type: "toggle-road", edgeId: "edge-7" });
draft = reducePlanningDraft(draft, {
  type: "set-wind",
  windSpeedMps: 8,
  windDirectionDegrees: 225,
});
draft = reducePlanningDraft(draft, {
  type: "relocate-resource",
  resourceId: "sim-engine-1",
  longitude: -121.61,
  latitude: 39.75,
});
draft = reducePlanningDraft(draft, {
  type: "lock-assignment",
  resourceId: "sim-engine-2",
  destinationId: "community-1",
});

expect(draftChangeCount(draft)).toBe(4);
expect(undoPlanningDraft(draft).present.lockedAssignments).toEqual([]);
expect(clearPlanningDraft(draft)).toEqual(
  createPlanningDraft(draft.basis),
);
```

Assert toggling a road twice removes it, restoring observed availability removes the override, a second relocation/assignment for the same resource replaces the first, removing a nonexistent value is a no-op that does not append history, and all collections/signatures remain deterministic regardless of action order.

- [ ] **Step 2: Write failing validation and request tests**

Validate against explicit incident IDs:

```typescript
const result = validatePlanningDraft(draft, {
  resourceIds: new Set(["sim-engine-1", "sim-engine-2"]),
  destinationIds: new Set(["community-1"]),
});
expect(result).toEqual({ valid: true, issues: [] });

expect(planningDraftRequest(draft)).toEqual({
  roadClosures: [{ edgeId: "edge-7" }],
  weatherOverrides: [{ windSpeedMps: 8, windDirectionDegrees: 225 }],
  resourceOverrides: [],
  resourceRelocations: [
    {
      resourceId: "sim-engine-1",
      longitude: -121.61,
      latitude: 39.75,
    },
  ],
  lockedAssignments: [
    { resourceId: "sim-engine-2", destinationId: "community-1" },
  ],
});
```

Reject nonfinite/out-of-WGS84 relocation coordinates, unknown resources/destinations, and a lock on a resource made unavailable in the same draft. Road IDs can leave the viewport after selection, so client validation checks only that they are nonblank; the pinned-graph membership check remains authoritative on the backend. Return human-readable issues with stable IDs retained in the issue object for focus targeting.

- [ ] **Step 3: Run the draft tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/planningDraft.test.ts
```

Expected: FAIL because the draft module does not exist.

- [ ] **Step 4: Implement immutable values and reducer helpers**

Use sorted arrays rather than `Map`/`Set` in stored state so signatures and API bodies are deterministic. Each changed action appends the previous `present` object to `past`; a no-op returns the identical draft object. `undoPlanningDraft` pops once. `clearPlanningDraft` returns an empty draft with the same basis.

Use one lock and one relocation per resource by replacement. Locking does not implicitly remove relocation, and relocating does not implicitly assign: the two actions have different operational meaning and may coexist only when the operator explicitly creates both.

```typescript
function withPresent(
  draft: PlanningDraft,
  present: PlanningDraftValues,
): PlanningDraft {
  return present === draft.present
    ? draft
    : { ...draft, present, past: [...draft.past, draft.present] };
}

export function undoPlanningDraft(draft: PlanningDraft): PlanningDraft {
  const previous = draft.past.at(-1);
  return previous === undefined
    ? draft
    : { ...draft, present: previous, past: draft.past.slice(0, -1) };
}

export function clearPlanningDraft(draft: PlanningDraft): PlanningDraft {
  return createPlanningDraft(draft.basis);
}
```

- [ ] **Step 5: Implement derived validation and serialization**

Keep validation pure and fast. The backend remains authoritative for graph snapping, capacity, capability, and reachability. `planningDraftRequest` returns full replacement arrays in API shape. `planningDraftSignature` serializes `{ basis, present }` only; history must never affect stale-result detection or idempotency intent.

```typescript
export function planningDraftSignature(draft: PlanningDraft): string {
  return JSON.stringify({ basis: draft.basis, present: draft.present });
}

export function planningDraftRequest(
  draft: PlanningDraft,
): ScenarioVersionCreateRequest {
  return {
    roadClosures: draft.present.closedRoadIds.map((edgeId) => ({ edgeId })),
    weatherOverrides: draft.present.windOverride === null
      ? []
      : [draft.present.windOverride],
    resourceOverrides: draft.present.resourceAvailability,
    resourceRelocations: draft.present.resourceRelocations,
    lockedAssignments: draft.present.lockedAssignments,
  };
}
```

- [ ] **Step 6: Run focused checks**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/planningDraft.test.ts
npm run build
```

Expected: reducer tests and TypeScript/Vite build pass.

- [ ] **Step 7: Commit the local-draft slice**

```bash
git add frontend/src/features/planning/planningDraft.ts frontend/src/features/planning/planningDraft.test.ts
git commit -m "feat: add reversible local planning draft"
```

---

### Task 9: Add Draft Preview Overlays and Semantic Map Interactions

**Files:**
- Modify: `frontend/src/features/map/planningOverlays.ts`
- Modify: `frontend/src/features/map/planningOverlays.test.ts`
- Modify: `frontend/src/features/map/layers.ts`
- Modify: `frontend/src/features/map/OperationsMap.tsx`
- Modify: `frontend/src/features/map/OperationsMap.test.tsx`
- Modify: `frontend/src/test/maplibre.ts`

**Interfaces:**
- Adds pure `buildDraftPreviewOverlays(incident, draft, visibleRoads)` separate from computed recommendation overlays; recommendation overlays expose covered, uncovered, and unreachable asset states from the current recommendation and add newly-covered classification only when an optional comparable baseline recommendation exists.
- Adds explicit `RecommendationOverlayResult = { routes; coverageAssets; unreachableIndicators; metadata }`; no exception state is inferred from diagnostic strings.
- Adds the exact `MapObjectIdentity`, `MapTool`, and `MapInteractionEvent` discriminated unions shown below; no MapLibre type appears in callback payloads.
- `OperationsMap` receives visible roads, draft relocation/assignment overlays, recommendation coverage/exception overlays, selected-object identity, active tool, active assignment resource, a recenter token, and reduced-motion preference.
- `OperationsMap` emits object selection, road toggle, resource drop, assignment request, and viewport-bound events.
- New props are optional with empty/select/no-op defaults in this slice so the existing `AppShell` still builds; Task 11 wires every prop and makes the command workspace the sole caller.

- [ ] **Step 1: Write failing pure overlay tests**

Build a draft containing a closed road, unavailable resource, relocation, and manual assignment. Assert:

```typescript
const preview = buildDraftPreviewOverlays(incidentFixture, draft, roadList);

expect(preview.closures.features[0]).toMatchObject({
  properties: {
    sourceKind: "draft-road-closure",
    edgeId: "edge-7",
    state: "draft",
  },
});
expect(preview.relocatedResources.features[0].geometry).toEqual({
  type: "Point",
  coordinates: [-121.61, 39.75],
});
expect(preview.manualAssignments.features[0]).toMatchObject({
  properties: {
    resourceId: "sim-engine-2",
    destinationId: "community-1",
    assignmentSource: "manual",
  },
});
```

The manual connector starts at the draft relocation when the same resource is relocated; otherwise it starts at observed geometry. Missing road/resource/destination geometry is reported in metadata and never throws. Recommendation routes remain a distinct collection with `state: "recommendation"` and `routeStatus`. Recommendation asset features always classify destinations as `covered`, `uncovered`, or `unreachable`; they use `newly-covered` only when an optional baseline recommendation for the same incident snapshot and graph proves the destination was not previously covered. With no comparable baseline, covered destinations remain `covered` and no improvement is invented. Unavailable IDs never make an asset disappear. Each `unreachableRoutePair` becomes a dashed red straight-line exception connector labelled “No routable path”; its properties and legend explicitly say it is a relationship indicator, not a traversable road route.

```typescript
expect(buildRecommendationOverlays({
  incident: incidentFixture,
  recommendation: currentRecommendation,
  baselineRecommendation: null,
  roads,
}).coverageAssets.features.map((feature) => feature.properties.coverageState))
  .not.toContain("newly-covered");

expect(buildRecommendationOverlays({
  incident: incidentFixture,
  recommendation: currentRecommendation,
  baselineRecommendation: comparableBaseline,
  roads,
}).coverageAssets.features)
  .toEqual(expect.arrayContaining([
    expect.objectContaining({ properties: expect.objectContaining({
      assetId: "community-1",
      coverageState: "newly-covered",
    }) }),
  ]));
```

- [ ] **Step 2: Write failing semantic-event map tests**

Extend the MapLibre test double to support:

- layer-qualified `on`/`off` listeners;
- event payload injection;
- `getBounds` and configurable bounds;
- `queryRenderedFeatures` for a point and layer list;
- `dragPan.disable()` / `dragPan.enable()`;
- canvas cursor state; and
- `setFilter` or `setFeatureState` recording for selection;
- `addControl`/`removeControl` for MapLibre navigation controls; and
- layer visibility recording for the accessible observation/resource/plan toggles; and
- `fitBounds`/`jumpTo` recording for explicit incident recentering.

Then assert exact plain-object callbacks:

```typescript
act(() => map.emitLayer("click", MAP_LAYER_IDS.exposedAssetsHit, {
  features: [{ properties: { assetId: "community-1" } }],
  lngLat: { lng: -121.54, lat: 40.08 },
}));
expect(onEvent).toHaveBeenCalledWith({
  type: "select-object",
  object: { kind: "asset", destinationId: "community-1" },
});

act(() => map.emit("moveend"));
expect(onEvent).toHaveBeenCalledWith({
  type: "viewport-changed",
  bbox: [-121.7, 39.7, -121.5, 39.9],
});
```

Cover incident/resource/asset/road/route selection, road click only in `close-road` mode, assignment request only in `assign` mode with an active resource, drag start/move/drop, Escape/cancel restoring observed data, and listener cleanup. Changing the explicit incident recenter token must fit the incident geometry (or jump to a point incident); reduced motion uses the nonanimated path.

- [ ] **Step 3: Write failing layer-order and style tests**

Assert sources/layers install once above the external or fallback basemap in this operational order:

1. visible selectable roads and transparent road hit layer;
2. incident and detections;
3. exposed assets and simulated resources;
4. draft closures, relocations, availability, and manual connectors;
5. recommendation routes, coverage states, and exceptions; and
6. selected-object emphasis.

Assert draft styling is amber with a dash/pattern, recommendation routes are cyan, synthetic unreachable route features are dashed red, selected objects use a high-contrast outline, and reduced motion removes route transition/animation configuration.

```typescript
act(() => map.emit("style.load"));
expect(map.addLayer.mock.calls.map(([layer]) => layer.id)).toEqual(
  expect.arrayContaining([
    MAP_LAYER_IDS.visibleRoads,
    MAP_LAYER_IDS.incident,
    MAP_LAYER_IDS.simulatedResources,
    MAP_LAYER_IDS.draftClosures,
    MAP_LAYER_IDS.recommendationRoutes,
    MAP_LAYER_IDS.unreachableIndicators,
    MAP_LAYER_IDS.selection,
  ]),
);
expect(layerById(MAP_LAYER_IDS.draftClosures).paint).toMatchObject({
  "line-dasharray": expect.any(Array),
});
expect(layerById(MAP_LAYER_IDS.unreachableIndicators).paint).toMatchObject({
  "line-dasharray": expect.any(Array),
});
```

- [ ] **Step 4: Run focused map tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/features/map/planningOverlays.test.ts src/features/map/OperationsMap.test.tsx
```

Expected: FAIL because preview collections, event contracts, sources, and mock methods are absent.

- [ ] **Step 5: Derive draft overlays without mutating observed features**

Add a `DraftPreviewOverlayResult` with `closures`, `relocatedResources`, `manualAssignments`, `unavailableResources`, `wind`, and missing-geometry metadata. Add `RecommendationOverlayResult` with separate `routes`, `coverageAssets`, and `unreachableIndicators` feature collections plus missing-geometry metadata. Its builder accepts `baselineRecommendation: Recommendation | null`; compare only when baseline/current incident snapshot and graph versions match, otherwise treat baseline as absent. Clone GeoJSON inputs when adding properties. Manual assignment geometry is a straight UI connector labelled as an assignment intent, not a routed path. Keep the existing exact-edge recommendation builder for computed routes, and derive coverage/exception collections only from typed recommendation fields.

```typescript
type RecommendationRouteProperties = {
  sourceKind: "recommendation-route";
  resourceId: string;
  destinationId: string;
  routeStatus: "reachable" | "unreachable";
  freshness: "current" | "stale";
};

type CoverageAssetProperties = {
  sourceKind: "recommendation-coverage";
  assetId: string;
  coverageState: "covered" | "newly-covered" | "uncovered" | "unreachable";
};

type ExceptionProperties = {
  sourceKind: "unreachable-indicator";
  resourceId: string;
  destinationId: string;
  label: "No routable path";
};

export type RecommendationOverlayResult = {
  routes: FeatureCollection<LineString, RecommendationRouteProperties>;
  coverageAssets: FeatureCollection<Geometry, CoverageAssetProperties>;
  unreachableIndicators: FeatureCollection<LineString, ExceptionProperties>;
  metadata: { missingGeometryIds: readonly string[] };
};

const comparableBaseline = baselineRecommendation !== null
  && baselineRecommendation.incidentSnapshotId === recommendation.incidentSnapshotId
  && baselineRecommendation.graphVersion === recommendation.graphVersion
  ? baselineRecommendation
  : null;
```

- [ ] **Step 6: Add map sources and accessible visual encodings**

Extend `MAP_SOURCE_IDS`, `MAP_LAYER_IDS`, `MAP_IMAGES`, and `MAP_LAYERS` rather than creating a second map abstraction. Add visible-road geometry plus a wider transparent hit layer, coverage/unreachable asset halos, and labels for exception states. Use line dashes/icons/text properties in addition to color. Route styling reads `routeStatus` and `freshness`; stale routes are visually demoted. Add a reduced-motion boolean to the route layer factory if the style needs different transition properties.

Add MapLibre’s `NavigationControl` and compact checkbox/button layer controls for observations, exposed assets, resources, draft overlays, and recommendations. Layer controls stay outside the canvas with accessible names and use the existing `setLayoutProperty` path; they do not rebuild sources or styles.

```typescript
const navigation = new maplibregl.NavigationControl({ showCompass: true });
map.addControl(navigation, "top-right");

function setGroupVisibility(layerIds: readonly string[], visible: boolean): void {
  for (const layerId of layerIds) {
    if (map.getLayer(layerId) !== undefined) {
      map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
    }
  }
}
```

- [ ] **Step 7: Emit semantic map events**

Define:

```typescript
export type MapTool =
  | "select"
  | "close-road"
  | "move-resource"
  | "assign"
  | "wind"
  | "availability";

export type MapObjectIdentity =
  | { kind: "incident"; incidentId: string }
  | { kind: "resource"; resourceId: string }
  | { kind: "asset"; destinationId: string }
  | { kind: "road"; edgeId: string }
  | { kind: "route"; resourceId: string; destinationId: string }
  | { kind: "exception"; resourceId: string; destinationId: string };

export type MapInteractionEvent =
  | { type: "select-object"; object: MapObjectIdentity }
  | { type: "toggle-road"; edgeId: string }
  | {
      type: "resource-drop";
      resourceId: string;
      longitude: number;
      latitude: number;
      destinationId?: string;
    }
  | { type: "request-assignment"; resourceId: string; destinationId: string }
  | {
      type: "viewport-changed";
      bbox: readonly [number, number, number, number];
    };
```

Layer listeners translate feature properties immediately and discard malformed features. A resource drop may include `destinationId` only when the drop point intersects an exposed-asset hit layer; the map never chooses Assign versus Relocate.

During a drag, update only a temporary cloned resource collection in the map source. On drop emit one event, then immediately restore the React-provided collection and re-enable pan; choosing Relocate later moves the marker through normal draft props, while Cancel leaves observed geometry untouched. Escape, pointer cancellation, unmount, and incident change perform the same restore without emitting a drop.

- [ ] **Step 8: Keep basemap fallback and cleanup guarantees**

Retain the existing one-time external-style fallback and loaded guard. Register operational layer listeners only after `style.load`, and remove every style, error, move, keyboard, pointer, and layer-qualified listener before `map.remove()`. A fallback `style.load` still initializes the complete source/layer/event set exactly once.

```typescript
return () => {
  map.off("style.load", handleStyleLoad);
  map.off("error", handleStyleError);
  map.off("moveend", handleMoveEnd);
  for (const binding of layerBindings) {
    map.off(binding.type, binding.layerId, binding.listener);
  }
  map.removeControl(navigation);
  map.remove();
};
```

- [ ] **Step 9: Run focused map checks**

Run:

```bash
cd frontend
npm test -- --run src/features/map/planningOverlays.test.ts src/features/map/OperationsMap.test.tsx
npm run build
```

Expected: pure overlay and component tests pass; build succeeds.

- [ ] **Step 10: Commit the interactive-map slice**

```bash
git add frontend/src/features/map/planningOverlays.ts frontend/src/features/map/planningOverlays.test.ts frontend/src/features/map/layers.ts frontend/src/features/map/OperationsMap.tsx frontend/src/features/map/OperationsMap.test.tsx frontend/src/test/maplibre.ts
git commit -m "feat: make the operations map interactive"
```

---

### Task 10: Implement One Planning Session Orchestrator

**Files:**
- Create: `frontend/src/features/planning/usePlanningSession.ts`
- Create: `frontend/src/features/planning/usePlanningSession.test.tsx`

**Interfaces:**
- `usePlanningSession({ incident, draft, freshnessToken, planningDisabled })` accepts `PlanningDraft | null` and owns server-command session state only: planning context, selected/default graph, baseline/latest versions, optional baseline recommendation, matching recommendation, failed recommendation version, command error, decided recommendation ID, and stale latch.
- Exports the hook result as `PlanningSessionResult` so the drawer and dock consume one contract rather than restating hook internals.
- Exposes `runPlan`, `retryRecommendation`, `resetSession`, and `markDecisionRecorded(recommendationId)` plus `commandError`, `commandErrorKind` and derived `graphVersion`, `decidedRecommendationId`, `busy`, `canRun`, `canRetry`, `baselineRecommendation`, `currentRecommendation`, `recommendationStale`, and `sessionStale`. `baselineRecommendation` remains null when the first deliberate run uses a nonempty draft; the UI then reports current coverage without inventing a baseline change.
- The hook never owns or clears `planningDraft`; failures therefore cannot lose local assumptions.

- [ ] **Step 1: Write failing orchestration tests for empty and nonempty drafts**

Using the existing MSW handlers and a hook harness, assert:

```typescript
await act(async () => result.current.runPlan());

expect(serverRequests).toEqual([
  ["POST", `/api/incidents/${incident.id}/scenarios`],
  ["POST", `/api/scenario-versions/${baselineVersion.id}/recommendations`],
]);
expect(result.current.currentRecommendation?.scenarioVersionId).toBe(
  baselineVersion.id,
);
```

For a nonempty draft, assert the sequence is create baseline if needed → create exactly one immutable version with `planningDraftRequest(draft)` → generate for that exact version. A second click while any command is pending produces no additional request.

- [ ] **Step 2: Write failing retry, edit, and stale tests**

Cover:

- scenario version succeeds and recommendation fails: `canRetry` is true and the draft is unchanged;
- Retry generates for the same stored version and does not create a second version;
- changing the draft after failure disables Retry and the next Run creates a new version;
- changing the draft after success demotes the prior result to stale and disables decision actions;
- incident snapshot or freshness-token change latches the session stale;
- late promises from an old incident/unmounted hook cannot settle the new session; and
- `resetSession` resets existing idempotent mutation hooks and all session-owned state only.

```typescript
await act(async () => result.current.runPlan());
expect(result.current.canRetry).toBe(true);
expect(result.current.currentRecommendation).toBeNull();
expect(currentDraftProp).toEqual(draftBeforeFailure);

await act(async () => result.current.retryRecommendation());
expect(versionPosts).toHaveLength(1);
expect(recommendationPosts).toHaveLength(2);

rerender({ incident: newerIncident, draft: newerDraft });
resolveOldRecommendation(oldRecommendation);
expect(result.current.currentRecommendation).toBeNull();
expect(result.current.sessionStale).toBe(false);
```

- [ ] **Step 3: Run the hook tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/usePlanningSession.test.tsx
```

Expected: FAIL because the planning-session hook does not exist.

- [ ] **Step 4: Port the existing command guards into the hook**

Implement the current `sessionGeneration`, `mounted`, `latestPolicy`, snapshot mismatch, freshness latch, mutation guards, graph selection, and error-classification behavior inside the new hook. Use `useCreateScenarioMutation`, `useCreateScenarioVersionMutation`, `useGenerateRecommendationMutation`, `useDecisionContext`, and the existing recommendation defaults (`30` minutes, `2` solver seconds). Task 11 removes the corresponding orchestration from `ScenarioPlanningPanel` when it integrates the hook, so no duplicate command path remains in the finished design.

Derive a stable `draftSignature = planningDraftSignature(draft)`. Record the signature paired with the version and recommendation. A recommendation is current only when incident ID, snapshot ID, graph version, scenario version ID, freshness token, and draft signature all match.

```typescript
const generationRef = useRef(0);
const mountedRef = useRef(true);
const policyRef = useRef({
  incidentId: incident.id,
  snapshotId: incident.snapshotId,
  freshnessToken,
  planningDisabled,
});

const canSettle = (generation: number): boolean =>
  mountedRef.current
  && generationRef.current === generation
  && policyRef.current.incidentId === incident.id;
```

- [ ] **Step 5: Implement one deliberate Run plan sequence**

`runPlan` must:

1. reject when disabled, stale, invalid, or busy;
2. ensure a baseline scenario exists for the selected incident/graph;
3. use the baseline version for an empty draft, otherwise create one replacement version;
4. generate a recommendation for that exact version;
5. keep the draft and pair the result with its signature; and
6. never auto-approve, clear assumptions, or mutate observed data.

If recommendation generation fails after a version write, store `{ version, draftSignature }` as the retry target. `retryRecommendation` may use it only while the draft signature and incident policy still match.

```typescript
type SettledRecommendation = {
  version: ScenarioVersion;
  recommendation: Recommendation;
  signature: string;
  isBaseline: boolean;
};

const ensureBaselineScenario = async (): Promise<ScenarioVersion> => {
  if (baselineVersion !== null) return baselineVersion;
  const version = await createScenario.mutateAsync({
    incidentId: incident.id,
    body: {
      graphVersion: selectedGraph,
      objective: "minimize-response-time",
      algorithmConfigVersion: "scenario-v1",
    },
  });
  setBaselineVersion(version);
  return version;
};

const settleRecommendation = (result: SettledRecommendation): void => {
  setLatestVersion(result.version);
  setLastSuccessful(result);
  if (result.isBaseline) setBaselineRecommendation(result.recommendation);
  setRetryTarget(null);
  setCommandError(null);
};

const runPlan = async (): Promise<void> => {
  if (!canRun || draft === null) return;
  const generation = generationRef.current;
  const signature = planningDraftSignature(draft);
  const isBaseline = isPlanningDraftEmpty(draft);
  let version: ScenarioVersion | null = null;
  try {
    const baseline = await ensureBaselineScenario();
    if (!canSettle(generation)) return;
    version = isBaseline
      ? baseline
      : await createVersion.mutateAsync({
          scenarioId: baseline.scenarioId,
          body: planningDraftRequest(draft),
        });
    if (!canSettle(generation)) return;
    const recommendation = await generateRecommendation.mutateAsync({
      versionId: version.id,
      body: recommendationRequest,
    });
    if (canSettle(generation)) {
      settleRecommendation({ version, recommendation, signature, isBaseline });
    }
  } catch (error) {
    if (canSettle(generation)) {
      setRetryTarget(
        version === null ? null : { version, draftSignature: signature },
      );
      setCommandError(error);
    }
  }
};
```

- [ ] **Step 6: Expose errors without hiding server explanations**

Return `commandError` and use the existing `ApiClientError` code/message helpers. Distinguish scenario validation, stale inputs, network failure, and solver failure for the command dock, but keep raw technical details for the drawer. `busy` is derived from the three mutation pending states rather than a parallel phase state machine.

```typescript
const busy = createScenario.isPending
  || createVersion.isPending
  || generateRecommendation.isPending;
const commandErrorKind = commandError instanceof ApiClientError
  ? commandError.code === "scenario_invalid"
    ? "scenario-validation"
    : commandError.code === "network_error"
      ? "network"
    : commandError.code.includes("stale")
      ? "stale"
      : commandError.code === "recommendation_inputs_invalid"
        || commandError.code === "internal_error"
        ? "solver"
        : "api"
  : commandError === null ? null : "network";
```

- [ ] **Step 7: Run focused planning-session checks**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/usePlanningSession.test.tsx
npm run build
```

Expected: all orchestration cases pass and build succeeds.

- [ ] **Step 8: Commit the session slice**

```bash
git add frontend/src/features/planning/usePlanningSession.ts frontend/src/features/planning/usePlanningSession.test.tsx
git commit -m "feat: orchestrate one-step plan runs"
```

---

### Task 11: Assemble the Map-First Command Workspace

**Files:**
- Create: `frontend/src/features/planning/CommandWorkspace.tsx`
- Create: `frontend/src/features/planning/CommandWorkspace.test.tsx`
- Create: `frontend/src/features/planning/CommandDock.tsx`
- Create: `frontend/src/features/planning/CommandDock.test.tsx`
- Create: `frontend/src/features/planning/SelectedObjectCard.tsx`
- Create: `frontend/src/features/planning/SelectedObjectCard.test.tsx`
- Create: `frontend/src/features/planning/DetailsDrawer.tsx`
- Create: `frontend/src/features/planning/DetailsDrawer.test.tsx`
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/app/AppShell.test.tsx`
- Modify: `frontend/src/features/incidents/IncidentQueue.tsx`
- Modify: `frontend/src/features/incidents/IncidentQueue.test.tsx`
- Modify: `frontend/src/features/incidents/IncidentDetails.tsx`
- Modify: `frontend/src/features/scenarios/ScenarioPlanningPanel.tsx`
- Modify: `frontend/src/features/scenarios/ScenarioPlanningPanel.test.tsx`
- Modify: `frontend/src/features/scenarios/ScenarioEditor.tsx`
- Modify: `frontend/src/features/scenarios/ScenarioEditor.test.tsx`
- Modify: `frontend/src/features/decisions/RecommendationPanel.tsx`
- Modify: `frontend/src/features/decisions/RecommendationPanel.test.tsx`
- Modify: `frontend/src/features/decisions/DecisionDialog.tsx`
- Modify: `frontend/src/features/decisions/DecisionDialog.test.tsx`
- Modify: `frontend/src/features/decisions/AuditDrawer.tsx`
- Modify: `frontend/src/features/decisions/AuditDrawer.test.tsx`
- Modify: `frontend/src/App.css`

**Interfaces:**
- `AppShell` keeps data loading/replay and delegates the incident/map/planning surface to `CommandWorkspace`.
- `CommandWorkspace` owns exactly one `PlanningDraft | null`, selected object, active map tool, viewport bounds, pending resource drop, drawer state, rail state, and incident-switch confirmation.
- `CommandDock` accepts a nonnullable `PlanningDraft` after workspace bootstrap and renders the current tool, draft count, Undo, Clear, Run, run failure actions, and compact PLAN READY result/decision controls.
- `DetailsDrawer` reuses the existing incident, scenario, comparison, recommendation, decision, and audit components as optional detail surfaces.

- [ ] **Step 1: Write failing first-viewport component tests**

At a mocked desktop viewport, render Park Fire and assert the first DOM order and actions:

```typescript
expect(screen.getByRole("heading", { name: "Park Fire" })).toBeVisible();
expect(screen.getByText(/priority score/i)).toBeVisible();
expect(screen.getByText(/top driver/i)).toBeVisible();
expect(screen.getByRole("button", { name: /move resource/i })).toBeVisible();
expect(await screen.findByRole("button", { name: /run plan/i })).toBeVisible();
expect(screen.queryByText(/raw incident json/i)).not.toBeVisible();
```

Assert the persistent portfolio-simulation notice remains visible, the top bar names Park Fire with incident/source freshness and an Audit entry point, the incident rail contains only compact incident summaries and an `aria-expanded` collapse toggle, the map region is present, and the Details & evidence control is optional and closed. Collapsing the rail keeps the active-incident marker and an accessible Expand incidents action.

- [ ] **Step 2: Write failing draft interaction tests through the workspace**

Exercise semantic events through the `OperationsMap` mock boundary:

1. selecting a resource opens `SelectedObjectCard` with `displayLabel`;
2. a resource drop opens an explicit choice and does not mutate the draft yet;
3. choosing Relocate adds only a relocation;
4. dropping on an asset and choosing Assign adds only a locked assignment;
5. clicking a road in road mode toggles its closure;
6. card/dock wind and availability controls update the same draft, and resource/asset cards can add or remove assignments and relocations;
7. Undo reverts one mutation and Clear confirms when more than one change exists; and
8. no scenario/recommendation POST occurs before Run plan.

Selecting an incident from the rail must also increment the map recenter token; assert the map receives a new token even when the already active Park Fire is explicitly reselected.

```typescript
act(() => emitMapEvent({
  type: "resource-drop",
  resourceId: "sim-engine-1",
  longitude: -121.61,
  latitude: 39.75,
  destinationId: "community-1",
}));
expect(screen.getByRole("dialog", { name: /resource drop/i })).toBeVisible();
expect(postedScenarioVersions).toHaveLength(0);

await user.click(screen.getByRole("button", { name: /relocate here/i }));
expect(screen.getByText(/1 draft change/i)).toBeVisible();
expect(currentDraft().present.lockedAssignments).toEqual([]);
expect(postedScenarioVersions).toHaveLength(0);
```

- [ ] **Step 3: Write failing incident-switch and graph-mismatch tests**

With a nonempty draft, selecting another incident opens a real confirmation dialog. Cancel retains incident, selection, and draft; Confirm discards/reset session and switches. With no changes, switch immediately. If the viewport road graph differs from the draft’s pinned graph, disable the road tool and display: “Road planning is unavailable until this incident is refreshed.”

```typescript
await user.click(screen.getByRole("button", { name: /second incident/i }));
const confirm = screen.getByRole("dialog", { name: /discard draft/i });
expect(confirm).toBeVisible();
await user.click(within(confirm).getByRole("button", { name: /cancel/i }));
expect(screen.getByRole("heading", { name: "Park Fire" })).toBeVisible();
expect(screen.getByText(/1 draft change/i)).toBeVisible();

rerenderWorkspace({ viewportGraphVersion: "other-graph" });
expect(screen.getByRole("button", { name: /close road/i })).toBeDisabled();
expect(screen.getByText(/road planning is unavailable until this incident is refreshed/i)).toBeVisible();
```

- [ ] **Step 4: Write failing plan-ready and drawer reuse tests**

After a successful run, assert the dock shows:

- `PLAN READY`;
- plain-language covered/uncovered counts;
- manual and optimized assignment counts;
- travel change when a baseline comparison exists;
- Adjust, Approve plan, and Reject controls; and
- an Audit action after the decision is recorded.

Open Details & evidence and assert it contains keyboard equivalents for closures, wind, availability, relocation coordinates, and locked assignments plus the existing comparison, full recommendation, decision edit, audit history, risk factors, model configuration, source provenance, detections, assets, resources, exact IDs, and raw JSON under native `<details>` elements. Preserve compact evidence summaries from the merged baseline, including “97 NASA FIRMS detections” for the Park Fire package, rather than expanding individual records by default.

```typescript
expect(await screen.findByText("PLAN READY")).toBeVisible();
expect(screen.getByText(/manual assignments/i)).toBeVisible();
expect(screen.getByRole("button", { name: /approve plan/i })).toBeEnabled();

await user.click(screen.getByRole("button", { name: /details and evidence/i }));
expect(screen.getByText("97 NASA FIRMS detections")).toBeVisible();
expect(screen.getByText(/raw incident json/i).closest("details")).not.toHaveAttribute("open");
expect(screen.getByRole("button", { name: /apply draft changes/i })).toBeEnabled();
```

- [ ] **Step 5: Run focused workspace tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/CommandWorkspace.test.tsx src/features/planning/CommandDock.test.tsx src/features/planning/SelectedObjectCard.test.tsx src/features/planning/DetailsDrawer.test.tsx src/app/AppShell.test.tsx
```

Expected: FAIL because the command workspace components do not exist.

- [ ] **Step 6: Move one draft into `CommandWorkspace`**

Call `usePlanningSession` initially with `draft: null`; once its decision-context query resolves `graphVersion`, create the draft basis from the active incident/snapshot/graph and pass it back on the next render. `canRun` remains false during that bootstrap, so there is no unpinned write window.

Maintain two road queries with different ownership:

- `useRoadEdges(graphVersion, { bbox, limit: 200 }, bbox !== null)` supplies only selectable viewport roads and exposes truncation; and
- `useExactRoadEdges(graphVersion, overlayEdgeIds)` supplies complete geometry for the union of draft closure IDs and current recommendation route edge IDs, even when edges are outside the viewport.

Never satisfy recommendation routes from the bbox cache. Add a component test where a route edge is outside/truncated from the viewport response but arrives through exact lookup and still renders. Feed observed, draft-preview, recommendation-coverage, recommendation-exception, and exact recommendation-route overlays to the map as separate props. Interpret `MapInteractionEvent` values with the pure draft reducer.

Keep `pendingDrop` transient and explicit. A small native resource-drop dialog rendered locally by `CommandWorkspace` offers:

- `Assign to <asset>` when a destination was hit, or a named destination select otherwise;
- `Relocate here` with the coordinate summary; and
- Cancel.

Neither choice triggers a server command.

The ordinary `SelectedObjectCard` still offers assignment/removal/availability actions for a selected resource or asset, but it does not own the blocking post-drag choice.

```typescript
const [draft, setDraft] = useState<PlanningDraft | null>(null);
const [viewportBounds, setViewportBounds] = useState<Wgs84Bounds | null>(null);
const session = usePlanningSession({
  incident,
  draft,
  freshnessToken,
  planningDisabled,
});

useEffect(() => {
  if (draft === null && session.graphVersion !== null) {
    setDraft(createPlanningDraft({
      incidentId: incident.id,
      incidentSnapshotId: incident.snapshotId,
      graphVersion: session.graphVersion,
    }));
  }
}, [draft, incident.id, incident.snapshotId, session.graphVersion]);

const visibleRoads = useRoadEdges(
  draft?.basis.graphVersion ?? "",
  { bbox: viewportBounds ?? undefined, limit: 200 },
  viewportBounds !== null,
);
const overlayEdgeIds = useMemo(
  () => [...new Set([
    ...(draft?.present.closedRoadIds ?? []),
    ...recommendationEdgeIds,
  ])].sort(),
  [draft?.present.closedRoadIds, recommendationEdgeIds],
);
const exactRoads = useExactRoadEdges(
  draft?.basis.graphVersion ?? "",
  overlayEdgeIds,
);

const dock = draft === null
  ? <p role="status">Loading planning tools…</p>
  : <CommandDock draft={draft} session={session} />;
```

Keep `CommandDock` and every draft helper typed to a nonnullable `PlanningDraft`; render the bootstrap status instead of calling draft helpers until the draft basis exists.

- [ ] **Step 7: Build the contextual card and compact guidance**

For incident selection, show incident name/status/freshness, **Priority score**, top contributing factor by contribution, exposed asset count, simulated resource count, and the next action. For resources/assets/roads/routes, show display label or source name first and operational actions; exact IDs appear only inside a technical `<details>`.

Render short skippable prompts near the current control. Derive completion from existing values:

- Observe: a valid incident is selected;
- Replay, only when at least two ordered frames exist: the replay position has moved or playback has run;
- Plan: a resource has been selected or the draft is nonempty;
- Recommend: a matching recommendation exists; and
- Decide: the matching recommendation has a recorded decision.

When replay has fewer than two ordered frames, omit it as a required step and place the existing explanation beside the map control. Once Track 2 repairs the timeline, Replay automatically becomes the second prompt without another layout redesign. Allow dismissing the current prompt with local presentation state, but do not create a workflow state machine or block controls.

```typescript
const missionSteps = [
  { key: "observe", complete: incident !== null },
  ...(replayFrames.length >= 2
    ? [{ key: "replay", complete: replayHasMoved }]
    : []),
  {
    key: "plan",
    complete: selectedResource !== null
      || (draft !== null && !isPlanningDraftEmpty(draft)),
  },
  { key: "recommend", complete: session.currentRecommendation !== null },
  {
    key: "decide",
    complete: session.decidedRecommendationId === session.currentRecommendation?.id,
  },
] as const;
const nextMission = missionSteps.find((step) => !step.complete) ?? null;
```

- [ ] **Step 8: Implement the dock around the planning-session hook**

Before a result, render map tools, validation summary, draft count, Undo, Clear draft, and Run plan. Lock editing while a command is pending and expose progress in a `role="status"` live region. For failure, keep overlays and show Retry only when the stored version/signature matches plus Edit assumptions in all cases.

For a current result, compute the plain-language summary from `Recommendation.outcome` and assignment sources. Render Adjust and the existing `DecisionDialog` controls inside the dock. Adjust restores editing without clearing assumptions; the first draft mutation demotes the old result and changes the primary action to Run plan again.

```tsx
<section className="command-dock" aria-label="Plan command dock">
  <DraftSummary count={draftChangeCount(draft)} issues={validation.issues} />
  <button type="button" onClick={onUndo} disabled={draft.past.length === 0}>Undo</button>
  <button type="button" onClick={onClear} disabled={isPlanningDraftEmpty(draft)}>Clear draft</button>
  <button type="button" onClick={() => void session.runPlan()} disabled={!session.canRun}>
    {session.busy ? "Running plan…" : "Run plan"}
  </button>
  {session.busy ? <p role="status">Creating scenario and computing routes…</p> : null}
  {session.currentRecommendation ? (
    <PlanReadySummary
      recommendation={session.currentRecommendation}
      onDecisionRecorded={() =>
        session.markDecisionRecorded(session.currentRecommendation!.id)}
    />
  ) : null}
</section>
```

- [ ] **Step 9: Convert `ScenarioPlanningPanel` into drawer content**

Delete its duplicate command/session state. Make it a presentational details panel receiving `draft`, `session`, road query state, and draft callbacks. Adapt `ScenarioEditor` to edit the local draft instead of submitting a scenario version; add relocation coordinate and locked-assignment fieldsets. Its submit label becomes “Apply draft changes” and never calls an API.

Keep full road search in the drawer. Search results use readable labels first and put exact edge IDs in a nested technical disclosure. All drawer controls update the same draft reducer used by the map.

```typescript
export type ScenarioPlanningPanelProps = {
  incident: IncidentDetail;
  draft: PlanningDraft;
  session: PlanningSessionResult;
  roads: RoadEdgeList | undefined;
  roadQueryState: "idle" | "loading" | "error" | "success";
  onDraftAction: (action: DraftAction) => void;
  onRetryRoads: () => void;
};
```

- [ ] **Step 10: Reuse decision and evidence components with readable labels**

Pass resource and destination objects to `DecisionDialog`, not ID arrays, so selects and summaries show `displayLabel` and asset `name`. Disable editing/removal of manual assignment rows and label them “Manual — locked by scenario”; the backend remains authoritative.

Keep full IDs in `AuditDrawer` and technical recommendation evidence. Change `RecommendationPanel`’s primary assignment list to human labels plus Manual/Optimized badges; keep edge IDs and exact identities inside its existing technical disclosure. Adapt `IncidentDetails` the same way: detection record IDs, asset IDs, resource IDs, source payloads, and raw JSON stay in collapsed technical disclosures while operational lists use source names, asset names, and resource display labels. Include `scenarioAssumptions` in Audit provenance.

```tsx
<option value={resource.resourceId}>{resource.displayLabel}</option>
<option value={asset.assetId}>{asset.name}</option>

<span className={`assignment-badge assignment-badge--${assignment.assignmentSource}`}>
  {assignment.assignmentSource === "manual" ? "Manual — locked by scenario" : "Optimized"}
</span>
```

- [ ] **Step 11: Implement the nonmodal Details & evidence drawer**

Use an `<aside aria-label="Details and evidence">`, not a new modal library. Mount it on first open and hide/show it without unmounting thereafter. On open, focus a `tabIndex={-1}` drawer heading; Escape/Close returns focus to the invoking button. Do not trap focus because the map remains available. Preserve selected object, draft, scroll position, and loaded queries across close/open.

Put technical sections under native collapsed `<details>` elements. Add a keyboard-operable “Map objects” list for incidents, resources, assets, visible/searched roads, routes, and result exceptions; activating each row kind updates the same selected-object identity, contextual card, and map emphasis as a pointer selection. Add focused tests for all six kinds plus keyboard activation of the PLAN READY result summary. Keep the audit query disabled until both the drawer and audit disclosure are open; closing and reopening must reuse TanStack Query cache data rather than resetting the selection.

```tsx
<aside aria-label="Details and evidence" hidden={!open}>
  <h2 ref={headingRef} tabIndex={-1}>Details & evidence</h2>
  <button type="button" onClick={onClose}>Close details</button>
  <nav aria-label="Map objects">
    {objects.map((object) => (
      <button key={mapObjectKey(object)} type="button" onClick={() => onSelect(object)}>
        {mapObjectLabel(object)}
      </button>
    ))}
  </nav>
  <details><summary>Technical evidence</summary>{technicalEvidence}</details>
</aside>
```

- [ ] **Step 12: Recompose `AppShell` without duplicating data ownership**

Keep incident/source/timeline queries, replay timer, map data shaping, and basemap behavior. Replace the old three siblings (`IncidentQueue`, map section, `IncidentDetails` decision column) with `CommandWorkspace`. Put the selected incident label, incident/source freshness, and Audit shortcut in the top bar. Adapt `IncidentQueue` into the collapsible rail without duplicating its selection logic. Move the compact replay control into map chrome. Until Track 2 repairs the package, retain the explicit explanation that replay requires at least two ordered snapshots; do not show a mysterious disabled Play button.

```tsx
<CommandWorkspace
  incidents={incidentsQuery.data?.items ?? []}
  incident={incident}
  mapData={mapData}
  replay={{ frames, replayTime, playing, onReplayTime: setReplayTime, onPlaying: setPlaying }}
  freshnessToken={planningFreshnessToken}
  planningDisabled={replaying}
  onSelectIncident={(incidentId) => {
    setSelectedIncidentId(incidentId);
    setPlaying(false);
    setReplayTime(null);
  }}
/>
```

`CommandWorkspace` increments its recenter token before invoking `onSelectIncident`, including when `incidentId` is already active. `AppShell` retains the existing replay reset in the callback; do not attempt to assign the derived `activeIncidentId`.

- [ ] **Step 13: Add the desktop and stacked CSS structure**

At `min-width: 1024px`, make `.command-workspace` a map-filling positioned canvas with a compact left rail, floating selected-object card, bottom dock, and right drawer. Keep the daylight map and dark tactical chrome; use cyan for active/recommendation routes, amber for draft assumptions, and red/orange for fire/errors with noncolor reinforcement.

Below 1024px, use normal document flow in this order: incident list, selected summary, map, command controls, result, details. Do not require drag parity; drawer forms remain complete.

```css
.command-workspace { position: relative; min-block-size: 0; }
.command-workspace__map { position: absolute; inset: 0; }
.command-dock { position: absolute; inset-inline: 1rem; inset-block-end: 1rem; }

@media (max-width: 1023px) {
  .command-workspace { display: grid; position: static; }
  .command-workspace__map,
  .command-dock,
  .details-drawer { position: static; }
}
```

- [ ] **Step 14: Run the focused component suite**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/CommandWorkspace.test.tsx src/features/planning/CommandDock.test.tsx src/features/planning/SelectedObjectCard.test.tsx src/features/planning/DetailsDrawer.test.tsx src/features/incidents/IncidentQueue.test.tsx src/features/incidents/IncidentDetails.test.tsx src/features/scenarios/ScenarioPlanningPanel.test.tsx src/features/scenarios/ScenarioEditor.test.tsx src/features/decisions/RecommendationPanel.test.tsx src/features/decisions/DecisionDialog.test.tsx src/features/decisions/AuditDrawer.test.tsx src/app/AppShell.test.tsx
npm run build
```

Expected: all focused component tests pass and build succeeds.

- [ ] **Step 15: Commit the command-workspace slice**

```bash
git add frontend/src/features/planning/CommandWorkspace.tsx frontend/src/features/planning/CommandWorkspace.test.tsx frontend/src/features/planning/CommandDock.tsx frontend/src/features/planning/CommandDock.test.tsx frontend/src/features/planning/SelectedObjectCard.tsx frontend/src/features/planning/SelectedObjectCard.test.tsx frontend/src/features/planning/DetailsDrawer.tsx frontend/src/features/planning/DetailsDrawer.test.tsx frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx frontend/src/features/incidents/IncidentQueue.tsx frontend/src/features/incidents/IncidentQueue.test.tsx frontend/src/features/incidents/IncidentDetails.tsx frontend/src/features/scenarios/ScenarioPlanningPanel.tsx frontend/src/features/scenarios/ScenarioPlanningPanel.test.tsx frontend/src/features/scenarios/ScenarioEditor.tsx frontend/src/features/scenarios/ScenarioEditor.test.tsx frontend/src/features/decisions/RecommendationPanel.tsx frontend/src/features/decisions/RecommendationPanel.test.tsx frontend/src/features/decisions/DecisionDialog.tsx frontend/src/features/decisions/DecisionDialog.test.tsx frontend/src/features/decisions/AuditDrawer.tsx frontend/src/features/decisions/AuditDrawer.test.tsx frontend/src/App.css
git commit -m "feat: introduce the map-first command workspace"
```

---

### Task 12: Harden Errors, Focus, Reduced Motion, and Responsive Parity

**Files:**
- Modify: `frontend/src/features/planning/CommandWorkspace.tsx`
- Modify: `frontend/src/features/planning/CommandWorkspace.test.tsx`
- Modify: `frontend/src/features/planning/CommandDock.tsx`
- Modify: `frontend/src/features/planning/CommandDock.test.tsx`
- Modify: `frontend/src/features/planning/DetailsDrawer.tsx`
- Modify: `frontend/src/features/planning/DetailsDrawer.test.tsx`
- Modify: `frontend/src/features/map/OperationsMap.tsx`
- Modify: `frontend/src/features/map/OperationsMap.test.tsx`
- Modify: `frontend/src/features/decisions/DecisionDialog.tsx`
- Modify: `frontend/src/features/decisions/DecisionDialog.test.tsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/test/setup.ts`

- [ ] **Step 1: Add failing failure-preservation tests**

Cover the approved failure matrix:

- road bbox query fails: preserve wind/availability/relocation/assignment changes, disable only road selection, and show Retry roads;
- relocation validation fails: retain the draft marker and name the resource plus snap/region problem;
- locked assignment validation fails: retain the pair and name the resource, destination, and failed constraint;
- scenario creation fails before a version exists: keep all draft values and offer Run again/Edit assumptions;
- recommendation fails after version creation: keep draft plus prior result, and Retry reuses the version;
- stale recommendation: visually demote routes and disable approve/edit;
- incident freshness changes: present Refresh and discard versus Stay on this draft; and
- timeout/network failure: last valid result remains labelled Previous result, never Current.

```typescript
server.use(http.post("*/api/scenarios/:id/versions", () =>
  HttpResponse.json({
    error: {
      code: "scenario_invalid",
      message: "Scenario planning inputs are invalid",
      details: {
        constraint: "snap_distance",
        resourceId: "sim-engine-1",
        limit: 5000,
        technicalMessage: "resource relocation sim-engine-1 is more than 5000 meters from a routable road",
      },
    },
  }, { status: 422 }),
));
await user.click(screen.getByRole("button", { name: /run plan/i }));
expect(await screen.findByText(/engine — butte meadows.*routable road/i)).toBeVisible();
expect(screen.getByText(/1 draft change/i)).toBeVisible();
expect(getDraftMarker("sim-engine-1")).toBeDefined();
```

- [ ] **Step 2: Add failing keyboard and focus tests**

Using `userEvent.tab()` and Escape, assert:

1. all map tools, incident choices, card actions, dock controls, and drawer controls receive visible logical focus;
2. opening the drawer focuses its heading and closing returns to its opener;
3. incident-switch, Clear draft, resource-drop choice, and decision dialogs move focus inside and restore it on Cancel;
4. after PLAN READY focus moves to the result status only after the explicit Run action;
5. after a recorded decision focus moves to “Decision recorded” and Audit is the next relevant action;
6. Escape cancels only the active transient map/drop action, never the full draft; and
7. map selections are announced through a polite live region without stealing focus.

```typescript
const opener = screen.getByRole("button", { name: /details and evidence/i });
await user.click(opener);
expect(screen.getByRole("heading", { name: /details and evidence/i })).toHaveFocus();
await user.keyboard("{Escape}");
expect(opener).toHaveFocus();

await user.click(screen.getByRole("button", { name: /run plan/i }));
expect(await screen.findByText("PLAN READY")).toHaveFocus();
```

- [ ] **Step 3: Add failing noncolor and reduced-motion tests**

Mock `matchMedia("(prefers-reduced-motion: reduce)")`. Assert route animation/transition is disabled while every final route remains visible. Assert legends/status text distinguish Observed, Draft, Recommendation, Manual, Optimized, Unreachable, Uncovered, and Stale without relying on CSS color values.

```typescript
mockMediaQuery("(prefers-reduced-motion: reduce)", true);
render(<CommandWorkspace {...props} />);
expect(lastOperationsMapProps().reducedMotion).toBe(true);
for (const label of [
  "Observed", "Draft", "Recommendation", "Manual", "Optimized",
  "Unreachable", "Uncovered", "Stale",
]) {
  expect(screen.getByText(label)).toBeVisible();
}
```

- [ ] **Step 4: Run focused tests and verify the red state**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/CommandWorkspace.test.tsx src/features/planning/CommandDock.test.tsx src/features/planning/DetailsDrawer.test.tsx src/features/map/OperationsMap.test.tsx src/features/decisions/DecisionDialog.test.tsx
```

Expected: new failure, focus, and motion assertions fail.

- [ ] **Step 5: Implement scoped recovery surfaces**

Render errors beside the affected control and in a polite/alert region as appropriate. For `scenario_invalid`, read the structured `ApiClientError.details`, resolve `resourceId`/`destinationId` through incident display-label maps, and format a constraint-specific operational message. Use a generic safe message for unknown/internal errors. Put the raw backend message, IDs, field, and technical constraint data in a nested disclosure only. Never clear the draft in an error handler.

For stale snapshot, do not silently replace the draft basis. “Refresh and discard” resets session/draft to the current incident snapshot. “Stay on this draft” closes the prompt but leaves Run/decision disabled with a persistent stale-basis explanation.

```typescript
const operationalError = scenarioErrorDetails === null
  ? safeCommandMessage(commandError)
  : formatScenarioConstraint({
      details: scenarioErrorDetails,
      resourceLabel: resourceLabels.get(scenarioErrorDetails.resourceId ?? ""),
      destinationLabel: destinationLabels.get(scenarioErrorDetails.destinationId ?? ""),
    });

<p role="alert">{operationalError}</p>
<details>
  <summary>Technical error details</summary>
  <pre>{JSON.stringify(commandErrorDetails, null, 2)}</pre>
</details>
```

- [ ] **Step 6: Implement deliberate focus management**

Use element refs and effects tied to explicit user-triggered transitions. For incident-switch, Clear draft, resource-drop choice, and decision dialogs, call native `dialog.showModal()` after mount, handle the `cancel` event, and call `dialog.close()` on every terminal action; do not emulate modality with only an `open` attribute. Add the minimal jsdom `showModal`/`close` test shim in `test/setup.ts`. Details & evidence remains a nonmodal `<aside>`. Give confirmation/result headings `tabIndex={-1}`. Restore focus only if the original invoker is still connected. Do not add a focus-management dependency.

```typescript
useEffect(() => {
  const dialog = dialogRef.current;
  if (dialog === null) return;
  const cancel = (event: Event): void => {
    event.preventDefault();
    onCancel();
  };
  dialog.addEventListener("cancel", cancel);
  if (!dialog.open) dialog.showModal();
  return () => dialog.removeEventListener("cancel", cancel);
}, [onCancel]);

const closeDialog = (): void => {
  dialogRef.current?.close();
  if (invokerRef.current?.isConnected) invokerRef.current.focus();
};
```

- [ ] **Step 7: Finish accessible sizing and styling**

Ensure primary buttons/toggles have `min-block-size: 44px` and `min-inline-size: 44px`; visible `:focus-visible` outlines meet the dark-chrome contrast. Map object hit layers are generous, but the drawer equivalents remain the authoritative keyboard/touch path. Add icon/text/dash reinforcement for all status colors.

Under 1024px, ensure no fixed overlay obscures the map or command controls, horizontal assignment/comparison tables use bounded overflow, and drawers become in-flow sections. Hide no operational action solely because of viewport size.

```css
.command-workspace button,
.command-workspace input[type="checkbox"] + label {
  min-block-size: 44px;
  min-inline-size: 44px;
}
.command-workspace :focus-visible {
  outline: 3px solid #8de8ff;
  outline-offset: 3px;
}
.details-table-scroll { max-inline-size: 100%; overflow-x: auto; }
```

- [ ] **Step 8: Honor reduced motion**

Read the media query with a tiny local hook in `CommandWorkspace` and pass a boolean to `OperationsMap`. Disable route drawing transitions, pulsing markers, smooth drawer transitions, and nonessential animation when true. Do not remove progress text or final visual states.

```typescript
function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = (): void => setReduced(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}
```

Set `data-motion={reducedMotion ? "reduced" : "full"}` on the workspace root and use that same state for CSS and the `OperationsMap` prop; this is runtime presentation state, not a test-only hook.

- [ ] **Step 9: Run focused and full frontend checks**

Run:

```bash
cd frontend
npm test -- --run src/features/planning/CommandWorkspace.test.tsx src/features/planning/CommandDock.test.tsx src/features/planning/DetailsDrawer.test.tsx src/features/map/OperationsMap.test.tsx src/features/decisions/DecisionDialog.test.tsx
npm test -- --run
npm run lint
npm run build
```

Expected: focused and full tests, oxlint, TypeScript, and Vite build pass.

- [ ] **Step 10: Commit the hardening slice**

```bash
git add frontend/src/features/planning/CommandWorkspace.tsx frontend/src/features/planning/CommandWorkspace.test.tsx frontend/src/features/planning/CommandDock.tsx frontend/src/features/planning/CommandDock.test.tsx frontend/src/features/planning/DetailsDrawer.tsx frontend/src/features/planning/DetailsDrawer.test.tsx frontend/src/features/map/OperationsMap.tsx frontend/src/features/map/OperationsMap.test.tsx frontend/src/features/decisions/DecisionDialog.tsx frontend/src/features/decisions/DecisionDialog.test.tsx frontend/src/App.css frontend/src/test/setup.ts
git commit -m "feat: harden command workspace interactions"
```

---

### Task 13: Replace the Stale Demo Journey and Verify the Whole Redesign

**Files:**
- Delete: `frontend/e2e/replay-decision.spec.ts`
- Create: `frontend/e2e/command-workspace.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Replace the obsolete scroll-heavy browser test**

Configure two Playwright projects:

```typescript
projects: [
  { name: "desktop-1280", use: { viewport: { width: 1280, height: 720 } } },
  { name: "compact-1024", use: { viewport: { width: 1024, height: 768 } } },
],
```

Add `"test:e2e": "playwright test"` to package scripts. Delete the old test rather than maintaining two contradictory journeys.

Scope the direct-map test to `desktop-1280` and the keyboard test to `compact-1024` with `testInfo.project.name`; scope reduced-motion/fallback checks explicitly as well. Each intended viewport still completes the full operator workflow once, without running every journey redundantly in both projects.

- [ ] **Step 2: Write the direct-map desktop journey**

The seeded Park Fire test must:

1. load with no console warning/error or `pageerror`;
2. show Park Fire, Priority score/top driver, safety notice, next action, map, basemap attribution, and replay-unavailable explanation in the first viewport;
3. project the known simulated resource coordinate into the MapLibre canvas, drag it, and choose Relocate in the contextual card;
4. verify the dock says one draft change and no POST occurred before Run;
5. Run plan once and wait for PLAN READY;
6. verify route segment count is nonzero and uncovered/unreachable exceptions remain textually visible;
7. Approve with a note;
8. open the matching audit event and verify relocation, assignment source, actor, note, scenario version, snapshot, and algorithm provenance; and
9. assert the document did not need to scroll through evidence to complete the primary workflow.

Keep the projection helper inside the test file and derive from the canvas box, map center, zoom, and Web Mercator math. Do not add production-only test hooks.

Add `expectInViewport(locator)` using `boundingBox()` and the project viewport. Before and after select/drag, Run, PLAN READY, Approve, and Audit, assert the relevant primary controls/cards are fully inside the viewport and `document.scrollingElement?.scrollTop === 0`. This catches Playwright auto-scrolling during an earlier action rather than checking only the final position.

```typescript
async function expectInViewport(locator: Locator, page: Page): Promise<void> {
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
  expect(await page.evaluate(() => document.scrollingElement?.scrollTop ?? 0)).toBe(0);
}

function worldPoint([longitude, latitude]: readonly [number, number], zoom: number) {
  const scale = 512 * 2 ** zoom;
  const sine = Math.sin(latitude * Math.PI / 180);
  return {
    x: ((longitude + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)) * scale,
  };
}

async function dragSeededResource(
  page: Page,
  coordinate: readonly [number, number],
): Promise<void> {
  const canvas = page.locator(".maplibregl-canvas");
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  const center = worldPoint([-121.58, 39.79], 8);
  const resource = worldPoint(coordinate, 8);
  const start = {
    x: box!.x + box!.width / 2 + resource.x - center.x,
    y: box!.y + box!.height / 2 + resource.y - center.y,
  };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 48, start.y - 24, { steps: 8 });
  await page.mouse.up();
}

async function runSeededPlan(page: Page): Promise<void> {
  await page.getByRole("button", { name: /run plan/i }).click();
  await expect(page.getByText("PLAN READY")).toBeVisible();
}

test("operator drafts on the map and approves the plan", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280");
  await page.goto("/");
  await expectInViewport(page.getByRole("button", { name: /move resource/i }), page);
  await page.getByRole("button", { name: /move resource/i }).click();
  await dragSeededResource(page, [-121.6064, 39.754192]);
  await page.getByRole("button", { name: /relocate here/i }).click();
  await page.getByRole("button", { name: /run plan/i }).click();
  await expectInViewport(page.getByText("PLAN READY"), page);
  await page.getByRole("button", { name: /approve plan/i }).click();
  await page.getByLabel(/operator note/i).fill("Portfolio demo approval");
  await page.getByRole("button", { name: /^approve$/i }).click();
  await page.getByRole("button", { name: /audit/i }).click();
  await expectInViewport(page.getByRole("heading", { name: /audit event/i }), page);
});
```

- [ ] **Step 3: Write the keyboard-equivalent compact journey**

At 1024×768, complete the same workflow without canvas pointer gestures:

1. navigate incident rail and open Details & evidence by keyboard;
2. set a relocation coordinate, locked assignment, wind, availability, and a searched road closure through form controls;
3. Apply draft changes, close the drawer, and Run plan;
4. inspect PLAN READY and recommendation technical evidence;
5. approve with keyboard only; and
6. open Audit and return focus correctly.

Assert the map, summary, dock, and result remain visible/operable at every checkpoint with `expectInViewport`; page scroll remains zero while drawer-internal scrolling is allowed. Tables do not expand the page width, and every primary control’s computed block/inline size is at least 44px.

```typescript
test("keyboard workflow reaches matching audit", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "compact-1024");
  await page.goto("/");
  await page.getByRole("button", { name: /details and evidence/i }).press("Enter");
  await page.getByLabel(/relocation resource/i).selectOption("sim-engine-butte-meadows");
  await page.getByLabel(/relocation longitude/i).fill("-121.552683");
  await page.getByLabel(/relocation latitude/i).fill("40.07531");
  await page.getByLabel(/locked resource/i).selectOption("sim-engine-butte-meadows");
  await page.getByLabel(/locked destination/i).selectOption("census-place-0609318");
  await page.getByLabel(/wind speed/i).fill("8");
  await page.getByLabel(/wind direction/i).fill("225");
  await page.getByLabel(/sim-engine-2 availability/i).uncheck();
  await page.getByLabel(/search road edges/i).fill("Calistoga Drive");
  await page.getByRole("button", { name: /search roads/i }).press("Enter");
  await page.getByRole("checkbox", { name: /Calistoga Drive/i }).first().check();
  await page.getByRole("button", { name: /apply draft changes/i }).press("Enter");
  await page.getByRole("button", { name: /close details/i }).press("Enter");
  await page.getByRole("button", { name: /run plan/i }).press("Enter");
  await expectInViewport(page.getByText("PLAN READY"), page);
  await page.getByRole("button", { name: /approve plan/i }).press("Enter");
  await page.getByLabel(/operator note/i).fill("Keyboard approval");
  await page.getByRole("button", { name: /^approve$/i }).press("Enter");
  await page.getByRole("button", { name: /audit/i }).press("Enter");
  await expect(page.getByRole("heading", { name: /audit event/i })).toBeVisible();
});
```

- [ ] **Step 4: Add reduced-motion and basemap-fallback browser checks**

Use `page.emulateMedia({ reducedMotion: "reduce" })` and verify routes render without animation. In a separate test, abort the external style request before load; verify the inline fallback appears, operational markers/draft/recommendation layers still work, and the console remains clean. Do not require external network success for the fallback test.

```typescript
test("fallback basemap retains operational layers", async ({ page }) => {
  await page.route("https://tiles.openfreemap.org/styles/positron*", (route) => route.abort());
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.getByRole("list", { name: /map legend/i })).toContainText("Observed");
  await runSeededPlan(page);
  await expect(page.getByText("PLAN READY")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("reduced motion keeps final routes visible", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await runSeededPlan(page);
  await expect(page.getByText(/recommendation routes/i)).toBeVisible();
  await expect(page.locator(".command-workspace")).toHaveAttribute("data-motion", "reduced");
});
```

- [ ] **Step 5: Run the new browser suite and verify the red/green transition**

Before finishing implementation, run once and record the expected failures from missing selectors/behavior. After Tasks 11–12 are complete, run:

```bash
cd frontend
npm run test:e2e
```

Expected: both viewport projects, reduced-motion, and fallback tests pass. Playwright artifacts remain under `/tmp/wildfireops-playwright`; do not add portfolio screenshots or video to this track.

- [ ] **Step 6: Run all backend verification**

Run:

```bash
cd backend
uv run alembic upgrade head
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

Expected: migration reaches head; full pytest, Ruff, and mypy pass.

- [ ] **Step 7: Run all frontend verification**

Run:

```bash
cd frontend
npm test -- --run
npm run lint
npm run build
npm run test:e2e
```

Expected: unit/component/API suites, oxlint, build, and browser acceptance pass.

- [ ] **Step 8: Perform live browser acceptance**

With the replay preview running, inspect `http://localhost:5173/` at 1280×720 and 1024×768. Verify roads/place labels and fire/resource/asset/draft/recommendation overlays are simultaneously visible, attribution is visible, map pan/zoom/selection/drag work, focus is visible, the drawer returns focus, and the console has no warnings/errors. Exercise select incident → draft → run → recommendation → approve → audit without opening evidence first.

- [ ] **Step 9: Commit the replacement browser journey**

```bash
git add frontend/e2e/command-workspace.spec.ts frontend/e2e/replay-decision.spec.ts frontend/playwright.config.ts frontend/package.json
git commit -m "test: verify the map-first operator journey"
```

- [ ] **Step 10: Request independent review and finish the branch**

Use `superpowers:requesting-code-review` against the merged baseline and address all correctness/accessibility findings. Re-run Steps 6–8 after any change. Then use `superpowers:finishing-a-development-branch`; do not merge or push without following the user’s current GitHub instructions.

---

## Deferred Tracks and Completion Boundary

This plan completes only the map-first redesign track. It does not claim that the original WildfireOps project is portfolio-ready. After this branch lands, write separate implementation plans for:

1. temporal replay repair plus dedicated degraded-mode and repeatable performance proof; and
2. CI, production Docker image, deployment configuration, public deployment, README/architecture documentation, screenshots, benchmark report, and demo video.

Deployment and publication remain deferred until the user explicitly resumes that work.
