# Park Fire Decision Exercise Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-first, three-checkpoint Park Fire exercise backend:
versioned definition loading, shared cross-incident task optimization,
deterministic explanations, isolated guided sessions, a bounded read-only
sandbox, audit data, and a committed golden fixture.

**Architecture:** Add a bounded exercise workflow beside the existing incident-scoped Live Monitor workflow. A versioned definition inside the replay package materializes each checkpoint; a new task planner reuses `ResourceUnit`, `RouteResult`, RoadGraph routing, OR-Tools conventions, idempotency, and transaction patterns without changing existing scenario or recommendation contracts. Exercise definitions stay in files while sessions, immutable plan runs, and append-only events live in PostgreSQL.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy asyncio, PostgreSQL/PostGIS, Alembic, NetworkX/OSM RoadGraph, OR-Tools CP-SAT, pytest, pytest-asyncio, Hypothesis, HTTPX.

## Global Constraints

- Project 1 only: do not rebuild frontend components in this plan.
- Prove the guided golden journey before adding the bounded sandbox endpoint;
  then hand both stable contracts to the Claude Code UI rebuild.
- Historical observations and simulated exercise assumptions must remain separately labeled.
- No LLM or nondeterministic explanation generation.
- Keep existing incident-scoped scenarios, recommendations, decisions, audit, and Live Monitor API contracts unchanged.
- Keep `solve_allocation()` unchanged; add a separate task-planning operation.
- Identical canonical inputs must produce identical semantic outputs.
- Use one CP-SAT worker, random seed `0`, integer objective coefficients, and a two-second solver limit.
- Supported objectives are exactly `fastest-response`, `protect-critical-services`, and `maximize-population-coverage`.
- Session statuses are exactly `active`, `completed`, and `expired`.
- Local sessions expire 24 hours after creation.
- Session creation requires an idempotency key; every mutation after creation requires an idempotency key and expected session version.
- Unreachable, incompatible, late, and capacity-constrained tasks are valid uncovered outcomes, not server errors.
- Public hosting, authentication, secure session credentials, cleanup jobs, and retention policy are outside this plan.
- Do not add dependencies; use the installed standard library, Pydantic, SQLAlchemy, OR-Tools, pytest, and Hypothesis.
- Use exact historical source identities and source citations in committed fixtures; never invent a real facility name or coordinate.
- Exercise observation references use composite normalized identities
  (`source_name:source_record_id`): `detectionIdentities` and
  `historicalWeatherIdentity`. Exercise assets either exactly mirror a verified
  static community or pin a validated OpenStreetMap `node|way|relation` record
  in the manifest-hashed definition; they do not alter Live Monitor fixtures.

---

## Planned file structure

### New backend files

- `backend/src/wildfireops/replay/exercise.py` — strict immutable exercise-definition schema, package loading, historical-reference validation, and canonical digest.
- `backend/src/wildfireops/decision/task_optimizer.py` — task demand, locked assignment, objective configuration, CP-SAT solve, and deterministic result types.
- `backend/src/wildfireops/decision/task_explanations.py` — causal codes and deterministic plan-difference explanations.
- `backend/src/wildfireops/application/exercises.py` — transport-neutral session projections, repository protocol, command services, transition validation, and error types.
- `backend/src/wildfireops/application/exercise_planning.py` — checkpoint materialization, routing, penalty calculation, task-plan generation, override validation, and plan serialization.
- `backend/src/wildfireops/persistence/exercise_models.py` — SQLAlchemy session, plan-run, and event models.
- `backend/src/wildfireops/persistence/exercises.py` — session-bound repository adapter.
- `backend/src/wildfireops/api/schemas/exercises.py` — request and response schemas.
- `backend/src/wildfireops/api/routes/exercises.py` — exercise metadata, session, command, audit, and debrief routes.
- `backend/migrations/versions/0005_exercise_sessions.py` — three exercise tables and constraints.
- `backend/tests/unit/replay/test_exercise.py` — definition parser and validation checks.
- `backend/tests/unit/decision/test_task_optimizer.py` — focused task-planner examples.
- `backend/tests/unit/decision/test_task_optimizer_properties.py` — invariant coverage.
- `backend/tests/unit/decision/test_task_explanations.py` — causal explanation checks.
- `backend/tests/unit/application/test_exercises.py` — command transitions and atomic validation using a fake repository.
- `backend/tests/unit/application/test_exercise_planning.py` — checkpoint materialization, routing, consequences, and override validation.
- `backend/tests/integration/persistence/test_exercises.py` — PostgreSQL constraints, locking, isolation, and immutability.
- `backend/tests/integration/api/test_exercises.py` — API contract, idempotency, conflict, expiry, audit, and debrief.
- `backend/tests/integration/replay/test_park_fire_exercise_golden.py` — committed package and semantic golden journey.
- `data/replay/park-fire/exercise.json` — approved three-checkpoint definition, pinned public facility references, and simulated resource inventory.
- `data/replay/park-fire/exercise_golden_outputs.json` — semantic golden output.

### Existing files modified

- `backend/src/wildfireops/replay/loader.py` — expose already-verified referenced bytes without rereading files.
- `backend/src/wildfireops/application/commands.py` — provide exercise command and query services.
- `backend/src/wildfireops/api/dependencies.py` — exercise service dependencies.
- `backend/src/wildfireops/api/command_errors.py` — stable exercise error mapping.
- `backend/src/wildfireops/main.py` — load the optional definition and register the router.
- `backend/migrations/env.py` — import exercise models for Alembic metadata.
- `backend/tests/integration/conftest.py` — truncate new exercise tables.
- `backend/tests/unit/replay/test_park_fire_package.py` — assert definition and disclosure integrity.
- `data/replay/park-fire/manifest.json` — hash the new and changed files.
- `README.md` — document local exercise startup and historical/simulated boundary.

---

### Task 1: Load and validate immutable exercise definitions

**Files:**
- Create: `backend/src/wildfireops/replay/exercise.py`
- Modify: `backend/src/wildfireops/replay/loader.py`
- Test: `backend/tests/unit/replay/test_exercise.py`

**Interfaces:**
- Consumes: `ReplayLoader.manifest`, `ReplayLoader.static_data`, normalized observation identities, and verified manifest file bytes.
- Produces: `ExerciseDefinition`, `ExerciseCheckpoint`, `ExerciseIncident`, `ExerciseTask`, `ExerciseResource`, `ExerciseDisruption`, `ExerciseFieldReport`, `ObjectivePreset`, `load_exercise_definition(loader)`, and `exercise_definition_digest(definition)`.

- [ ] **Step 1: Write the failing verified-file access test**

```python
# backend/tests/unit/replay/test_exercise.py
from pathlib import Path

import pytest

from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt


FIXTURE = Path("tests/fixtures/replay-small")


def test_loader_returns_only_manifest_verified_file_bytes() -> None:
    loader = ReplayLoader(FIXTURE)

    assert loader.referenced_file("fire_detections.jsonl").startswith(b"{")
    with pytest.raises(
        ReplayPackageCorrupt,
        match="file is not referenced by manifest: absent.json",
    ):
        loader.referenced_file("absent.json")
```

- [ ] **Step 2: Run the test and verify the missing method**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_exercise.py::test_loader_returns_only_manifest_verified_file_bytes -v
```

Expected: FAIL with `AttributeError: 'ReplayLoader' object has no attribute 'referenced_file'`.

- [ ] **Step 3: Retain verified bytes and expose a read-only accessor**

```python
# backend/src/wildfireops/replay/loader.py
from types import MappingProxyType

# At the end of manifest file verification in ReplayLoader.__init__:
self._file_contents = MappingProxyType(dict(file_contents))

def referenced_file(self, filename: str) -> bytes:
    try:
        return self._file_contents[filename]
    except KeyError:
        raise ReplayPackageCorrupt(
            f"file is not referenced by manifest: {filename}"
        ) from None
```

- [ ] **Step 4: Add the immutable Pydantic definition contract**

```python
# backend/src/wildfireops/replay/exercise.py
import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt


type ObjectivePreset = Literal[
    "fastest-response",
    "protect-critical-services",
    "maximize-population-coverage",
]
type ProvenanceKind = Literal["historical", "exercise"]


class ExerciseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            word if index == 0 else word.title()
            for index, word in enumerate(value.split("_"))
        ),
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class Point(ExerciseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class ExerciseResource(ExerciseModel):
    resource_id: str = Field(min_length=1)
    resource_type: Literal["engine", "evacuation-bus", "medical-team", "road-crew"]
    capabilities: frozenset[str] = Field(min_length=1)
    capacity: int = Field(gt=0)
    available: bool = True
    position: Point
    provenance: Literal["exercise"] = "exercise"


class ExerciseAsset(ExerciseModel):
    asset_id: str = Field(min_length=1)
    asset_kind: Literal[
        "community",
        "hospital",
        "shelter",
        "communications",
        "power-substation",
        "road-corridor",
    ]
    name: str = Field(min_length=1)
    position: Point
    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    citation_url: str = Field(pattern=r"^https://")
    provenance: Literal["historical"] = "historical"


class ExerciseTask(ExerciseModel):
    task_id: str = Field(min_length=1)
    incident_key: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    task_type: Literal[
        "community-evacuation",
        "hospital-support",
        "shelter-transport",
        "communications-protection",
        "power-substation-protection",
        "corridor-clearing",
    ]
    required_capability: str = Field(min_length=1)
    required_capacity: int = Field(gt=0)
    deadline_minutes: int = Field(gt=0)
    affected_population: int = Field(ge=0)
    critical_service: bool
    base_priority: int = Field(ge=0)
    provenance: Literal["exercise"] = "exercise"


class ExerciseIncident(ExerciseModel):
    incident_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provenance: ProvenanceKind
    detection_identities: tuple[str, ...] = ()
    simulated_position: Point | None = None

    @model_validator(mode="after")
    def validate_geometry_source(self) -> "ExerciseIncident":
        if self.provenance == "historical":
            if not self.detection_identities:
                raise ValueError("historical incident requires detection identities")
            if self.simulated_position is not None:
                raise ValueError("historical incident must not define simulated position")
        else:
            if self.detection_identities:
                raise ValueError(
                    "exercise incident must not define historical detection identities"
                )
            if self.simulated_position is None:
                raise ValueError("exercise incident requires simulated position")
        return self


class ExerciseDisruption(ExerciseModel):
    wind_speed_mps: float = Field(gt=0)
    wind_direction_degrees: float = Field(ge=0, lt=360)
    closed_edge_ids: tuple[str, ...] = ()
    provenance: Literal["exercise"] = "exercise"


class ExerciseFieldReport(ExerciseModel):
    report_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    provenance: Literal["exercise"] = "exercise"


class ExerciseCheckpoint(ExerciseModel):
    checkpoint_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    situation_summary: str = Field(min_length=1)
    decision_prompt: str = Field(min_length=1)
    reference_at: datetime
    historical_weather_identity: str = Field(min_length=1)
    incidents: tuple[ExerciseIncident, ...]
    tasks: tuple[ExerciseTask, ...]
    disruption: ExerciseDisruption | None = None
    field_reports: tuple[ExerciseFieldReport, ...] = ()


class ObjectiveWeights(ExerciseModel):
    travel_weight: int = Field(ge=0)
    base_priority_weight: int = Field(ge=0)
    critical_service_weight: int = Field(ge=0)
    population_divisor: int = Field(gt=0)
    population_weight: int = Field(ge=0)


class SandboxControls(ExerciseModel):
    checkpoint_keys: frozenset[str] = Field(min_length=1)
    closure_edge_ids: frozenset[str]
    wind_presets: dict[str, ExerciseDisruption]
    priority_multipliers: dict[
        Literal["standard", "elevated", "urgent"],
        int,
    ]


class ExerciseDefinition(ExerciseModel):
    exercise_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    replay_package_id: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    objectives: dict[ObjectivePreset, ObjectiveWeights]
    assets: tuple[ExerciseAsset, ...]
    resources: tuple[ExerciseResource, ...]
    checkpoints: tuple[ExerciseCheckpoint, ...] = Field(min_length=3, max_length=3)
    sandbox: SandboxControls
    safety_statement: str = Field(min_length=1)


def load_exercise_definition(
    loader: ReplayLoader,
    filename: str = "exercise.json",
) -> ExerciseDefinition | None:
    if filename not in loader.manifest.files:
        return None
    try:
        raw = json.loads(
            loader.referenced_file(filename),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        definition = ExerciseDefinition.model_validate(raw)
    except (UnicodeDecodeError, ValueError, ValidationError) as error:
        raise ReplayPackageCorrupt(
            f"{filename}: invalid exercise definition: {error}"
        ) from error
    _validate_definition_references(definition, loader)
    return definition


def exercise_definition_digest(definition: ExerciseDefinition) -> str:
    payload = json.dumps(
        definition.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return sha256(payload).hexdigest()
```

- [ ] **Step 5: Add strict cross-reference and ordering validation**

```python
# backend/src/wildfireops/replay/exercise.py
def _validate_definition_references(
    definition: ExerciseDefinition,
    loader: ReplayLoader,
) -> None:
    if definition.replay_package_id != loader.manifest.package_id:
        raise ReplayPackageCorrupt(
            "exercise.json: replayPackageId does not match manifest package_id"
        )
    graph = loader.manifest.road_graph
    if graph is None or definition.graph_version != graph.graph_version:
        raise ReplayPackageCorrupt(
            "exercise.json: graphVersion does not match replay graph"
        )
    if set(definition.objectives) != {
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    }:
        raise ReplayPackageCorrupt(
            "exercise.json: objectives must define all approved presets"
        )
    if loader.static_data is None:
        raise ReplayPackageCorrupt(
            "exercise.json: exercise requires replay static data"
        )
    asset_ids = [item.asset_id for item in definition.assets]
    _unique(asset_ids, "assetId")
    west, south, east, north = loader.manifest.region
    for asset in definition.assets:
        if not (
            west <= asset.position.longitude <= east
            and south <= asset.position.latitude <= north
        ):
            raise ReplayPackageCorrupt(
                f"exercise.json: asset is outside replay bounds: {asset.asset_id}"
            )
    observations = tuple(loader.iter_until(loader.manifest.end_at))
    detection_ids = {
        item.source_record_id
        for item in observations
        if isinstance(item, NormalizedObservation)
    }
    weather_ids = {
        item.source_record_id
        for item in observations
        if isinstance(item, WeatherObservation)
    }
    resource_ids = [item.resource_id for item in definition.resources]
    _unique(resource_ids, "resourceId")
    _unique(
        [item.checkpoint_key for item in definition.checkpoints],
        "checkpointKey",
    )
    checkpoint_keys = {
        item.checkpoint_key for item in definition.checkpoints
    }
    unknown_sandbox_checkpoints = sorted(
        definition.sandbox.checkpoint_keys - checkpoint_keys
    )
    if unknown_sandbox_checkpoints:
        raise ReplayPackageCorrupt(
            "exercise.json: unknown sandbox checkpoint: "
            f"{unknown_sandbox_checkpoints[0]}"
        )
    if set(definition.sandbox.priority_multipliers) != {
        "standard",
        "elevated",
        "urgent",
    }:
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox priority multipliers must define "
            "standard, elevated, and urgent"
        )
    if any(
        value <= 0
        for value in definition.sandbox.priority_multipliers.values()
    ):
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox priority multipliers must be positive"
        )
    if not definition.sandbox.wind_presets:
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox requires at least one wind preset"
        )
    if any(
        preset.closed_edge_ids
        for preset in definition.sandbox.wind_presets.values()
    ):
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox wind presets cannot define road closures"
        )
    times = [item.reference_at for item in definition.checkpoints]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ReplayPackageCorrupt(
            "exercise.json: checkpoints must be strictly time ordered"
        )
    for checkpoint in definition.checkpoints:
        incident_keys = [item.incident_key for item in checkpoint.incidents]
        task_ids = [item.task_id for item in checkpoint.tasks]
        report_ids = [item.report_id for item in checkpoint.field_reports]
        _unique(incident_keys, f"{checkpoint.checkpoint_key}.incidentKey")
        _unique(task_ids, f"{checkpoint.checkpoint_key}.taskId")
        _unique(report_ids, f"{checkpoint.checkpoint_key}.reportId")
        if checkpoint.historical_weather_identity not in weather_ids:
            raise ReplayPackageCorrupt(
                "exercise.json: unknown historical weather identity: "
                f"{checkpoint.historical_weather_identity}"
            )
        for incident in checkpoint.incidents:
            unknown = sorted(
                set(incident.detection_identities) - detection_ids
            )
            if unknown:
                raise ReplayPackageCorrupt(
                    f"exercise.json: unknown historical detection identity: {unknown[0]}"
                )
        for task in checkpoint.tasks:
            if task.incident_key not in incident_keys:
                raise ReplayPackageCorrupt(
                    f"exercise.json: task incident does not exist: {task.incident_key}"
                )
            if task.asset_id not in set(asset_ids):
                raise ReplayPackageCorrupt(
                    f"exercise.json: unknown asset ID: {task.asset_id}"
                )
            if not any(
                task.required_capability in resource.capabilities
                for resource in definition.resources
            ):
                raise ReplayPackageCorrupt(
                    "exercise.json: no resource supports capability: "
                    f"{task.required_capability}"
                )
        for report in checkpoint.field_reports:
            if report.task_id not in task_ids:
                raise ReplayPackageCorrupt(
                    f"exercise.json: field report task does not exist: "
                    f"{report.task_id}"
                )


def _unique(values: list[str], field: str) -> None:
    if len(values) != len(set(values)):
        raise ReplayPackageCorrupt(f"exercise.json: duplicate {field}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid JSON number: {value}")
```

- [ ] **Step 6: Add parser tests for the required failure boundaries**

Add table-driven cases to `backend/tests/unit/replay/test_exercise.py` that mutate a valid temporary `exercise.json` and manifest hash, then assert exact failures for:

```python
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda body: body.update(replayPackageId="wrong"), "replayPackageId"),
        (lambda body: body.update(graphVersion="wrong"), "graphVersion"),
        (
            lambda body: body["checkpoints"].reverse(),
            "checkpoints must be strictly time ordered",
        ),
        (
            lambda body: body["checkpoints"][0]["tasks"][0].update(
                assetId="unknown"
            ),
            "unknown asset ID: unknown",
        ),
        (
            lambda body: body["checkpoints"][0]["tasks"][0].update(
                requiredCapability="aircraft"
            ),
            "no resource supports capability: aircraft",
        ),
    ],
)
def test_definition_rejects_invalid_contract(
    exercise_package: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)
    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))
```

- [ ] **Step 7: Run the focused replay tests**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_loader.py tests/unit/replay/test_exercise.py -q
uv run ruff check src/wildfireops/replay/loader.py src/wildfireops/replay/exercise.py tests/unit/replay/test_exercise.py
uv run mypy src/wildfireops/replay/loader.py src/wildfireops/replay/exercise.py
```

Expected: all tests pass, Ruff reports no issues, and mypy reports success.

- [ ] **Step 8: Commit the definition boundary**

```bash
git add backend/src/wildfireops/replay/loader.py \
  backend/src/wildfireops/replay/exercise.py \
  backend/tests/unit/replay/test_exercise.py
git commit -m "feat(exercise): validate versioned exercise definitions"
```

---

### Task 2: Solve shared cross-incident task plans deterministically

**Files:**
- Create: `backend/src/wildfireops/decision/task_optimizer.py`
- Test: `backend/tests/unit/decision/test_task_optimizer.py`
- Test: `backend/tests/unit/decision/test_task_optimizer_properties.py`

**Interfaces:**
- Consumes: `ResourceUnit`, `RouteResult`, `RouteStatus`, checkpoint task data, objective weights, and locked assignments.
- Produces: `TaskDemand`, `TaskCandidateRoute`, `LockedTaskAssignment`, `TaskOptimizationRequest`, `TaskAssignment`, `TaskOptimizationResult`, `TASK_ALGORITHM_VERSION`, and `solve_task_plan(request)`.

- [ ] **Step 1: Write a failing cross-incident scarcity test**

```python
# backend/tests/unit/decision/test_task_optimizer.py
from wildfireops.decision.task_optimizer import (
    TaskCandidateRoute,
    TaskDemand,
    TaskOptimizationRequest,
    solve_task_plan,
)
from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


def route(minutes: float) -> RouteResult:
    return RouteResult(
        RouteStatus.REACHABLE,
        (),
        minutes * 1000,
        minutes,
        "graph-v1",
        "closures-v1",
    )


def test_shared_resource_goes_to_higher_penalty_task_across_incidents() -> None:
    engine = ResourceUnit(
        "engine-1",
        frozenset({"protect"}),
        1,
        True,
        -121.6,
        39.8,
    )
    tasks = (
        TaskDemand(
            "park-task",
            "park-fire",
            "asset-a",
            "protect",
            1,
            30,
            200,
        ),
        TaskDemand(
            "spot-task",
            "spot-fire",
            "asset-b",
            "protect",
            1,
            30,
            900,
        ),
    )
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(engine,),
            tasks=tasks,
            routes=(
                TaskCandidateRoute("engine-1", "park-task", route(2)),
                TaskCandidateRoute("engine-1", "spot-task", route(5)),
            ),
            locked_assignments=(),
            travel_weight=1,
            max_solver_seconds=2,
        )
    )

    assert [(item.resource_id, item.task_id) for item in result.assignments] == [
        ("engine-1", "spot-task")
    ]
    assert result.uncovered_task_ids == ("park-task",)
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_task_optimizer.py -v
```

Expected: collection fails with `ModuleNotFoundError: wildfireops.decision.task_optimizer`.

- [ ] **Step 3: Implement immutable task-planning types and validation**

```python
# backend/src/wildfireops/decision/task_optimizer.py
from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil, isfinite

from ortools.sat.python import cp_model

from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


TASK_ALGORITHM_VERSION = "task-allocation-v1"
_SOLUTION_STATUSES = frozenset({"FEASIBLE", "OPTIMAL"})


@dataclass(frozen=True, slots=True)
class TaskDemand:
    task_id: str
    incident_id: str
    asset_id: str
    required_capability: str
    required_capacity: int
    deadline_minutes: int
    uncovered_penalty: int

    def __post_init__(self) -> None:
        for field, value in (
            ("task_id", self.task_id),
            ("incident_id", self.incident_id),
            ("asset_id", self.asset_id),
            ("required_capability", self.required_capability),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be blank")
        if self.required_capacity <= 0:
            raise ValueError("required_capacity must be positive")
        if self.deadline_minutes <= 0:
            raise ValueError("deadline_minutes must be positive")
        if self.uncovered_penalty < 0:
            raise ValueError("uncovered_penalty must be nonnegative")


@dataclass(frozen=True, slots=True)
class TaskCandidateRoute:
    resource_id: str
    task_id: str
    route: RouteResult


@dataclass(frozen=True, slots=True)
class LockedTaskAssignment:
    resource_id: str
    task_id: str


@dataclass(frozen=True, slots=True)
class TaskOptimizationRequest:
    resources: tuple[ResourceUnit, ...]
    tasks: tuple[TaskDemand, ...]
    routes: tuple[TaskCandidateRoute, ...]
    locked_assignments: tuple[LockedTaskAssignment, ...]
    travel_weight: int
    max_solver_seconds: float = 2.0
    algorithm_version: str = TASK_ALGORITHM_VERSION


@dataclass(frozen=True, slots=True)
class TaskAssignment:
    resource_id: str
    task_id: str
    incident_id: str
    asset_id: str
    travel_minutes: float
    capacity: int


@dataclass(frozen=True, slots=True)
class TaskOptimizationResult:
    status: str
    assignments: tuple[TaskAssignment, ...]
    uncovered_task_ids: tuple[str, ...]
    unassigned_resource_ids: tuple[str, ...]
    travel_cost: int
    uncovered_task_penalty: int
    objective_value: int
    binding_constraints: tuple[str, ...]
    runtime_milliseconds: int
    algorithm_version: str
```

- [ ] **Step 4: Implement the minimal CP-SAT model**

```python
# backend/src/wildfireops/decision/task_optimizer.py
def solve_task_plan(request: TaskOptimizationRequest) -> TaskOptimizationResult:
    resources, tasks, routes, locks = _canonicalize(request)
    resources_by_id = {item.resource_id: item for item in resources}
    tasks_by_id = {item.task_id: item for item in tasks}
    eligible = {
        (route.resource_id, route.task_id): route
        for route in routes
        if _eligible(
            resources_by_id[route.resource_id],
            tasks_by_id[route.task_id],
            route.route,
        )
    }
    model = cp_model.CpModel()
    assigned = {
        pair: model.new_bool_var(f"assigned[{pair[0]},{pair[1]}]")
        for pair in eligible
    }
    covered = {
        task.task_id: model.new_bool_var(f"covered[{task.task_id}]")
        for task in tasks
    }
    for resource in resources:
        variables = [
            variable
            for (resource_id, _), variable in assigned.items()
            if resource_id == resource.resource_id
        ]
        if variables:
            model.add(sum(variables) <= 1)
    for task in tasks:
        capacity = [
            (resources_by_id[resource_id].capacity, variable)
            for (resource_id, task_id), variable in assigned.items()
            if task_id == task.task_id
        ]
        if not capacity:
            model.add(covered[task.task_id] == 0)
        else:
            model.add(
                sum(value * variable for value, variable in capacity)
                >= task.required_capacity * covered[task.task_id]
            )
            model.add(
                sum(variable for _, variable in capacity)
                <= len(capacity) * covered[task.task_id]
            )
    for lock in locks:
        variable = assigned.get((lock.resource_id, lock.task_id))
        if variable is None:
            raise ValueError(
                f"locked assignment is not eligible: "
                f"{lock.resource_id} -> {lock.task_id}"
            )
        model.add(variable == 1)
    travel_costs = {
        pair: request.travel_weight * ceil(route.route.travel_minutes)
        for pair, route in eligible.items()
    }
    model.minimize(
        sum(travel_costs[pair] * variable for pair, variable in assigned.items())
        + sum(
            task.uncovered_penalty * (1 - covered[task.task_id])
            for task in tasks
        )
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = request.max_solver_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.status_name(solver.solve(model))
    selected = (
        tuple(pair for pair, variable in assigned.items() if solver.value(variable))
        if status in _SOLUTION_STATUSES
        else ()
    )
    uncovered = (
        tuple(
            task.task_id
            for task in tasks
            if not solver.value(covered[task.task_id])
        )
        if status in _SOLUTION_STATUSES
        else tuple(task.task_id for task in tasks)
    )
    assignments = tuple(
        TaskAssignment(
            resource_id,
            task_id,
            tasks_by_id[task_id].incident_id,
            tasks_by_id[task_id].asset_id,
            eligible[(resource_id, task_id)].route.travel_minutes,
            resources_by_id[resource_id].capacity,
        )
        for resource_id, task_id in selected
    )
    selected_resources = {item.resource_id for item in assignments}
    travel_cost = sum(travel_costs[pair] for pair in selected)
    uncovered_penalty = sum(
        tasks_by_id[task_id].uncovered_penalty for task_id in uncovered
    )
    return TaskOptimizationResult(
        status=status if status in {*_SOLUTION_STATUSES, "INFEASIBLE", "UNKNOWN"} else "UNKNOWN",
        assignments=assignments,
        uncovered_task_ids=uncovered,
        unassigned_resource_ids=tuple(
            item.resource_id
            for item in resources
            if item.resource_id not in selected_resources
        ),
        travel_cost=travel_cost,
        uncovered_task_penalty=uncovered_penalty,
        objective_value=travel_cost + uncovered_penalty,
        binding_constraints=_binding_constraints(
            status,
            resources,
            tasks,
            routes,
            eligible,
            selected,
            uncovered,
        ),
        runtime_milliseconds=round(solver.wall_time * 1000),
        algorithm_version=request.algorithm_version,
    )
```

- [ ] **Step 5: Implement canonical validation and eligibility**

```python
# backend/src/wildfireops/decision/task_optimizer.py
def _canonicalize(
    request: TaskOptimizationRequest,
) -> tuple[
    tuple[ResourceUnit, ...],
    tuple[TaskDemand, ...],
    tuple[TaskCandidateRoute, ...],
    tuple[LockedTaskAssignment, ...],
]:
    if request.travel_weight < 0:
        raise ValueError("travel_weight must be nonnegative")
    if (
        not isfinite(request.max_solver_seconds)
        or request.max_solver_seconds <= 0
    ):
        raise ValueError("max_solver_seconds must be finite and positive")
    resources = tuple(sorted(request.resources, key=lambda item: item.resource_id))
    tasks = tuple(sorted(request.tasks, key=lambda item: item.task_id))
    routes = tuple(
        sorted(request.routes, key=lambda item: (item.resource_id, item.task_id))
    )
    locks = tuple(
        sorted(
            request.locked_assignments,
            key=lambda item: (item.resource_id, item.task_id),
        )
    )
    _reject_duplicates((item.resource_id for item in resources), "resource")
    _reject_duplicates((item.task_id for item in tasks), "task")
    _reject_duplicates(
        ((item.resource_id, item.task_id) for item in routes),
        "route pair",
    )
    _reject_duplicates(
        ((item.resource_id, item.task_id) for item in locks),
        "locked assignment",
    )
    resource_ids = {item.resource_id for item in resources}
    task_ids = {item.task_id for item in tasks}
    for route in routes:
        if route.resource_id not in resource_ids:
            raise ValueError(f"unknown route resource: {route.resource_id}")
        if route.task_id not in task_ids:
            raise ValueError(f"unknown route task: {route.task_id}")
    for lock in locks:
        if lock.resource_id not in resource_ids or lock.task_id not in task_ids:
            raise ValueError(
                f"unknown locked assignment: {lock.resource_id} -> {lock.task_id}"
            )
    return resources, tasks, routes, locks


def _eligible(
    resource: ResourceUnit,
    task: TaskDemand,
    route: RouteResult,
) -> bool:
    return (
        resource.available
        and task.required_capability in resource.capabilities
        and route.status is RouteStatus.REACHABLE
        and route.travel_minutes <= task.deadline_minutes
    )


def _reject_duplicates[T](values: Iterable[T], label: str) -> None:
    seen: set[T] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _binding_constraints(
    status: str,
    resources: tuple[ResourceUnit, ...],
    tasks: tuple[TaskDemand, ...],
    routes: tuple[TaskCandidateRoute, ...],
    eligible: dict[tuple[str, str], TaskCandidateRoute],
    selected: tuple[tuple[str, str], ...],
    uncovered: tuple[str, ...],
) -> tuple[str, ...]:
    resources_by_id = {item.resource_id: item for item in resources}
    tasks_by_id = {item.task_id: item for item in tasks}
    selected_by_resource = dict(selected)
    constraints: set[str] = set()
    for task_id in uncovered:
        task = tasks_by_id[task_id]
        if status not in _SOLUTION_STATUSES:
            constraints.add(
                f"solver-status: task={task_id}; status={status} produced no solution"
            )
            continue
        candidates = [item for item in routes if item.task_id == task_id]
        if not candidates:
            constraints.add(f"route: task={task_id}; no candidate route")
        for candidate in candidates:
            resource = resources_by_id[candidate.resource_id]
            prefix = f"resource={resource.resource_id}; task={task_id};"
            if not resource.available:
                constraints.add(f"availability: {prefix} resource is unavailable")
            elif task.required_capability not in resource.capabilities:
                constraints.add(
                    f"compatibility: {prefix} resource lacks capability="
                    f"{task.required_capability}"
                )
            elif candidate.route.status is not RouteStatus.REACHABLE:
                constraints.add(f"route: {prefix} route is unreachable")
            elif candidate.route.travel_minutes > task.deadline_minutes:
                constraints.add(
                    f"deadline: {prefix} travel_minutes="
                    f"{candidate.route.travel_minutes:g} exceeds deadline_minutes="
                    f"{task.deadline_minutes}"
                )
        eligible_resources = [
            resource_id
            for resource_id, candidate_task_id in eligible
            if candidate_task_id == task_id
        ]
        eligible_capacity = sum(
            resources_by_id[resource_id].capacity
            for resource_id in eligible_resources
        )
        if eligible_capacity < task.required_capacity:
            constraints.add(
                f"capacity: task={task_id}; eligible_capacity={eligible_capacity} "
                f"is below required_capacity={task.required_capacity}"
            )
        consumed = sorted(
            f"{resource_id}->{selected_by_resource[resource_id]}"
            for resource_id in eligible_resources
            if resource_id in selected_by_resource
            and selected_by_resource[resource_id] != task_id
        )
        if consumed:
            constraints.add(
                f"resource-contention: task={task_id}; eligible assignments="
                f"{', '.join(consumed)} consume needed capacity"
            )
    return tuple(sorted(constraints))
```

- [ ] **Step 6: Add exact constraint tests**

Add these cases to `test_task_optimizer.py`:

| Test | Setup | Exact assertion |
|---|---|---|
| `test_multiple_resources_may_combine_capacity_for_one_task` | Two capacity-1 buses, one evacuation task requiring capacity 2 | Both buses are assigned to the task and it is not uncovered |
| `test_one_resource_cannot_cover_tasks_from_both_incidents` | One engine, two compatible tasks from different incidents | Exactly one assignment exists and the other task is uncovered |
| `test_unavailable_resource_is_ineligible` | One unavailable compatible resource and reachable route | No assignments; constraint starts with `availability:` |
| `test_incompatible_resource_is_ineligible` | One available bus and a medical task | No assignments; constraint starts with `compatibility:` |
| `test_late_route_is_ineligible` | Travel time 31, task deadline 30 | No assignments; constraint starts with `deadline:` |
| `test_unreachable_route_is_ineligible` | Candidate route status `UNREACHABLE` | No assignments; constraint starts with `route:` |
| `test_valid_locked_assignment_is_forced` | One lower-penalty locked task and one higher-penalty unlocked task | Locked pair is the only selected pair |
| `test_invalid_locked_assignment_fails_before_solving` | Lock an incompatible pair | Raises `ValueError("locked assignment is not eligible: bus-1 -> medical-1")` |
| `test_unknown_solver_status_does_not_read_variable_values` | Monkeypatch the solver using the existing `test_optimizer.py` pattern | Status is `UNKNOWN`, all tasks uncovered, and fake `value()` is never called |
| `test_reordered_inputs_produce_identical_semantic_result` | Reverse resources, tasks, routes, and locks | Every field except measured `runtime_milliseconds` compares equal |

Each test asserts assignments, uncovered task IDs, unassigned resources, objective components, and the complete expected binding-constraint tuple.

- [ ] **Step 7: Add Hypothesis invariants**

```python
# backend/tests/unit/decision/test_task_optimizer_properties.py
from hypothesis import given, settings, strategies as st


@st.composite
def task_plan_requests(
    draw: st.DrawFn,
) -> TaskOptimizationRequest:
    resource_count = draw(st.integers(min_value=1, max_value=4))
    task_count = draw(st.integers(min_value=1, max_value=4))
    resources = tuple(
        ResourceUnit(
            f"resource-{index}",
            frozenset({"protect"} if index % 2 == 0 else {"transport"}),
            draw(st.integers(min_value=1, max_value=3)),
            draw(st.booleans()),
            -121.60 - index / 100,
            39.80 + index / 100,
        )
        for index in range(resource_count)
    )
    tasks = tuple(
        TaskDemand(
            f"task-{index}",
            "park-fire" if index % 2 == 0 else "spot-fire",
            f"asset-{index}",
            "protect" if index % 2 == 0 else "transport",
            draw(st.integers(min_value=1, max_value=4)),
            draw(st.integers(min_value=5, max_value=60)),
            draw(st.integers(min_value=0, max_value=2_000)),
        )
        for index in range(task_count)
    )
    routes = tuple(
        TaskCandidateRoute(
            resource.resource_id,
            task.task_id,
            RouteResult(
                draw(st.sampled_from(tuple(RouteStatus))),
                (),
                1_000,
                draw(
                    st.floats(
                        min_value=1,
                        max_value=90,
                        allow_nan=False,
                        allow_infinity=False,
                    )
                ),
                "graph-v1",
                "closures-v1",
            ),
        )
        for resource in resources
        for task in tasks
    )
    return TaskOptimizationRequest(
        resources=resources,
        tasks=tasks,
        routes=routes,
        locked_assignments=(),
        travel_weight=draw(st.integers(min_value=0, max_value=10)),
    )


@given(task_plan_requests())
@settings(max_examples=30, deadline=None)
def test_task_plan_invariants(request: TaskOptimizationRequest) -> None:
    result = solve_task_plan(request)
    resources = {item.resource_id: item for item in request.resources}
    tasks = {item.task_id: item for item in request.tasks}
    routes = {
        (item.resource_id, item.task_id): item.route
        for item in request.routes
    }
    assigned_resources = [item.resource_id for item in result.assignments]
    assert len(assigned_resources) == len(set(assigned_resources))
    assert result.assignments == tuple(
        sorted(result.assignments, key=lambda item: (item.resource_id, item.task_id))
    )
    assert result.uncovered_task_ids == tuple(sorted(result.uncovered_task_ids))
    for assignment in result.assignments:
        resource = resources[assignment.resource_id]
        task = tasks[assignment.task_id]
        route = routes[(assignment.resource_id, assignment.task_id)]
        assert resource.available
        assert task.required_capability in resource.capabilities
        assert route.status is RouteStatus.REACHABLE
        assert route.travel_minutes <= task.deadline_minutes
    for task_id in set(tasks) - set(result.uncovered_task_ids):
        assert sum(
            item.capacity
            for item in result.assignments
            if item.task_id == task_id
        ) >= tasks[task_id].required_capacity
    assert result.objective_value == (
        result.travel_cost + result.uncovered_task_penalty
    )
```

- [ ] **Step 8: Run solver tests and static checks**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_task_optimizer.py \
  tests/unit/decision/test_task_optimizer_properties.py -q
uv run ruff check src/wildfireops/decision/task_optimizer.py \
  tests/unit/decision/test_task_optimizer.py \
  tests/unit/decision/test_task_optimizer_properties.py
uv run mypy src/wildfireops/decision/task_optimizer.py
```

Expected: all checks pass.

- [ ] **Step 9: Commit the task solver**

```bash
git add backend/src/wildfireops/decision/task_optimizer.py \
  backend/tests/unit/decision/test_task_optimizer.py \
  backend/tests/unit/decision/test_task_optimizer_properties.py
git commit -m "feat(exercise): solve shared task plans"
```

---

### Task 3: Explain plan changes from structured evidence

**Files:**
- Create: `backend/src/wildfireops/decision/task_explanations.py`
- Test: `backend/tests/unit/decision/test_task_explanations.py`

**Interfaces:**
- Consumes: canonical serialized previous/current planning inputs plus `TaskOptimizationResult`.
- Produces: `PlanChange`, `TaskPlanExplanation`, `explain_task_plan(previous_input, current_input, result)`, and `serialize_task_explanation(explanation)`.

- [ ] **Step 1: Write a failing three-cause explanation test**

```python
# backend/tests/unit/decision/test_task_explanations.py
from wildfireops.decision.task_explanations import explain_task_plan


def test_explanation_reports_wind_spot_fire_and_closed_route() -> None:
    previous = {
        "objective": "fastest-response",
        "wind": {"speedMps": 6.7, "directionDegrees": 160},
        "closedEdgeIds": [],
        "tasks": [{"taskId": "park-evac", "incidentId": "park-fire", "penalty": 200}],
        "assignments": [{"resourceId": "bus-1", "taskId": "park-evac"}],
    }
    current = {
        "objective": "protect-critical-services",
        "wind": {"speedMps": 9.0, "directionDegrees": 45},
        "closedEdgeIds": ["edge-32"],
        "tasks": [
            {"taskId": "park-evac", "incidentId": "park-fire", "penalty": 300},
            {"taskId": "spot-comms", "incidentId": "spot-fire", "penalty": 900},
        ],
        "assignments": [{"resourceId": "bus-1", "taskId": "spot-comms"}],
    }

    explanation = explain_task_plan(previous, current)

    assert [item.code for item in explanation.changes] == [
        "objective.changed",
        "wind.changed",
        "incident.task-added",
        "route.closed",
        "assignment.changed",
    ]
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_task_explanations.py -v
```

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement deterministic diff types and ordering**

```python
# backend/src/wildfireops/decision/task_explanations.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


_ORDER = {
    "objective.changed": 10,
    "wind.changed": 20,
    "incident.task-added": 30,
    "incident.task-removed": 40,
    "task.priority-changed": 50,
    "route.closed": 60,
    "route.reopened": 70,
    "resource.unavailable": 80,
    "assignment.changed": 90,
}


@dataclass(frozen=True, slots=True)
class PlanChange:
    code: str
    summary: str
    evidence: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TaskPlanExplanation:
    changes: tuple[PlanChange, ...]


def explain_task_plan(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> TaskPlanExplanation:
    if previous is None:
        return TaskPlanExplanation(())
    changes: list[PlanChange] = []
    if previous.get("objective") != current.get("objective"):
        changes.append(
            PlanChange(
                "objective.changed",
                "The planning objective changed.",
                {
                    "before": previous.get("objective"),
                    "after": current.get("objective"),
                },
            )
        )
    if previous.get("wind") != current.get("wind"):
        changes.append(
            PlanChange(
                "wind.changed",
                "Wind conditions changed task priorities.",
                {
                    "before": previous.get("wind"),
                    "after": current.get("wind"),
                },
            )
        )
    changes.extend(_task_changes(previous, current))
    changes.extend(_road_changes(previous, current))
    changes.extend(_assignment_changes(previous, current))
    return TaskPlanExplanation(
        tuple(
            sorted(
                changes,
                key=lambda item: (
                    _ORDER[item.code],
                    str(item.evidence),
                ),
            )
        )
    )


def serialize_task_explanation(
    explanation: TaskPlanExplanation,
) -> dict[str, object]:
    return {
        "changes": [
            {
                "code": item.code,
                "summary": item.summary,
                "evidence": dict(item.evidence),
            }
            for item in explanation.changes
        ]
    }
```

- [ ] **Step 4: Add exact rule implementations**

Implement `_task_changes`, `_road_changes`, and `_assignment_changes` using dictionary indexes keyed by `taskId` and `resourceId`. Each emitted fact must contain the exact before/after values needed to prove the sentence. Do not infer a cause from map position or prose.

```python
def _road_changes(
    previous: Mapping[str, object],
    current: Mapping[str, object],
) -> list[PlanChange]:
    before = set(_strings(previous.get("closedEdgeIds"), "closedEdgeIds"))
    after = set(_strings(current.get("closedEdgeIds"), "closedEdgeIds"))
    return [
        *(
            PlanChange(
                "route.closed",
                "A corridor closed and invalidated affected routes.",
                {"edgeId": edge_id},
            )
            for edge_id in sorted(after - before)
        ),
        *(
            PlanChange(
                "route.reopened",
                "A previously closed corridor reopened.",
                {"edgeId": edge_id},
            )
            for edge_id in sorted(before - after)
        ),
    ]


def _task_changes(
    previous: Mapping[str, object],
    current: Mapping[str, object],
) -> list[PlanChange]:
    before = _rows(previous.get("tasks"), "tasks", "taskId")
    after = _rows(current.get("tasks"), "tasks", "taskId")
    changes = [
        PlanChange(
            "incident.task-added",
            "A new incident task was added.",
            {
                "taskId": task_id,
                "incidentId": after[task_id].get("incidentId"),
            },
        )
        for task_id in sorted(after.keys() - before.keys())
    ]
    changes.extend(
        PlanChange(
            "incident.task-removed",
            "An incident task was removed.",
            {
                "taskId": task_id,
                "incidentId": before[task_id].get("incidentId"),
            },
        )
        for task_id in sorted(before.keys() - after.keys())
    )
    for task_id in sorted(before.keys() & after.keys()):
        old_penalty = before[task_id].get("penalty")
        new_penalty = after[task_id].get("penalty")
        if old_penalty != new_penalty:
            changes.append(
                PlanChange(
                    "task.priority-changed",
                    "A task priority changed.",
                    {
                        "taskId": task_id,
                        "before": old_penalty,
                        "after": new_penalty,
                    },
                )
            )
    old_resources = _rows(
        previous.get("resources"),
        "resources",
        "resourceId",
    )
    new_resources = _rows(
        current.get("resources"),
        "resources",
        "resourceId",
    )
    changes.extend(
        PlanChange(
            "resource.unavailable",
            "A resource became unavailable.",
            {"resourceId": resource_id},
        )
        for resource_id in sorted(old_resources.keys() & new_resources.keys())
        if old_resources[resource_id].get("available") is True
        and new_resources[resource_id].get("available") is False
    )
    return changes


def _assignment_changes(
    previous: Mapping[str, object],
    current: Mapping[str, object],
) -> list[PlanChange]:
    before = _rows(
        previous.get("assignments"),
        "assignments",
        "resourceId",
    )
    after = _rows(
        current.get("assignments"),
        "assignments",
        "resourceId",
    )
    return [
        PlanChange(
            "assignment.changed",
            "A resource assignment changed.",
            {
                "resourceId": resource_id,
                "beforeTaskId": before.get(resource_id, {}).get("taskId"),
                "afterTaskId": after.get(resource_id, {}).get("taskId"),
            },
        )
        for resource_id in sorted(before.keys() | after.keys())
        if before.get(resource_id, {}).get("taskId")
        != after.get(resource_id, {}).get("taskId")
    ]


def _strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{field} must be a sequence")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} entries must be strings")
    return tuple(value)


def _rows(
    value: object,
    field: str,
    key: str,
) -> dict[str, Mapping[str, object]]:
    if value is None:
        return {}
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{field} must be a sequence")
    result: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} entries must be objects")
        identifier = item.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{field}.{key} must be a nonblank string")
        if identifier in result:
            raise ValueError(f"duplicate {field}.{key}: {identifier}")
        result[identifier] = item
    return result
```

- [ ] **Step 5: Test every approved causal code**

Add these exact cases to `test_task_explanations.py`:

| Test | Required assertion |
|---|---|
| `test_initial_plan_has_no_change_claims` | `explain_task_plan(None, current).changes == ()` |
| `test_task_added_and_removed_are_distinct` | Codes are `incident.task-added` then `incident.task-removed`, with exact task IDs |
| `test_priority_change_records_before_and_after_penalty` | Evidence equals `{"taskId": "hospital", "before": 300, "after": 900}` |
| `test_route_reopened_names_the_exact_edge` | Evidence equals `{"edgeId": "edge-32"}` |
| `test_resource_unavailable_names_the_resource` | Evidence equals `{"resourceId": "bus-1"}` |
| `test_assignment_change_names_old_and_new_task` | Evidence contains `resourceId`, `beforeTaskId`, and `afterTaskId` |
| `test_reordered_json_inputs_produce_same_explanation` | Reversed task and assignment arrays produce equal dataclasses |
| `test_serializer_is_json_compatible` | `json.dumps(serialize_task_explanation(value), allow_nan=False)` succeeds |

- [ ] **Step 6: Run explanation tests and commit**

```bash
cd backend
uv run pytest tests/unit/decision/test_task_explanations.py -q
uv run ruff check src/wildfireops/decision/task_explanations.py \
  tests/unit/decision/test_task_explanations.py
uv run mypy src/wildfireops/decision/task_explanations.py
cd ..
git add backend/src/wildfireops/decision/task_explanations.py \
  backend/tests/unit/decision/test_task_explanations.py
git commit -m "feat(exercise): explain task plan changes"
```

---

### Task 4: Persist isolated sessions, immutable plan runs, and events

**Files:**
- Create: `backend/src/wildfireops/persistence/exercise_models.py`
- Create: `backend/src/wildfireops/persistence/exercises.py`
- Create: `backend/migrations/versions/0005_exercise_sessions.py`
- Modify: `backend/migrations/env.py`
- Modify: `backend/tests/integration/conftest.py`
- Test: `backend/tests/integration/persistence/test_exercises.py`

**Interfaces:**
- Consumes: `IdempotencyKeyModel` and an application-owned SQLAlchemy transaction.
- Produces: `ExerciseSessionModel`, `ExercisePlanRunModel`, `ExerciseEventModel`, and `ExerciseRepository`.

- [ ] **Step 1: Write failing migration-shape and repository isolation tests**

```python
# backend/tests/integration/persistence/test_exercises.py
@pytest.mark.asyncio
async def test_plan_runs_are_isolated_by_session(db_session: AsyncSession) -> None:
    repository = ExerciseRepository(db_session)
    first = await repository.create_session(
        exercise_id="park-fire-decision",
        definition_version="1",
        definition_digest="a" * 64,
        callsign="EMBER-101",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    second = await repository.create_session(
        exercise_id="park-fire-decision",
        definition_version="1",
        definition_digest="a" * 64,
        callsign="EMBER-102",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    await repository.store_plan(
        session_id=first.id,
        checkpoint_key="initial",
        input_hash="b" * 64,
        input_data={"session": "first"},
        output_data={"status": "OPTIMAL"},
        versions={"algorithm": "task-allocation-v1"},
        idempotency_key_id=None,
    )

    assert await repository.list_plans(first.id)
    assert await repository.list_plans(second.id) == ()
```

- [ ] **Step 2: Add the three SQLAlchemy models**

```python
# backend/src/wildfireops/persistence/exercise_models.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from wildfireops.persistence.base import Base


class ExerciseSessionModel(Base):
    __tablename__ = "exercise_sessions"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exercise_id: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    callsign: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    checkpoint_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    objective: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    consequences: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExercisePlanRunModel(Base):
    __tablename__ = "exercise_plan_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key_id", name="uq_exercise_plan_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exercise_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    checkpoint_key: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    versions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExerciseEventModel(Base):
    __tablename__ = "exercise_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "resulting_session_version",
            name="uq_exercise_event_session_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exercise_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_callsign: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    expected_session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    after_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 3: Add the Alembic migration**

Create `0005_exercise_sessions.py` with:

```python
revision = "0005_exercise_sessions"
down_revision = "0004_auditable_decisions"
```

The upgrade creates the three tables matching Step 2, these indexes:

```python
op.create_index(
    "ix_exercise_sessions_expiry",
    "exercise_sessions",
    ["status", "expires_at"],
)
op.create_index(
    "ix_exercise_plan_runs_session_checkpoint",
    "exercise_plan_runs",
    ["session_id", "checkpoint_key", "created_at"],
)
op.create_index(
    "ix_exercise_events_session_time",
    "exercise_events",
    ["session_id", "occurred_at", "id"],
)
```

and check constraints:

```python
sa.CheckConstraint(
    "status IN ('active', 'completed', 'expired')",
    name="ck_exercise_sessions_status",
)
sa.CheckConstraint("version >= 1", name="ck_exercise_sessions_version")
sa.CheckConstraint(
    "checkpoint_index BETWEEN 0 AND 2",
    name="ck_exercise_sessions_checkpoint",
)
```

The downgrade drops indexes and tables in reverse dependency order.

- [ ] **Step 4: Register metadata and test cleanup**

```python
# backend/migrations/env.py
from wildfireops.persistence import (  # noqa: F401
    decision_models,
    exercise_models,
    observed_models,
)
```

Prepend `exercise_events, exercise_plan_runs, exercise_sessions,` to the integration `TRUNCATE` statement in `backend/tests/integration/conftest.py`.

- [ ] **Step 5: Implement the session-bound repository**

```python
# backend/src/wildfireops/persistence/exercises.py
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.exercise_models import (
    ExerciseEventModel,
    ExercisePlanRunModel,
    ExerciseSessionModel,
)


class ExerciseRepository:
    """Session-bound adapter; the caller owns commit and rollback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        callsign: str,
        expires_at: datetime,
    ) -> ExerciseSessionModel:
        model = ExerciseSessionModel(
            exercise_id=exercise_id,
            definition_version=definition_version,
            definition_digest=definition_digest,
            callsign=callsign,
            expires_at=expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def lock_session(self, session_id: UUID) -> ExerciseSessionModel | None:
        return await self._session.scalar(
            select(ExerciseSessionModel)
            .where(ExerciseSessionModel.id == session_id)
            .with_for_update()
        )

    async def get_session(self, session_id: UUID) -> ExerciseSessionModel | None:
        return await self._session.get(ExerciseSessionModel, session_id)

    async def store_plan(
        self,
        *,
        session_id: UUID,
        checkpoint_key: str,
        input_hash: str,
        input_data: dict[str, object],
        output_data: dict[str, object],
        versions: dict[str, object],
        idempotency_key_id: UUID | None,
    ) -> ExercisePlanRunModel:
        model = ExercisePlanRunModel(
            session_id=session_id,
            checkpoint_key=checkpoint_key,
            input_hash=input_hash,
            input_data=input_data,
            output_data=output_data,
            versions=versions,
            idempotency_key_id=idempotency_key_id,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def latest_plan(
        self,
        session_id: UUID,
        checkpoint_key: str,
    ) -> ExercisePlanRunModel | None:
        return await self._session.scalar(
            select(ExercisePlanRunModel)
            .where(
                ExercisePlanRunModel.session_id == session_id,
                ExercisePlanRunModel.checkpoint_key == checkpoint_key,
            )
            .order_by(
                ExercisePlanRunModel.created_at.desc(),
                ExercisePlanRunModel.id.desc(),
            )
            .limit(1)
        )

    async def list_plans(
        self,
        session_id: UUID,
    ) -> tuple[ExercisePlanRunModel, ...]:
        rows = await self._session.scalars(
            select(ExercisePlanRunModel)
            .where(ExercisePlanRunModel.session_id == session_id)
            .order_by(
                ExercisePlanRunModel.created_at,
                ExercisePlanRunModel.id,
            )
        )
        return tuple(rows)

    async def append_event(
        self,
        *,
        session_id: UUID,
        event_type: str,
        actor_callsign: str,
        display_name: str | None,
        expected_session_version: int,
        resulting_session_version: int,
        before_state: dict[str, object],
        after_state: dict[str, object],
        inputs: dict[str, object],
        note: str | None,
    ) -> ExerciseEventModel:
        model = ExerciseEventModel(
            session_id=session_id,
            event_type=event_type,
            actor_callsign=actor_callsign,
            display_name=display_name,
            expected_session_version=expected_session_version,
            resulting_session_version=resulting_session_version,
            before_state=before_state,
            after_state=after_state,
            inputs=inputs,
            note=note,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_events(
        self,
        session_id: UUID,
    ) -> tuple[ExerciseEventModel, ...]:
        rows = await self._session.scalars(
            select(ExerciseEventModel)
            .where(ExerciseEventModel.session_id == session_id)
            .order_by(
                ExerciseEventModel.occurred_at,
                ExerciseEventModel.id,
            )
        )
        return tuple(rows)
```

No repository method commits; the application service owns the transaction.

- [ ] **Step 6: Prove database invariants**

Add these integration cases:

| Test | Exact database behavior |
|---|---|
| `test_session_status_check_constraint` | Writing status `invalid` raises `IntegrityError` naming `ck_exercise_sessions_status` |
| `test_event_session_version_is_unique` | Two events for one session/resulting version raise `IntegrityError` |
| `test_plan_run_is_not_updated_by_repository` | A second `store_plan` call creates a new ID and leaves the first JSON unchanged |
| `test_lock_session_serializes_concurrent_commands` | Two connections using `FOR UPDATE` cannot both increment from version 1; the second observes version 2 |
| `test_deleting_session_cascades_plans_and_events` | Deleting the session leaves zero child rows |
| `test_idempotency_key_cannot_back_two_plan_runs` | Reusing one idempotency row raises `IntegrityError` naming `uq_exercise_plan_idempotency` |

- [ ] **Step 7: Run migrations and persistence tests**

Run:

```bash
docker compose up -d db
cd backend
uv run alembic upgrade head
uv run pytest tests/integration/persistence/test_exercises.py -q
uv run alembic downgrade 0004_auditable_decisions
uv run alembic upgrade head
uv run ruff check src/wildfireops/persistence/exercise_models.py \
  src/wildfireops/persistence/exercises.py \
  migrations/versions/0005_exercise_sessions.py \
  tests/integration/persistence/test_exercises.py
```

Expected: migration round trip and all tests pass.

- [ ] **Step 8: Commit persistence**

```bash
git add backend/src/wildfireops/persistence/exercise_models.py \
  backend/src/wildfireops/persistence/exercises.py \
  backend/migrations/env.py \
  backend/migrations/versions/0005_exercise_sessions.py \
  backend/tests/integration/conftest.py \
  backend/tests/integration/persistence/test_exercises.py
git commit -m "feat(exercise): persist isolated planning sessions"
```

---

### Task 5: Enforce session commands, versions, idempotency, and audit events

**Files:**
- Create: `backend/src/wildfireops/application/exercises.py`
- Modify: `backend/src/wildfireops/persistence/exercises.py`
- Test: `backend/tests/unit/application/test_exercises.py`
- Test: `backend/tests/integration/persistence/test_exercises.py`

**Interfaces:**
- Consumes: `ExerciseDefinition`, definition digest, a UTC clock, and repository operations.
- Produces: `ExerciseSession`, `ExercisePlanRun`, `ExerciseEvent`, `ExerciseSessionService`, `ExerciseQueryService`, `ExerciseError` subclasses, and repository protocol methods.

- [ ] **Step 1: Write failing session lifecycle tests with a fake repository**

```python
# backend/tests/unit/application/test_exercises.py
@pytest.mark.asyncio
async def test_new_session_gets_callsign_and_24_hour_expiry() -> None:
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    repository = FakeExerciseRepository()
    service = ExerciseSessionService(
        definition=definition(),
        definition_digest="a" * 64,
        repository=repository,
        clock=lambda: now,
        callsign=lambda: "EMBER-101",
    )

    session = await service.create(idempotency_key="create-1")

    assert session.callsign == "EMBER-101"
    assert session.status == "active"
    assert session.version == 1
    assert session.expires_at == now + timedelta(hours=24)
```

Add the lifecycle cases listed in Step 7 before implementation; run each named test once to confirm it fails for the expected missing behavior.

- [ ] **Step 2: Define transport-neutral projections and errors**

```python
# backend/src/wildfireops/application/exercises.py
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from wildfireops.domain.scenario_versions import IdempotencyClaim
from wildfireops.replay.exercise import ExerciseDefinition, ObjectivePreset


type SessionStatus = Literal["active", "completed", "expired"]


@dataclass(slots=True)
class ExerciseSession:
    id: UUID
    exercise_id: str
    definition_version: str
    definition_digest: str
    callsign: str
    display_name: str | None
    checkpoint_index: int
    objective: ObjectivePreset | None
    status: SessionStatus
    version: int
    consequences: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExercisePlanRun:
    id: UUID
    session_id: UUID
    checkpoint_key: str
    input_hash: str
    input_data: Mapping[str, object]
    output_data: Mapping[str, object]
    versions: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExerciseEvent:
    id: UUID
    session_id: UUID
    event_type: str
    actor_callsign: str
    display_name: str | None
    expected_session_version: int
    resulting_session_version: int
    before_state: Mapping[str, object]
    after_state: Mapping[str, object]
    inputs: Mapping[str, object]
    note: str | None
    occurred_at: datetime


class ExerciseRepositoryProtocol(Protocol):
    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim: ...

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None: ...

    async def create_session(
        self,
        *,
        exercise_id: str,
        definition_version: str,
        definition_digest: str,
        callsign: str,
        expires_at: datetime,
    ) -> ExerciseSession: ...

    async def get_session(self, session_id: UUID) -> ExerciseSession | None: ...
    async def lock_session(self, session_id: UUID) -> ExerciseSession | None: ...
    async def save_session(self, session: ExerciseSession) -> None: ...
    async def get_event(self, event_id: UUID) -> ExerciseEvent | None: ...
    async def get_plan(self, plan_id: UUID) -> ExercisePlanRun | None: ...
    async def latest_plan(
        self,
        session_id: UUID,
        checkpoint_key: str,
    ) -> ExercisePlanRun | None: ...
    async def latest_plan_for_session(
        self,
        session_id: UUID,
    ) -> ExercisePlanRun | None: ...
    async def list_plans(
        self,
        session_id: UUID,
    ) -> tuple[ExercisePlanRun, ...]: ...
    async def list_events(
        self,
        session_id: UUID,
    ) -> tuple[ExerciseEvent, ...]: ...
    async def append_event(
        self,
        *,
        session_id: UUID,
        event_type: str,
        actor_callsign: str,
        display_name: str | None,
        expected_session_version: int,
        resulting_session_version: int,
        before_state: dict[str, object],
        after_state: dict[str, object],
        inputs: dict[str, object],
        note: str | None,
    ) -> ExerciseEvent: ...


class ExerciseError(ValueError):
    code = "exercise_error"


class ExerciseNotFound(ExerciseError):
    code = "exercise_not_found"


class ExerciseSessionNotFound(ExerciseError):
    code = "exercise_session_not_found"


class ExerciseSessionExpired(ExerciseError):
    code = "exercise_session_expired"


class ExerciseVersionConflict(ExerciseError):
    code = "exercise_session_version_conflict"


class ExerciseTransitionInvalid(ExerciseError):
    code = "exercise_transition_invalid"


class ExerciseCommandInvalid(ExerciseError):
    code = "exercise_command_invalid"


class ExerciseIdempotencyConflict(ExerciseError):
    code = "exercise_idempotency_conflict"
```

- [ ] **Step 3: Implement create, read, and objective selection**

```python
class ExerciseSessionService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        definition_digest: str,
        repository: ExerciseRepositoryProtocol,
        clock: Callable[[], datetime],
        callsign: Callable[[], str],
    ) -> None:
        self._definition = definition
        self._definition_digest = definition_digest
        self._repository = repository
        self._clock = clock
        self._callsign = callsign

    @property
    def exercise_id(self) -> str:
        return self._definition.exercise_id

    async def project(self, session: ExerciseSession) -> dict[str, object]:
        return await session_projection(
            self._definition,
            self._repository,
            session,
            self._clock(),
        )

    async def create(self, *, idempotency_key: str) -> ExerciseSession:
        now = self._clock()
        claim = await self._repository.claim_idempotency(
            scope=f"exercise:{self._definition.exercise_id}:session-create",
            key=idempotency_key,
            request_hash=_request_hash({}),
        )
        replayed = await self._replay_event(claim)
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        session = await self._repository.create_session(
            exercise_id=self._definition.exercise_id,
            definition_version=self._definition.version,
            definition_digest=self._definition_digest,
            callsign=self._callsign(),
            expires_at=now + timedelta(hours=24),
        )
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.session-created",
            actor_callsign=session.callsign,
            display_name=None,
            expected_session_version=0,
            resulting_session_version=1,
            before_state={},
            after_state=_session_state(session),
            inputs={},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="exercise_event",
            response_id=event.id,
        )
        return session

    async def select_objective(
        self,
        session_id: UUID,
        objective: ObjectivePreset,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> ExerciseSession:
        session, claim, replayed = await self.lock_command(
            session_id,
            expected_version,
            idempotency_key,
            "select-objective",
            {"objective": objective},
        )
        if replayed is not None:
            return _session_from_state(replayed.after_state)
        if objective not in self._definition.objectives:
            raise ExerciseCommandInvalid(f"unsupported objective: {objective}")
        latest = await self._repository.latest_plan_for_session(session.id)
        if latest is not None and latest.output_data.get("operatorOverride"):
            raise ExerciseTransitionInvalid(
                "objective cannot change after a validated override"
            )
        before = _session_state(session)
        session.objective = objective
        session.version += 1
        await self._repository.save_session(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.objective-selected",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs={"objective": objective},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="exercise_event",
            response_id=event.id,
        )
        return session
```

Add `_request_hash`, `_replay_event`, and `lock_command`:

```python
def _request_hash(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _session_state(session: ExerciseSession) -> dict[str, object]:
    return {
        "id": str(session.id),
        "exerciseId": session.exercise_id,
        "definitionVersion": session.definition_version,
        "definitionDigest": session.definition_digest,
        "callsign": session.callsign,
        "displayName": session.display_name,
        "checkpointIndex": session.checkpoint_index,
        "objective": session.objective,
        "status": session.status,
        "version": session.version,
        "consequences": dict(session.consequences),
        "expiresAt": session.expires_at.isoformat(),
    }


def _session_from_state(state: Mapping[str, object]) -> ExerciseSession:
    objective = state.get("objective")
    status = state.get("status")
    if objective not in {
        None,
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    }:
        raise RuntimeError("stored exercise objective is invalid")
    if status not in {"active", "completed", "expired"}:
        raise RuntimeError("stored exercise status is invalid")
    consequences = state.get("consequences")
    if not isinstance(consequences, Mapping):
        raise RuntimeError("stored exercise consequences are invalid")
    return ExerciseSession(
        id=UUID(str(state["id"])),
        exercise_id=str(state["exerciseId"]),
        definition_version=str(state["definitionVersion"]),
        definition_digest=str(state["definitionDigest"]),
        callsign=str(state["callsign"]),
        display_name=(
            None
            if state.get("displayName") is None
            else str(state["displayName"])
        ),
        checkpoint_index=int(str(state["checkpointIndex"])),
        objective=cast(ObjectivePreset | None, objective),
        status=cast(SessionStatus, status),
        version=int(str(state["version"])),
        consequences=dict(consequences),
        expires_at=datetime.fromisoformat(str(state["expiresAt"])),
    )


async def _replay_event(
    self,
    claim: IdempotencyClaim,
) -> ExerciseEvent | None:
    if claim.created:
        return None
    if claim.response_type != "exercise_event" or claim.response_id is None:
        raise RuntimeError("exercise idempotency response is incomplete")
    event = await self._repository.get_event(claim.response_id)
    if event is None:
        raise RuntimeError("exercise idempotency event does not exist")
    return event


async def lock_command(
    self,
    session_id: UUID,
    expected_version: int,
    idempotency_key: str,
    command: str,
    payload: Mapping[str, object],
) -> tuple[ExerciseSession, IdempotencyClaim, ExerciseEvent | None]:
    request_hash = _request_hash(
        {
            "sessionId": str(session_id),
            "expectedVersion": expected_version,
            "payload": dict(payload),
        }
    )
    claim = await self._repository.claim_idempotency(
        scope=f"exercise-session:{session_id}:{command}",
        key=idempotency_key,
        request_hash=request_hash,
    )
    if not claim.created:
        if claim.request_hash != request_hash:
            raise ExerciseIdempotencyConflict(
                "idempotency key was already used with a different request"
            )
        event = await self._replay_event(claim)
        if event is None:
            raise RuntimeError("exercise replay response is missing")
        current = await self._repository.get_session(session_id)
        if current is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        return current, claim, event
    session = await self._repository.lock_session(session_id)
    if session is None:
        raise ExerciseSessionNotFound("exercise session was not found")
    if self._clock() >= session.expires_at:
        raise ExerciseSessionExpired("exercise session has expired")
    if session.status != "active":
        raise ExerciseTransitionInvalid("exercise session is not active")
    if session.version != expected_version:
        raise ExerciseVersionConflict(
            f"expected session version {expected_version}, current version "
            f"{session.version}"
        )
    return session, claim, None
```

- [ ] **Step 4: Implement checkpoint acceptance and corridor consequence**

```python
async def advance(
    self,
    session_id: UUID,
    *,
    expected_version: int,
    idempotency_key: str,
) -> ExerciseSession:
    session, claim, replayed = await self.lock_command(
        session_id,
        expected_version,
        idempotency_key,
        "advance",
        {},
    )
    if replayed is not None:
        return _session_from_state(replayed.after_state)
    if session.checkpoint_index >= 2:
        raise ExerciseTransitionInvalid("checkpoint three cannot advance")
    latest = await self._repository.latest_plan(
        session.id,
        self._definition.checkpoints[session.checkpoint_index].checkpoint_key,
    )
    if latest is None or latest.output_data.get("status") not in {
        "FEASIBLE",
        "OPTIMAL",
    } or latest.input_data.get("objective") != session.objective:
        raise ExerciseTransitionInvalid("current checkpoint has no actionable plan")
    consequences = dict(session.consequences)
    if session.checkpoint_index == 1:
        assignments = latest.output_data.get("assignments", [])
        consequences["corridorCleared"] = any(
            item.get("taskId") == "clear-primary-corridor"
            for item in assignments
            if isinstance(item, Mapping)
        )
    before = _session_state(session)
    session.checkpoint_index += 1
    session.consequences = consequences
    session.version += 1
    await self._repository.save_session(session)
    event = await self._repository.append_event(
        session_id=session.id,
        event_type="exercise.checkpoint-advanced",
        actor_callsign=session.callsign,
        display_name=session.display_name,
        expected_session_version=expected_version,
        resulting_session_version=session.version,
        before_state=before,
        after_state=_session_state(session),
        inputs={"acceptedPlanId": str(latest.id)},
        note=None,
    )
    await self._repository.complete_idempotency(
        claim_id=claim.id,
        response_type="exercise_event",
        response_id=event.id,
    )
    return session
```

Checkpoint index `2` cannot advance. Final approval changes status to `completed`.

- [ ] **Step 5: Implement final decision validation**

```python
async def decide(
    self,
    session_id: UUID,
    *,
    display_name: str | None,
    note: str,
    expected_version: int,
    idempotency_key: str,
) -> ExerciseSession:
    session, claim, replayed = await self.lock_command(
        session_id,
        expected_version,
        idempotency_key,
        "decide",
        {"displayName": display_name, "note": note},
    )
    if replayed is not None:
        return _session_from_state(replayed.after_state)
    if session.checkpoint_index != 2:
        raise ExerciseTransitionInvalid("final decision requires checkpoint three")
    normalized_note = note.strip()
    if not normalized_note:
        raise ExerciseCommandInvalid("decision note must not be blank")
    normalized_name = None if display_name is None else display_name.strip()
    if normalized_name == "":
        raise ExerciseCommandInvalid("display name must not be blank")
    if normalized_name is not None and len(normalized_name) > 120:
        raise ExerciseCommandInvalid("display name must not exceed 120 characters")
    latest = await self._repository.latest_plan(session.id, "field-report")
    if (
        latest is None
        or latest.input_data.get("objective") != session.objective
        or not latest.output_data.get("operatorOverride")
    ):
        raise ExerciseTransitionInvalid("final decision requires a validated override")
    session.display_name = normalized_name
    session.status = "completed"
    session.version += 1
    before = {
        **_session_state(session),
        "displayName": None,
        "status": "active",
        "version": expected_version,
    }
    await self._repository.save_session(session)
    event = await self._repository.append_event(
        session_id=session.id,
        event_type="exercise.plan-approved",
        actor_callsign=session.callsign,
        display_name=session.display_name,
        expected_session_version=expected_version,
        resulting_session_version=session.version,
        before_state=before,
        after_state=_session_state(session),
        inputs={"planId": str(latest.id)},
        note=normalized_note,
    )
    await self._repository.complete_idempotency(
        claim_id=claim.id,
        response_type="exercise_event",
        response_id=event.id,
    )
    return session
```

- [ ] **Step 6: Map repository models and implement query projections**

Extend `backend/src/wildfireops/persistence/exercises.py` so every public method returns application dataclasses, not SQLAlchemy models. `save_session` locks the model by ID and copies only `display_name`, `checkpoint_index`, `objective`, `status`, `version`, and `consequences`. `get_plan`, `get_event`, and list methods use these exact mappers:

```python
def _plan(model: ExercisePlanRunModel) -> ExercisePlanRun:
    return ExercisePlanRun(
        id=model.id,
        session_id=model.session_id,
        checkpoint_key=model.checkpoint_key,
        input_hash=model.input_hash,
        input_data=dict(model.input_data),
        output_data=dict(model.output_data),
        versions=dict(model.versions),
        created_at=model.created_at,
    )


def _event(model: ExerciseEventModel) -> ExerciseEvent:
    return ExerciseEvent(
        id=model.id,
        session_id=model.session_id,
        event_type=model.event_type,
        actor_callsign=model.actor_callsign,
        display_name=model.display_name,
        expected_session_version=model.expected_session_version,
        resulting_session_version=model.resulting_session_version,
        before_state=dict(model.before_state),
        after_state=dict(model.after_state),
        inputs=dict(model.inputs),
        note=model.note,
        occurred_at=model.occurred_at,
    )
```

Reuse `ScenarioRepository.claim_idempotency()` and `complete_idempotency()` instead of duplicating PostgreSQL upsert logic.

Add `ExerciseQueryService`:

```python
class ExerciseQueryService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        repository: ExerciseRepositoryProtocol,
        clock: Callable[[], datetime],
    ) -> None:
        self._definition = definition
        self._repository = repository
        self._clock = clock

    async def metadata(self, exercise_id: str) -> dict[str, object]:
        if exercise_id != self._definition.exercise_id:
            raise ExerciseNotFound("exercise was not found")
        return {
            "exerciseId": self._definition.exercise_id,
            "version": self._definition.version,
            "name": self._definition.name,
            "description": self._definition.description,
            "checkpointCount": len(self._definition.checkpoints),
            "objectives": sorted(self._definition.objectives),
            "safetyStatement": self._definition.safety_statement,
            "assets": [
                item.model_dump(mode="json", by_alias=True)
                for item in self._definition.assets
            ],
            "resources": [
                item.model_dump(mode="json", by_alias=True)
                for item in self._definition.resources
            ],
        }

    async def session(self, session_id: UUID) -> dict[str, object]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        return await session_projection(
            self._definition,
            self._repository,
            session,
            self._clock(),
        )

    async def audit(self, session_id: UUID) -> tuple[ExerciseEvent, ...]:
        if await self._repository.get_session(session_id) is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        return await self._repository.list_events(session_id)

    async def debrief(self, session_id: UUID) -> dict[str, object]:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise ExerciseSessionNotFound("exercise session was not found")
        if session.status != "completed":
            raise ExerciseTransitionInvalid("debrief requires a completed exercise")
        plans = await self._repository.list_plans(session.id)
        events = await self._repository.list_events(session.id)
        if not plans:
            raise RuntimeError("completed exercise has no plan")
        return {
            "session": _session_state(session),
            "plans": [dict(item.output_data) for item in plans],
            "finalPlan": dict(plans[-1].output_data),
            "events": [
                {
                    "eventType": item.event_type,
                    "inputs": dict(item.inputs),
                    "note": item.note,
                    "occurredAt": item.occurred_at.isoformat(),
                }
                for item in events
            ],
        }


async def session_projection(
    definition: ExerciseDefinition,
    repository: ExerciseRepositoryProtocol,
    session: ExerciseSession,
    now: datetime,
) -> dict[str, object]:
    if session.status == "active" and now >= session.expires_at:
        session.status = "expired"
    latest = await repository.latest_plan_for_session(session.id)
    return {
        **_session_state(session),
        "allowedActions": _allowed_actions(session, latest),
        "currentCheckpoint": definition.checkpoints[
            session.checkpoint_index
        ].model_dump(mode="json", by_alias=True),
        "latestPlan": None if latest is None else dict(latest.output_data),
    }


def _allowed_actions(
    session: ExerciseSession,
    latest: ExercisePlanRun | None,
) -> tuple[str, ...]:
    if session.status == "expired":
        return ("start-new-exercise",)
    if session.status == "completed":
        return ("view-debrief",)
    if session.objective is None:
        return ("select-objective",)
    if session.checkpoint_index < 2:
        actionable = (
            latest is not None
            and latest.checkpoint_key
            == session_checkpoint_key(session.checkpoint_index)
            and latest.input_data.get("objective") == session.objective
            and latest.output_data.get("status") in {"FEASIBLE", "OPTIMAL"}
        )
        return (
            ("select-objective", "advance")
            if actionable
            else ("select-objective", "generate-plan")
        )
    if (
        latest is None
        or latest.checkpoint_key != "field-report"
        or latest.input_data.get("objective") != session.objective
    ):
        return ("select-objective", "generate-plan")
    return (
        ("approve-plan",)
        if latest.output_data.get("operatorOverride")
        else ("select-objective", "apply-override")
    )
```

Implement `session_checkpoint_key()` as the fixed mapping `{0: "initial", 1: "cascade", 2: "field-report"}` and raise `RuntimeError` for any other index.

- [ ] **Step 7: Complete lifecycle tests**

Add these cases with exact exception messages and repository row counts:

| Test | Required assertion |
|---|---|
| `test_identical_objective_command_replays_original_version` | Second call returns the version-2 projection from the original event and appends no row |
| `test_same_key_with_different_objective_conflicts` | Raises `ExerciseIdempotencyConflict` and objective remains unchanged |
| `test_stale_expected_version_does_not_append_event` | Raises `ExerciseVersionConflict`; event count is unchanged |
| `test_expired_session_is_read_only_without_persisted_side_effects` | Mutation raises `ExerciseSessionExpired`; subsequent projection reports `expired`; stored objective and version are unchanged |
| `test_checkpoint_two_acceptance_records_corridor_cleared` | `consequences == {"corridorCleared": True}` |
| `test_checkpoint_two_without_road_crew_keeps_corridor_closed` | `consequences == {"corridorCleared": False}` |
| `test_final_approval_requires_checkpoint_three` | Raises `ExerciseTransitionInvalid("final decision requires checkpoint three")` |
| `test_final_approval_requires_validated_override` | Raises `ExerciseTransitionInvalid("final decision requires a validated override")` |
| `test_final_approval_requires_nonblank_note` | Raises `ExerciseCommandInvalid("decision note must not be blank")` |
| `test_final_approval_is_append_only` | One approval event exists and a second distinct approval command conflicts because status is completed |

- [ ] **Step 8: Run command tests and commit**

```bash
cd backend
uv run pytest tests/unit/application/test_exercises.py \
  tests/integration/persistence/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercises.py \
  src/wildfireops/persistence/exercises.py \
  tests/unit/application/test_exercises.py
uv run mypy src/wildfireops/application/exercises.py \
  src/wildfireops/persistence/exercises.py
cd ..
git add backend/src/wildfireops/application/exercises.py \
  backend/src/wildfireops/persistence/exercises.py \
  backend/tests/unit/application/test_exercises.py \
  backend/tests/integration/persistence/test_exercises.py
git commit -m "feat(exercise): enforce session command lifecycle"
```

---

### Task 6: Materialize checkpoints, route tasks, generate plans, and validate overrides

**Files:**
- Create: `backend/src/wildfireops/application/exercise_planning.py`
- Modify: `backend/src/wildfireops/application/exercises.py`
- Modify: `backend/src/wildfireops/persistence/exercises.py`
- Test: `backend/tests/unit/application/test_exercise_planning.py`

**Interfaces:**
- Consumes: `ExerciseDefinition`, locked `ExerciseSession`, `RoadGraph`, `ResourceUnit`, `compute_route`, objective weights, task solver, and task explanations.
- Produces: `ExercisePlanningService.generate_plan(...) -> tuple[ExercisePlanRun, dict[str, object]]`, `ExercisePlanningService.apply_override(...) -> tuple[ExercisePlanRun, dict[str, object]]`, canonical planning-input JSON, stable SHA-256 input hash, and JSON-compatible output. The tuple contains the immutable plan and the resulting session projection from the same transaction.

- [ ] **Step 1: Write a failing materialization test**

```python
# backend/tests/unit/application/test_exercise_planning.py
def test_checkpoint_materialization_combines_both_incidents() -> None:
    materialized = materialize_checkpoint(
        definition(),
        checkpoint_index=1,
        objective="protect-critical-services",
        consequences={"corridorCleared": False},
    )

    assert {item.incident_id for item in materialized.tasks} == {
        "park-fire",
        "spot-fire",
    }
    assert materialized.closed_edge_ids == ("edge-32",)
    assert materialized.objective == "protect-critical-services"
```

- [ ] **Step 2: Implement canonical planning input and objective penalties**

```python
# backend/src/wildfireops/application/exercise_planning.py
from dataclasses import dataclass
from hashlib import sha256
import json

from wildfireops.decision.task_optimizer import TaskDemand
from wildfireops.replay.exercise import ExerciseDefinition, ObjectivePreset


@dataclass(frozen=True, slots=True)
class MaterializedCheckpoint:
    checkpoint_key: str
    objective: ObjectivePreset
    tasks: tuple[TaskDemand, ...]
    resources: tuple[ResourceUnit, ...]
    closed_edge_ids: tuple[str, ...]
    asset_positions: Mapping[str, tuple[float, float]]
    asset_sources: Mapping[str, dict[str, str]]
    wind: dict[str, float] | None
    source_versions: dict[str, object]


def uncovered_penalty(
    task: ExerciseTask,
    weights: ObjectiveWeights,
) -> int:
    return (
        weights.base_priority_weight * task.base_priority
        + weights.critical_service_weight * int(task.critical_service)
        + weights.population_weight
        * (task.affected_population // weights.population_divisor)
    )


def planning_input_hash(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def materialize_checkpoint(
    definition: ExerciseDefinition,
    *,
    checkpoint_index: int,
    objective: ObjectivePreset,
    consequences: Mapping[str, object],
) -> MaterializedCheckpoint:
    checkpoint = definition.checkpoints[checkpoint_index]
    weights = definition.objectives[objective]
    resources = tuple(
        ResourceUnit(
            item.resource_id,
            item.capabilities,
            item.capacity,
            item.available,
            item.position.longitude,
            item.position.latitude,
        )
        for item in definition.resources
    )
    tasks = tuple(
        TaskDemand(
            item.task_id,
            item.incident_key,
            item.asset_id,
            item.required_capability,
            item.required_capacity,
            item.deadline_minutes,
            uncovered_penalty(item, weights),
        )
        for item in checkpoint.tasks
    )
    definition_assets = {
        item.asset_id: (item.position.longitude, item.position.latitude)
        for item in definition.assets
    }
    closed = (
        ()
        if checkpoint.disruption is None
        else checkpoint.disruption.closed_edge_ids
    )
    if (
        checkpoint_index == 2
        and consequences.get("corridorCleared") is True
    ):
        corridor_edges = set(
            definition.checkpoints[1].disruption.closed_edge_ids
            if definition.checkpoints[1].disruption is not None
            else ()
        )
        closed = tuple(edge_id for edge_id in closed if edge_id not in corridor_edges)
    return MaterializedCheckpoint(
        checkpoint_key=checkpoint.checkpoint_key,
        objective=objective,
        tasks=tasks,
        resources=resources,
        closed_edge_ids=tuple(sorted(closed)),
        asset_positions={
            asset_id: definition_assets[asset_id]
            for asset_id in sorted({item.asset_id for item in checkpoint.tasks})
        },
        asset_sources={
            item.asset_id: {
                "sourceName": item.source_name,
                "sourceVersion": item.source_version,
                "sourceRecordId": item.source_record_id,
                "citationUrl": item.citation_url,
                "provenance": item.provenance,
            }
            for item in definition.assets
            if item.asset_id in {task.asset_id for task in checkpoint.tasks}
        },
        wind=(
            None
            if checkpoint.disruption is None
            else {
                "speedMps": checkpoint.disruption.wind_speed_mps,
                "directionDegrees": (
                    checkpoint.disruption.wind_direction_degrees
                ),
            }
        ),
        source_versions={
            "exercise": definition.version,
            "graph": definition.graph_version,
            "replayPackage": definition.replay_package_id,
            "historicalWeatherIdentity": (
                checkpoint.historical_weather_identity
            ),
        },
    )


def serialize_planning_input(
    checkpoint: MaterializedCheckpoint,
    routes: tuple[TaskCandidateRoute, ...],
    locked_assignments: tuple[LockedTaskAssignment, ...] = (),
) -> dict[str, object]:
    return {
        "checkpointKey": checkpoint.checkpoint_key,
        "objective": checkpoint.objective,
        "closedEdgeIds": list(checkpoint.closed_edge_ids),
        "wind": checkpoint.wind,
        "resources": [
            {
                "resourceId": item.resource_id,
                "capabilities": sorted(item.capabilities),
                "capacity": item.capacity,
                "available": item.available,
                "longitude": item.longitude,
                "latitude": item.latitude,
            }
            for item in checkpoint.resources
        ],
        "tasks": [
            {
                "taskId": item.task_id,
                "incidentId": item.incident_id,
                "assetId": item.asset_id,
                "requiredCapability": item.required_capability,
                "requiredCapacity": item.required_capacity,
                "deadlineMinutes": item.deadline_minutes,
                "penalty": item.uncovered_penalty,
                "position": list(checkpoint.asset_positions[item.asset_id]),
                "assetSource": dict(
                    checkpoint.asset_sources[item.asset_id]
                ),
            }
            for item in checkpoint.tasks
        ],
        "routes": [
            {
                "resourceId": item.resource_id,
                "taskId": item.task_id,
                "status": item.route.status.value,
                "edgeIds": list(item.route.edge_ids),
                "distanceMeters": item.route.distance_meters,
                "travelMinutes": item.route.travel_minutes,
                "graphVersion": item.route.graph_version,
                "closureHash": item.route.closure_hash,
            }
            for item in routes
        ],
        "lockedAssignments": [
            {
                "resourceId": item.resource_id,
                "taskId": item.task_id,
            }
            for item in locked_assignments
        ],
        "sourceVersions": dict(checkpoint.source_versions),
    }
```

If `consequences["corridorCleared"] is True` at checkpoint three, remove the configured corridor edge from the closed-edge set. No other cross-checkpoint state is interpreted.

- [ ] **Step 3: Compute candidate routes with existing RoadGraph functions**

```python
def candidate_routes(
    graph: RoadGraph,
    resources: tuple[ResourceUnit, ...],
    tasks: tuple[TaskDemand, ...],
    asset_positions: Mapping[str, tuple[float, float]],
    closed_edge_ids: tuple[str, ...],
) -> tuple[TaskCandidateRoute, ...]:
    return tuple(
        TaskCandidateRoute(
            resource.resource_id,
            task.task_id,
            compute_route(
                graph,
                nearest_road_node(graph, resource.longitude, resource.latitude),
                nearest_road_node(
                    graph,
                    *asset_positions[task.asset_id],
                ),
                closed_edge_ids,
            ),
        )
        for resource in resources
        for task in tasks
    )


def serialize_task_result(
    result: TaskOptimizationResult,
    routes: tuple[TaskCandidateRoute, ...],
) -> dict[str, object]:
    route_by_pair = {
        (item.resource_id, item.task_id): item.route for item in routes
    }
    return {
        "status": result.status,
        "assignments": [
            {
                "resourceId": item.resource_id,
                "taskId": item.task_id,
                "incidentId": item.incident_id,
                "assetId": item.asset_id,
                "capacity": item.capacity,
                "travelMinutes": item.travel_minutes,
                "route": {
                    "status": route_by_pair[
                        (item.resource_id, item.task_id)
                    ].status.value,
                    "edgeIds": list(
                        route_by_pair[
                            (item.resource_id, item.task_id)
                        ].edge_ids
                    ),
                    "distanceMeters": route_by_pair[
                        (item.resource_id, item.task_id)
                    ].distance_meters,
                    "travelMinutes": route_by_pair[
                        (item.resource_id, item.task_id)
                    ].travel_minutes,
                },
            }
            for item in result.assignments
        ],
        "uncoveredTaskIds": list(result.uncovered_task_ids),
        "unassignedResourceIds": list(result.unassigned_resource_ids),
        "objectiveComponents": {
            "travelCost": result.travel_cost,
            "uncoveredTaskPenalty": result.uncovered_task_penalty,
            "objectiveValue": result.objective_value,
        },
        "bindingConstraints": list(result.binding_constraints),
        "runtimeMilliseconds": result.runtime_milliseconds,
        "algorithmVersion": result.algorithm_version,
    }
```

Call the existing signature exactly as shown: `compute_route(graph, origin_node, destination_node, closed_edge_ids)`. Candidate generation includes incompatible pairs so explanations can name incompatibility, matching the existing optimizer pattern.

- [ ] **Step 4: Implement plan generation as one transaction**

```python
class ExercisePlanningService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        graph: RoadGraph,
        repository: ExerciseRepositoryProtocol,
        session_service: ExerciseSessionService,
        clock: Callable[[], datetime],
    ) -> None:
        self._definition = definition
        self._graph = graph
        self._repository = repository
        self._session_service = session_service
        self._clock = clock

    async def generate_plan(
        self,
        session_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[ExercisePlanRun, dict[str, object]]:
        session, claim, replayed = await self._session_service.lock_command(
            session_id,
            expected_version,
            idempotency_key,
            "generate-plan",
            {},
        )
        if replayed is not None:
            plan_id = replayed.inputs.get("planId")
            if not isinstance(plan_id, str):
                raise RuntimeError("plan replay is missing plan ID")
            stored_replay = await self._repository.get_plan(UUID(plan_id))
            if stored_replay is None:
                raise RuntimeError("plan replay does not exist")
            replay_session = _session_from_state(replayed.after_state)
            return stored_replay, await session_projection(
                self._definition,
                self._repository,
                replay_session,
                self._clock(),
            )
        if session.objective is None:
            raise ExerciseTransitionInvalid("select an objective before planning")
        checkpoint = materialize_checkpoint(
            self._definition,
            checkpoint_index=session.checkpoint_index,
            objective=session.objective,
            consequences=session.consequences,
        )
        routes = candidate_routes(
            self._graph,
            checkpoint.resources,
            checkpoint.tasks,
            checkpoint.asset_positions,
            checkpoint.closed_edge_ids,
        )
        payload = serialize_planning_input(checkpoint, routes, ())
        result = solve_task_plan(
            TaskOptimizationRequest(
                resources=checkpoint.resources,
                tasks=checkpoint.tasks,
                routes=routes,
                locked_assignments=(),
                travel_weight=self._definition.objectives[
                    session.objective
                ].travel_weight,
                max_solver_seconds=2,
            )
        )
        previous = await self._repository.latest_plan_for_session(session.id)
        output = serialize_task_result(result, routes)
        previous_evidence = (
            None
            if previous is None
            else {
                **dict(previous.input_data),
                "assignments": previous.output_data.get("assignments", []),
            }
        )
        current_evidence = {
            **payload,
            "assignments": output["assignments"],
        }
        output["explanation"] = serialize_task_explanation(
            explain_task_plan(previous_evidence, current_evidence)
        )
        stored = await self._repository.store_plan(
            session_id=session.id,
            checkpoint_key=checkpoint.checkpoint_key,
            input_hash=planning_input_hash(payload),
            input_data=payload,
            output_data=output,
            versions={
                "exercise": self._definition.version,
                "graph": self._definition.graph_version,
                "taskAlgorithm": TASK_ALGORITHM_VERSION,
            },
            idempotency_key_id=claim.id,
        )
        before = _session_state(session)
        session.version += 1
        await self._repository.save_session(session)
        event = await self._repository.append_event(
            session_id=session.id,
            event_type="exercise.plan-generated",
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs={"planId": str(stored.id), "inputHash": stored.input_hash},
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="exercise_event",
            response_id=event.id,
        )
        return stored, await session_projection(
            self._definition,
            self._repository,
            session,
            self._clock(),
        )
```

An `UNKNOWN` plan is stored for evidence and retry but is not actionable.

- [ ] **Step 5: Implement the shelter bus override validator**

```python
async def apply_override(
    self,
    session_id: UUID,
    *,
    resource_id: str,
    task_id: str,
    expected_version: int,
    idempotency_key: str,
) -> tuple[ExercisePlanRun, dict[str, object]]:
    session, claim, replayed = await self._session_service.lock_command(
        session_id,
        expected_version,
        idempotency_key,
        "apply-override",
        {"resourceId": resource_id, "taskId": task_id},
    )
    if replayed is not None:
        replayed_plan_id = replayed.inputs.get("planId")
        if not isinstance(replayed_plan_id, str):
            raise RuntimeError("override replay is missing plan ID")
        stored_replay = await self._repository.get_plan(UUID(replayed_plan_id))
        if stored_replay is None:
            raise RuntimeError("override replay plan does not exist")
        replay_session = _session_from_state(replayed.after_state)
        return stored_replay, await session_projection(
            self._definition,
            self._repository,
            replay_session,
            self._clock(),
        )
    if session.checkpoint_index != 2:
        raise ExerciseTransitionInvalid("override requires checkpoint three")
    if task_id != "shelter-capacity-transport":
        raise ExerciseCommandInvalid("guided override must target shelter transport")
    current = await self._repository.latest_plan(session.id, "field-report")
    if current is None:
        raise ExerciseTransitionInvalid("generate checkpoint-three plan first")
    locked = (LockedTaskAssignment(resource_id, task_id),)
    if session.objective is None:
        raise ExerciseTransitionInvalid("select an objective before overriding")
    if current.input_data.get("objective") != session.objective:
        raise ExerciseTransitionInvalid(
            "generate checkpoint-three plan for the selected objective"
        )
    checkpoint = materialize_checkpoint(
        self._definition,
        checkpoint_index=session.checkpoint_index,
        objective=session.objective,
        consequences=session.consequences,
    )
    routes = candidate_routes(
        self._graph,
        checkpoint.resources,
        checkpoint.tasks,
        checkpoint.asset_positions,
        checkpoint.closed_edge_ids,
    )
    base_payload = serialize_planning_input(checkpoint, routes, ())
    if planning_input_hash(base_payload) != current.input_hash:
        raise ExerciseVersionConflict("checkpoint planning input changed")
    payload = serialize_planning_input(checkpoint, routes, locked)
    request = TaskOptimizationRequest(
        resources=checkpoint.resources,
        tasks=checkpoint.tasks,
        routes=routes,
        locked_assignments=(),
        travel_weight=self._definition.objectives[
            session.objective
        ].travel_weight,
        max_solver_seconds=2,
    )
    result = solve_task_plan(
        replace(request, locked_assignments=locked)
    )
    assignment = next(
        (
            item
            for item in result.assignments
            if item.resource_id == resource_id and item.task_id == task_id
        ),
        None,
    )
    if assignment is None:
        raise ExerciseCommandInvalid(
            "override fails capability, capacity, route, deadline, or uniqueness"
        )
    output = serialize_task_result(result, routes)
    output["explanation"] = serialize_task_explanation(
        explain_task_plan(
            {
                **dict(current.input_data),
                "assignments": current.output_data.get("assignments", []),
            },
            {
                **payload,
                "assignments": output["assignments"],
            },
        )
    )
    output["operatorOverride"] = {
        "resourceId": resource_id,
        "taskId": task_id,
        "beforePlanId": str(current.id),
    }
    stored = await self._repository.store_plan(
        session_id=session.id,
        checkpoint_key=current.checkpoint_key,
        input_hash=planning_input_hash(payload),
        input_data=payload,
        output_data=output,
        versions=dict(current.versions),
        idempotency_key_id=claim.id,
    )
    before = _session_state(session)
    session.version += 1
    session.consequences["lastPlanId"] = str(stored.id)
    await self._repository.save_session(session)
    event = await self._repository.append_event(
        session_id=session.id,
        event_type="exercise.override-applied",
        actor_callsign=session.callsign,
        display_name=session.display_name,
        expected_session_version=expected_version,
        resulting_session_version=session.version,
        before_state=before,
        after_state=_session_state(session),
        inputs={
            "beforePlanId": str(current.id),
            "planId": str(stored.id),
            "resourceId": resource_id,
            "taskId": task_id,
        },
        note=None,
    )
    await self._repository.complete_idempotency(
        claim_id=claim.id,
        response_type="exercise_event",
        response_id=event.id,
    )
    return stored, await session_projection(
        self._definition,
        self._repository,
        session,
        self._clock(),
    )
```

Reconstruct the typed request from stored canonical input; never deserialize arbitrary class names.

- [ ] **Step 6: Prove planning and override behavior**

Add these cases:

| Test | Required assertion |
|---|---|
| `test_all_three_objectives_compute_different_penalties` | The same critical/populated task yields three exact integer penalties from fixture weights |
| `test_checkpoint_two_routes_apply_closure` | Every selected route omits the configured closed edge |
| `test_checkpoint_three_reopens_corridor_only_after_crew_assignment` | `corridorCleared=True` removes exactly that edge; `False` retains it |
| `test_duplicate_plan_command_replays_same_plan` | Repeating key and payload returns the first plan ID and creates no rows |
| `test_unknown_plan_is_stored_but_cannot_advance` | Plan status is `UNKNOWN`; `advance` raises `ExerciseTransitionInvalid` |
| `test_override_rejects_non_bus_resource` | Engine-to-shelter override returns the exact eligibility error |
| `test_override_rejects_unreachable_shelter_route` | Bus override with an unreachable route is rejected |
| `test_override_recalculates_uncovered_tasks_and_objective` | Shelter becomes covered, displaced task becomes uncovered, and objective total equals component sum |
| `test_invalid_override_does_not_store_plan_or_event` | Plan and event counts do not change |

- [ ] **Step 7: Run planning tests and commit**

```bash
cd backend
uv run pytest tests/unit/application/test_exercise_planning.py \
  tests/unit/application/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercise_planning.py \
  src/wildfireops/application/exercises.py \
  tests/unit/application/test_exercise_planning.py
uv run mypy src/wildfireops/application/exercise_planning.py
cd ..
git add backend/src/wildfireops/application/exercise_planning.py \
  backend/src/wildfireops/application/exercises.py \
  backend/src/wildfireops/persistence/exercises.py \
  backend/tests/unit/application/test_exercise_planning.py \
  backend/tests/unit/application/test_exercises.py
git commit -m "feat(exercise): generate and override checkpoint plans"
```

---

### Task 7: Expose the exercise API and stable error contract

**Files:**
- Create: `backend/src/wildfireops/api/schemas/exercises.py`
- Create: `backend/src/wildfireops/api/routes/exercises.py`
- Modify: `backend/src/wildfireops/application/commands.py`
- Modify: `backend/src/wildfireops/api/dependencies.py`
- Modify: `backend/src/wildfireops/api/command_errors.py`
- Modify: `backend/src/wildfireops/main.py`
- Test: `backend/tests/integration/api/test_exercises.py`
- Test: `backend/tests/architecture/test_api_boundaries.py`

**Interfaces:**
- Consumes: application services and projections from Tasks 5–6.
- Produces: the representative routes approved in the design and JSON response types used by the future Claude Code frontend.

- [ ] **Step 1: Write a failing create/read API contract test**

```python
# backend/tests/integration/api/test_exercises.py
@pytest.mark.asyncio
async def test_create_and_read_exercise_session(exercise_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=exercise_app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/exercises/park-fire-decision/sessions",
            headers={"Idempotency-Key": "create-session-1"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["exerciseId"] == "park-fire-decision"
        assert body["status"] == "active"
        assert body["version"] == 1
        assert body["allowedActions"] == ["select-objective"]

        restored = await client.get(
            f"/api/exercise-sessions/{body['id']}"
        )
        assert restored.status_code == 200
        assert restored.json() == body
```

- [ ] **Step 2: Define request and response schemas**

```python
# backend/src/wildfireops/api/schemas/exercises.py
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from wildfireops.api.schemas.incidents import ApiModel


class SessionCommand(ApiModel):
    expected_version: int = Field(ge=1)


class SelectObjectiveRequest(SessionCommand):
    objective: Literal[
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    ]


class OverrideRequest(SessionCommand):
    resource_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class ExerciseDecisionRequest(SessionCommand):
    display_name: str | None = Field(default=None, max_length=120)
    note: str = Field(min_length=1, max_length=2000)


class ExerciseSessionResponse(ApiModel):
    id: str
    exercise_id: str
    definition_version: str
    callsign: str
    display_name: str | None
    checkpoint_index: int
    objective: str | None
    status: str
    version: int
    expires_at: datetime
    allowed_actions: tuple[str, ...]
    current_checkpoint: dict[str, JsonValue]
    latest_plan: dict[str, JsonValue] | None


class ExerciseMetadataResponse(ApiModel):
    exercise_id: str
    version: str
    name: str
    description: str
    checkpoint_count: int
    objectives: tuple[str, ...]
    safety_statement: str
    assets: tuple[dict[str, JsonValue], ...]
    resources: tuple[dict[str, JsonValue], ...]


class ExercisePlanResponse(ApiModel):
    id: str
    session_id: str
    checkpoint_key: str
    input_hash: str
    input_data: dict[str, JsonValue]
    output_data: dict[str, JsonValue]
    versions: dict[str, JsonValue]
    created_at: datetime


class ExercisePlanCommandResponse(ApiModel):
    session: ExerciseSessionResponse
    plan: ExercisePlanResponse


class ExerciseEventResponse(ApiModel):
    id: str
    session_id: str
    event_type: str
    actor_callsign: str
    display_name: str | None
    expected_session_version: int
    resulting_session_version: int
    before_state: dict[str, JsonValue]
    after_state: dict[str, JsonValue]
    inputs: dict[str, JsonValue]
    note: str | None
    occurred_at: datetime


class ExerciseAuditResponse(ApiModel):
    items: tuple[ExerciseEventResponse, ...]


class ExerciseDebriefResponse(ApiModel):
    session: dict[str, JsonValue]
    plans: tuple[dict[str, JsonValue], ...]
    final_plan: dict[str, JsonValue]
    events: tuple[dict[str, JsonValue], ...]
```

- [ ] **Step 3: Add command routes**

```python
# backend/src/wildfireops/api/routes/exercises.py
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from wildfireops.api.dependencies import (
    get_exercise_planning_service,
    get_exercise_query_service,
    get_exercise_session_service,
)


router = APIRouter(tags=["exercises"])


@router.post(
    "/api/exercises/{exercise_id}/sessions",
    response_model=ExerciseSessionResponse,
    status_code=201,
)
async def create_session(
    exercise_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExerciseSessionService,
        Depends(get_exercise_session_service, scope="function"),
    ],
) -> ExerciseSessionResponse:
    if exercise_id != service.exercise_id:
        raise exercise_api_error(ExerciseNotFound("exercise was not found"))
    session = await service.create(idempotency_key=idempotency_key)
    return ExerciseSessionResponse.model_validate(await service.project(session))
```

Add the remaining routes with these exact contracts. Every post-creation command
route also injects `ExerciseQueryService`. On `ExerciseVersionConflict` or
`ExerciseTransitionInvalid`, it reads the current session projection and passes
that projection to `exercise_api_error`; the command transaction then rolls
back. Other `ExerciseError` instances map directly.

| Method and path | Body | Service call |
|---|---|---|
| `GET /api/exercises/{exercise_id}` | none | `ExerciseQueryService.metadata(exercise_id)` |
| `GET /api/exercise-sessions/{session_id}` | none | `ExerciseQueryService.session(UUID(session_id))` |
| `POST /api/exercise-sessions/{session_id}/objective` | `SelectObjectiveRequest` | `select_objective(UUID(session_id), body.objective, expected_version=body.expected_version, idempotency_key=idempotency_key)` |
| `POST /api/exercise-sessions/{session_id}/plans` | `SessionCommand` | `generate_plan(UUID(session_id), expected_version=body.expected_version, idempotency_key=idempotency_key)` |
| `POST /api/exercise-sessions/{session_id}/advance` | `SessionCommand` | `advance(UUID(session_id), expected_version=body.expected_version, idempotency_key=idempotency_key)` |
| `POST /api/exercise-sessions/{session_id}/overrides` | `OverrideRequest` | `apply_override(UUID(session_id), resource_id=body.resource_id, task_id=body.task_id, expected_version=body.expected_version, idempotency_key=idempotency_key)` |
| `POST /api/exercise-sessions/{session_id}/decisions` | `ExerciseDecisionRequest` | `decide(UUID(session_id), display_name=body.display_name, note=body.note, expected_version=body.expected_version, idempotency_key=idempotency_key)` |
| `GET /api/exercise-sessions/{session_id}/audit` | none | `ExerciseQueryService.audit(UUID(session_id))` |
| `GET /api/exercise-sessions/{session_id}/debrief` | none | `ExerciseQueryService.debrief(UUID(session_id))` |

Use `201` for session, plan, override, and decision creation; use `200` for reads, objective replacement, and advance.
Session-changing routes return `ExerciseSessionResponse`; plan and override
routes return `ExercisePlanCommandResponse`; audit returns `ExerciseAuditResponse`;
debrief returns `ExerciseDebriefResponse`. Map application projections
explicitly:

```python
def plan_response(plan: ExercisePlanRun) -> ExercisePlanResponse:
    return ExercisePlanResponse(
        id=str(plan.id),
        sessionId=str(plan.session_id),
        checkpointKey=plan.checkpoint_key,
        inputHash=plan.input_hash,
        inputData=dict(plan.input_data),
        outputData=dict(plan.output_data),
        versions=dict(plan.versions),
        createdAt=plan.created_at,
    )


def event_response(event: ExerciseEvent) -> ExerciseEventResponse:
    return ExerciseEventResponse(
        id=str(event.id),
        sessionId=str(event.session_id),
        eventType=event.event_type,
        actorCallsign=event.actor_callsign,
        displayName=event.display_name,
        expectedSessionVersion=event.expected_session_version,
        resultingSessionVersion=event.resulting_session_version,
        beforeState=dict(event.before_state),
        afterState=dict(event.after_state),
        inputs=dict(event.inputs),
        note=event.note,
        occurredAt=event.occurred_at,
    )


def plan_command_response(
    plan: ExercisePlanRun,
    session: dict[str, object],
) -> ExercisePlanCommandResponse:
    return ExercisePlanCommandResponse(
        session=ExerciseSessionResponse.model_validate(session),
        plan=plan_response(plan),
    )
```

- [ ] **Step 4: Wire service providers and router**

In `application/commands.py`, add context managers:

```python
@asynccontextmanager
async def exercise_sessions(self) -> AsyncIterator[ExerciseSessionService]:
    definition = self._exercise_definition
    if definition is None:
        raise ExerciseNotFound("exercise is not configured")
    async with self._session_factory() as session:
        async with session.begin():
            repository = ExerciseRepository(session)
            yield ExerciseSessionService(
                definition=definition,
                definition_digest=exercise_definition_digest(definition),
                repository=repository,
                clock=self._clock,
                callsign=self._callsign,
            )

@asynccontextmanager
async def exercise_planning(self) -> AsyncIterator[ExercisePlanningService]:
    definition = self._exercise_definition
    if definition is None:
        raise ExerciseNotFound("exercise is not configured")
    graph = self._graphs().get(definition.graph_version)
    if graph is None:
        raise ExerciseCommandInvalid("exercise graph is unavailable")
    async with self._session_factory() as session:
        async with session.begin():
            repository = ExerciseRepository(session)
            session_service = ExerciseSessionService(
                definition=definition,
                definition_digest=exercise_definition_digest(definition),
                repository=repository,
                clock=self._clock,
                callsign=self._callsign,
            )
            yield ExercisePlanningService(
                definition=definition,
                graph=graph,
                repository=repository,
                session_service=session_service,
                clock=self._clock,
            )

@asynccontextmanager
async def exercise_queries(self) -> AsyncIterator[ExerciseQueryService]:
    definition = self._exercise_definition
    if definition is None:
        raise ExerciseNotFound("exercise is not configured")
    async with self._session_factory() as session:
        yield ExerciseQueryService(
            definition=definition,
            repository=ExerciseRepository(session),
            clock=self._clock,
        )
```

Extend `CommandServiceProvider.__init__` with `exercise_definition`, `clock`, and `callsign` providers and assign them to the corresponding private attributes. Exercise asset positions come from the already validated definition. Command services use `async with session.begin()`; query service does not start a write transaction.

In `main.py`, load:

```python
exercise_definition = (
    None if resolved.replay_package is None
    else load_exercise_definition(loader)
)
```

Store it on `app.state.exercise_definition`, pass it to `CommandServiceProvider`, and include `exercise_router`.

- [ ] **Step 5: Add stable error mapping**

```python
# backend/src/wildfireops/api/command_errors.py
def exercise_api_error(
    error: ExerciseError,
    *,
    current_state: dict[str, object] | None = None,
) -> ApiError:
    if isinstance(error, (ExerciseNotFound, ExerciseSessionNotFound)):
        return ApiError(status_code=404, code=error.code, message=str(error))
    if isinstance(error, ExerciseSessionExpired):
        return ApiError(
            status_code=410,
            code=error.code,
            message=str(error),
            details={"action": "start-new-exercise"},
        )
    if isinstance(
        error,
        (
            ExerciseVersionConflict,
            ExerciseTransitionInvalid,
            ExerciseIdempotencyConflict,
        ),
    ):
        return ApiError(
            status_code=409,
            code=error.code,
            message=str(error),
            details=(
                {}
                if current_state is None
                else {
                    "currentSession": current_state,
                    "allowedActions": current_state["allowedActions"],
                }
            ),
        )
    if isinstance(error, ExerciseCommandInvalid):
        return ApiError(status_code=422, code=error.code, message=str(error))
    return ApiError(
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
```

Version and transition conflicts include the complete current session projection
and `allowedActions` in `details`.

- [ ] **Step 6: Prove the full API state contract**

Add these integration cases:

| Test | Required HTTP assertion |
|---|---|
| `test_metadata_discloses_historical_plus_simulated_boundary` | `200`; safety statement, three objective IDs, cited historical assets, and exercise-provenance resources are present |
| `test_objective_requires_expected_version_and_idempotency_key` | Missing header is `422`; missing body field is `422` |
| `test_stale_version_returns_current_state_in_409_details` | `409`; details contain exact current version and allowed actions |
| `test_generate_plan_returns_assignments_constraints_and_versions` | `201`; response includes all approved evidence fields |
| `test_unreachable_task_is_200_with_uncovered_state` | `201`; task is in `uncoveredTaskIds`, not an API error |
| `test_advance_requires_actionable_latest_plan` | `409` before planning and after `UNKNOWN` result |
| `test_invalid_override_is_422_and_plan_is_unchanged` | `422`; subsequent session read returns the previous plan ID |
| `test_expired_session_is_410` | `410`; details equal `{"action": "start-new-exercise"}` |
| `test_final_decision_requires_note` | Blank note returns `422` |
| `test_audit_is_ordered_and_session_scoped` | Events are ordered and another session ID returns only its own events |
| `test_debrief_restores_after_new_client_request` | A fresh HTTP client receives the same completed debrief JSON |

- [ ] **Step 7: Run API and architecture tests**

```bash
cd backend
uv run pytest tests/integration/api/test_exercises.py \
  tests/architecture/test_api_boundaries.py -q
uv run ruff check src/wildfireops/api/schemas/exercises.py \
  src/wildfireops/api/routes/exercises.py \
  src/wildfireops/api/dependencies.py \
  src/wildfireops/api/command_errors.py \
  src/wildfireops/application/commands.py \
  src/wildfireops/main.py
uv run mypy src/wildfireops/api/schemas/exercises.py \
  src/wildfireops/api/routes/exercises.py
```

Expected: all checks pass.

- [ ] **Step 8: Commit the API**

```bash
git add backend/src/wildfireops/api/schemas/exercises.py \
  backend/src/wildfireops/api/routes/exercises.py \
  backend/src/wildfireops/api/dependencies.py \
  backend/src/wildfireops/api/command_errors.py \
  backend/src/wildfireops/application/commands.py \
  backend/src/wildfireops/main.py \
  backend/tests/integration/api/test_exercises.py \
  backend/tests/architecture/test_api_boundaries.py
git commit -m "feat(exercise): expose session planning API"
```

---

### Task 8: Curate the committed Park Fire Decision Exercise fixture

**Files:**
- Create: `data/replay/park-fire/exercise.json`
- Create: `data/replay/park-fire/exercise_golden_outputs.json`
- Modify: `backend/src/wildfireops/replay/manifest.py`
- Modify: `backend/tests/unit/replay/test_manifest.py`
- Modify: `data/replay/park-fire/manifest.json`
- Modify: `backend/tests/unit/replay/test_park_fire_package.py`
- Test: `backend/tests/integration/replay/test_park_fire_exercise_golden.py`

**Interfaces:**
- Consumes: the approved definition schema, existing Park Fire observations, pinned road graph, exact public OSM/Census identities, and exercise APIs.
- Produces: one integrity-hashed exercise definition whose public asset references are historical, whose demands/resources/disruptions are explicitly simulated, and whose three objective paths reach a valid shelter-bus override.

- [ ] **Step 1: Add failing committed-package assertions**

```python
# backend/tests/unit/replay/test_park_fire_package.py
def test_committed_park_fire_exercise_is_complete() -> None:
    package = Path(__file__).parents[4] / "data/replay/park-fire"
    loader = ReplayLoader(package)
    definition = load_exercise_definition(loader)

    assert definition is not None
    assert definition.exercise_id == "park-fire-decision"
    assert len(definition.checkpoints) == 3
    assert set(definition.objectives) == {
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    }
    assert {item.resource_type for item in definition.resources} == {
        "engine",
        "evacuation-bus",
        "medical-team",
        "road-crew",
    }
    assert all(
        item.provenance == "exercise" for item in definition.resources
    )
    assert any(
        incident.provenance == "exercise"
        for checkpoint in definition.checkpoints
        for incident in checkpoint.incidents
    )
```

- [ ] **Step 2: Select and pin real public asset references without changing Live Monitor data**

Query OpenStreetMap’s public Overpass endpoint over the manifest bbox
`(south=39.7, west=-121.9, north=40.3, east=-121.53)` for named hospitals,
community centres, communications towers, and power substations. Discard
unnamed or geometry-less results, then choose the road-snappable feature nearest
the Park Fire historical detection centroid, breaking ties by
`(OSM element type, OSM ID)`. A community centre may have the simulated role of
receiving shelter, but its public name and OSM identity remain unchanged.

Store the selected references only in `exercise.json` as `assets`. Each entry
records `sourceName: "OpenStreetMap"`, the OSM data timestamp as
`sourceVersion`, an exact `node/<id>`, `way/<id>`, or `relation/<id>`
`sourceRecordId`, and `https://www.openstreetmap.org/<sourceRecordId>` as the
citation. Copy existing Census community identities from
`exposed_assets.geojson` into the exercise definition; do not alter the Live
Monitor file. Mark facility/community identity and coordinates as historical,
while task demand remains simulated.

Run this read-only query from `backend/` to obtain the candidate set and the
OSM data timestamp:

```bash
uv run python - <<'PY'
import json
from math import hypot
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

query = """
[out:json][timeout:60];
(
  nwr["amenity"="hospital"]["name"](39.7,-121.9,40.3,-121.53);
  nwr["amenity"="community_centre"]["name"](39.7,-121.9,40.3,-121.53);
  nwr["man_made"="communications_tower"]["name"](39.7,-121.9,40.3,-121.53);
  nwr["man_made"="tower"]["tower:type"="communication"]["name"](39.7,-121.9,40.3,-121.53);
  nwr["power"="substation"]["name"](39.7,-121.9,40.3,-121.53);
);
out center tags meta;
"""
url = "https://overpass-api.de/api/interpreter?" + urlencode({"data": query})
with urlopen(url, timeout=90) as response:
    payload = json.load(response)
detections = [
    json.loads(line)
    for line in Path("../data/replay/park-fire/fire_detections.jsonl")
    .read_text()
    .splitlines()
]
centroid = (
    sum(item["longitude"] for item in detections) / len(detections),
    sum(item["latitude"] for item in detections) / len(detections),
)
candidates = []
for item in payload["elements"]:
    longitude = item.get("lon", item.get("center", {}).get("lon"))
    latitude = item.get("lat", item.get("center", {}).get("lat"))
    name = item.get("tags", {}).get("name")
    if longitude is None or latitude is None or not name:
        continue
    candidates.append(
        {
            "distance": hypot(longitude - centroid[0], latitude - centroid[1]),
            "sourceRecordId": f"{item['type']}/{item['id']}",
            "name": name,
            "longitude": longitude,
            "latitude": latitude,
            "tags": item["tags"],
        }
    )
print(payload["osm3s"]["timestamp_osm_base"])
print(json.dumps(sorted(candidates, key=lambda item: (
    item["distance"], item["sourceRecordId"]
)), indent=2, sort_keys=True))
PY
```

After the deterministic selection, verify every committed definition asset
snaps to the graph:

```bash
cd backend
uv run python - <<'PY'
from pathlib import Path
from wildfireops.geospatial.road_graph import RoadGraph, nearest_road_node
from wildfireops.replay.exercise import load_exercise_definition
from wildfireops.replay.loader import ReplayLoader

package = Path("../data/replay/park-fire")
loader = ReplayLoader(package)
definition = load_exercise_definition(loader)
assert definition is not None
graph = RoadGraph.load(package / loader.manifest.road_graph.filename)
for asset in definition.assets:
    longitude = asset.position.longitude
    latitude = asset.position.latitude
    assert nearest_road_node(graph, longitude, latitude) in graph._graph
print(len(definition.assets), "exercise assets snap to the pinned graph")
PY
```

Expected: prints the final asset count and exits zero.

- [ ] **Step 3: Commit the approved simulated resource mix**

`exercise.json` defines a scarce inventory containing engines, evacuation buses, medical teams, and exactly one road crew. Each resource contains:

```json
{
  "resourceId": "exercise-bus-1",
  "resourceType": "evacuation-bus",
  "capabilities": ["evacuation-transport"],
  "capacity": 40,
  "available": true,
  "position": {"longitude": -121.6064, "latitude": 39.754192},
  "provenance": "exercise"
}
```

Use stable `exercise-` IDs for every simulated resource. Keep this inventory
inside `exercise.json`; the exercise API returns it to the future UI, so no
duplicate write to Live Monitor’s `resources.json` is needed.

- [ ] **Step 4: Build the three checkpoints**

Use exact UTC checkpoint times already covered by the replay observations. The committed definition must satisfy:

```python
assert checkpoint_1.reference_at < checkpoint_2.reference_at < checkpoint_3.reference_at
assert {item.incident_key for item in checkpoint_1.incidents} == {"park-fire"}
assert {item.incident_key for item in checkpoint_2.incidents} == {
    "park-fire",
    "spot-fire",
}
assert checkpoint_2.disruption is not None
assert checkpoint_2.disruption.closed_edge_ids
assert checkpoint_2.disruption.wind_direction_degrees != (
    checkpoint_1.disruption.wind_direction_degrees
    if checkpoint_1.disruption else None
)
assert any(
    report.task_id == "shelter-capacity-transport"
    for report in checkpoint_3.field_reports
)
```

All historical incident detections use exact `source_record_id` values from `fire_detections.jsonl`. The spot fire, closure, tasks, deadlines, resources, and field report use `provenance: "exercise"`.
The definition’s sandbox permits all three checkpoint keys, only the curated
closure edge from Step 5, three named wind presets, and exact priority
multipliers `{"standard": 1, "elevated": 2, "urgent": 3}`.

- [ ] **Step 5: Choose a consequential road closure from an actual route**

Generate the checkpoint-one plan, choose an edge traversed by at least one selected route, and set that exact edge as the checkpoint-two closure. Assert:

```python
assert closed_edge_id in checkpoint_one_selected_route_edge_ids
assert all(
    closed_edge_id not in assignment["route"]["edgeIds"]
    for assignment in checkpoint_two_output["assignments"]
)
```

The `clear-primary-corridor` task requires the road crew capability. When accepted, checkpoint three removes only that edge from the closure set.

- [ ] **Step 6: Tune objective weights against behavior, not arbitrary scores**

Run all three presets at checkpoints one and two. Accept weights only when:

```python
semantic_plans = {
    objective: tuple(
        sorted(
            (item["resourceId"], item["taskId"])
            for item in output["assignments"]
        )
    )
    for objective, output in outputs.items()
}


def shelter_override_is_valid(output: dict[str, object]) -> bool:
    override = output.get("operatorOverride")
    assignments = output.get("assignments")
    return (
        isinstance(override, dict)
        and override.get("taskId") == "shelter-capacity-transport"
        and isinstance(assignments, list)
        and any(
            isinstance(item, dict)
            and item.get("resourceId") == override.get("resourceId")
            and item.get("taskId") == "shelter-capacity-transport"
            for item in assignments
        )
    )


assert len(set(semantic_plans.values())) >= 2
assert all(output["uncoveredTaskIds"] for output in checkpoint_two_outputs.values())
assert all(
    shelter_override_is_valid(output)
    for output in checkpoint_three_outputs.values()
)
```

Store integer weights in `exercise.json`; do not add hidden per-objective assignments.

- [ ] **Step 7: Generate and pin semantic golden output**

`exercise_golden_outputs.json` stores, for each objective and checkpoint:

- input hash;
- task IDs and penalties;
- assignment resource/task pairs;
- route edge IDs;
- covered and uncovered task IDs;
- objective components;
- binding-constraint codes;
- causal codes;
- corridor-cleared consequence; and
- final override and audit semantics.

The integration test loads the committed package, runs the actual services, materializes the semantic subset, and asserts exact equality with the golden file.

- [ ] **Step 8: Recompute package hashes atomically**

Add this immutable helper and unit test:

```python
# backend/src/wildfireops/replay/manifest.py
def with_files(self, updates: Mapping[str, str]) -> "ReplayManifest":
    return replace(self, files={**self.files, **dict(updates)})


# backend/tests/unit/replay/test_manifest.py
def test_with_files_returns_valid_replacement_without_mutating_original() -> None:
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)
    replaced = manifest.with_files({"exercise.json": "a" * 64})
    assert "exercise.json" not in manifest.files
    assert replaced.files["exercise.json"] == "a" * 64
```

Use the existing atomic manifest writer rather than editing hashes by hand. Hash:

```text
exercise.json
exercise_golden_outputs.json
```

Run this exact mechanical update from `backend/`:

```bash
uv run python - <<'PY'
from hashlib import sha256
from pathlib import Path

from wildfireops.replay.manifest import ReplayManifest

package = Path("../data/replay/park-fire")
path = package / "manifest.json"
before = path.read_bytes()
manifest = ReplayManifest.load(path)
filenames = (
    "exercise.json",
    "exercise_golden_outputs.json",
)
updates = {
    filename: sha256((package / filename).read_bytes()).hexdigest()
    for filename in filenames
}
manifest.with_files(updates).write_atomic(
    path,
    expected_digest=sha256(before).hexdigest(),
)
PY
```

Then run:

```bash
cd backend
uv run pytest tests/unit/replay/test_park_fire_package.py \
  tests/integration/replay/test_park_fire_exercise_golden.py -q
```

Expected: package validation and semantic golden journey pass.

- [ ] **Step 9: Commit the fixture**

```bash
git add data/replay/park-fire \
  backend/src/wildfireops/replay/manifest.py \
  backend/tests/unit/replay/test_manifest.py \
  backend/tests/unit/replay/test_park_fire_package.py \
  backend/tests/integration/replay/test_park_fire_exercise_golden.py
git commit -m "feat(exercise): add Park Fire decision fixture"
```

---

### Task 9: Add the bounded, non-mutating sandbox

**Files:**
- Modify: `backend/src/wildfireops/application/exercise_planning.py`
- Modify: `backend/src/wildfireops/api/schemas/exercises.py`
- Modify: `backend/src/wildfireops/api/routes/exercises.py`
- Test: `backend/tests/unit/application/test_exercise_planning.py`
- Test: `backend/tests/integration/api/test_exercises.py`

**Interfaces:**
- Consumes: a completed guided session plus definition-bounded objective,
  checkpoint, closure, wind, availability, priority, and lock controls.
- Produces: `POST /api/exercise-sessions/{session_id}/sandbox-plans`, returning
  canonical input, input hash, and the same task-planner output without writing
  a plan run, event, or session change.

- [ ] **Step 1: Add a failing non-mutation test**

```python
@pytest.mark.asyncio
async def test_sandbox_plan_does_not_change_guided_state(
    completed_exercise: CompletedExercise,
) -> None:
    before = await completed_exercise.repository.counts(
        completed_exercise.session.id
    )
    result = await completed_exercise.planning.generate_sandbox_plan(
        completed_exercise.session.id,
        SandboxPlanControls(
            expected_version=completed_exercise.session.version,
            checkpoint_key="cascade",
            objective="maximize-population-coverage",
            closed_edge_ids=(),
            wind_preset="strong-northeast",
            unavailable_resource_ids=frozenset({"exercise-engine-1"}),
            task_priority_presets={
                "community-evacuation": "urgent",
            },
            locked_assignments=(),
        ),
    )

    assert result["sandbox"] is True
    assert result["output"]["status"] in {"FEASIBLE", "OPTIMAL"}
    assert (
        await completed_exercise.repository.counts(
            completed_exercise.session.id
        )
        == before
    )
```

Define `CompletedExercise` in the test file as a dataclass containing the
already completed `ExerciseSession`, `ExercisePlanningService`, and
`FakeExerciseRepository`; its fixture completes the exact guided journey from
Task 6 once and exposes the fake repository’s `(plans, events, session_version)`
counts.

- [ ] **Step 2: Define the transport-neutral bounded controls**

```python
# backend/src/wildfireops/application/exercise_planning.py
type TaskPriorityPreset = Literal["standard", "elevated", "urgent"]


@dataclass(frozen=True, slots=True)
class SandboxPlanControls:
    expected_version: int
    checkpoint_key: str
    objective: ObjectivePreset
    closed_edge_ids: tuple[str, ...]
    wind_preset: str
    unavailable_resource_ids: frozenset[str]
    task_priority_presets: Mapping[str, TaskPriorityPreset]
    locked_assignments: tuple[LockedTaskAssignment, ...]
```

- [ ] **Step 3: Validate graph-backed definition controls at startup**

```python
def validate_exercise_graph(
    definition: ExerciseDefinition,
    graph: RoadGraph,
) -> None:
    configured_closures = {
        edge_id
        for checkpoint in definition.checkpoints
        if checkpoint.disruption is not None
        for edge_id in checkpoint.disruption.closed_edge_ids
    } | set(definition.sandbox.closure_edge_ids)
    unknown = sorted(configured_closures - graph.edge_ids)
    if unknown:
        raise ReplayPackageCorrupt(
            f"exercise.json: unknown road edge ID: {unknown[0]}"
        )
    for resource in definition.resources:
        nearest_road_node(
            graph,
            resource.position.longitude,
            resource.position.latitude,
        )
    for asset in definition.assets:
        nearest_road_node(
            graph,
            asset.position.longitude,
            asset.position.latitude,
        )
```

Call `validate_exercise_graph(exercise_definition, graph)` in `main.py` after
both objects load and before the router is served. Add a startup test whose
definition contains `missing-edge` and assert the exact error above.

- [ ] **Step 4: Reuse materialization, routing, solving, and explanations**

```python
async def generate_sandbox_plan(
    self,
    session_id: UUID,
    controls: SandboxPlanControls,
) -> dict[str, object]:
    session = await self._repository.get_session(session_id)
    if session is None:
        raise ExerciseSessionNotFound("exercise session was not found")
    if session.status != "completed":
        raise ExerciseTransitionInvalid(
            "sandbox requires a completed guided exercise"
        )
    if session.version != controls.expected_version:
        raise ExerciseVersionConflict(
            f"expected session version {controls.expected_version}, "
            f"current version {session.version}"
        )
    allowed = self._definition.sandbox
    if controls.checkpoint_key not in allowed.checkpoint_keys:
        raise ExerciseCommandInvalid(
            f"sandbox checkpoint is not allowed: {controls.checkpoint_key}"
        )
    if controls.objective not in self._definition.objectives:
        raise ExerciseCommandInvalid(
            f"unsupported objective: {controls.objective}"
        )
    unknown_edges = sorted(
        set(controls.closed_edge_ids) - allowed.closure_edge_ids
    )
    if unknown_edges:
        raise ExerciseCommandInvalid(
            f"sandbox closure is not allowed: {unknown_edges[0]}"
        )
    wind = allowed.wind_presets.get(controls.wind_preset)
    if wind is None:
        raise ExerciseCommandInvalid(
            f"sandbox wind preset is not allowed: {controls.wind_preset}"
        )
    resource_ids = {
        item.resource_id for item in self._definition.resources
    }
    unknown_resources = sorted(
        controls.unavailable_resource_ids - resource_ids
    )
    if unknown_resources:
        raise ExerciseCommandInvalid(
            f"unknown sandbox resource: {unknown_resources[0]}"
        )
    checkpoint_index = next(
        index
        for index, item in enumerate(self._definition.checkpoints)
        if item.checkpoint_key == controls.checkpoint_key
    )
    materialized = materialize_checkpoint(
        self._definition,
        checkpoint_index=checkpoint_index,
        objective=controls.objective,
        consequences=session.consequences,
    )
    task_ids = {item.task_id for item in materialized.tasks}
    unknown_tasks = sorted(
        set(controls.task_priority_presets) - task_ids
    )
    if unknown_tasks:
        raise ExerciseCommandInvalid(
            f"unknown sandbox task: {unknown_tasks[0]}"
        )
    resources = tuple(
        replace(
            item,
            available=(
                item.available
                and item.resource_id not in controls.unavailable_resource_ids
            ),
        )
        for item in materialized.resources
    )
    tasks = tuple(
        replace(
            item,
            uncovered_penalty=(
                item.uncovered_penalty
                * allowed.priority_multipliers[
                    controls.task_priority_presets.get(
                        item.task_id,
                        "standard",
                    )
                ]
            ),
        )
        for item in materialized.tasks
    )
    sandbox = replace(
        materialized,
        resources=resources,
        tasks=tasks,
        closed_edge_ids=tuple(sorted(set(controls.closed_edge_ids))),
        wind={
            "speedMps": wind.wind_speed_mps,
            "directionDegrees": wind.wind_direction_degrees,
        },
    )
    routes = candidate_routes(
        self._graph,
        sandbox.resources,
        sandbox.tasks,
        sandbox.asset_positions,
        sandbox.closed_edge_ids,
    )
    payload = serialize_planning_input(
        sandbox,
        routes,
        controls.locked_assignments,
    )
    try:
        solved = solve_task_plan(
            TaskOptimizationRequest(
                resources=sandbox.resources,
                tasks=sandbox.tasks,
                routes=routes,
                locked_assignments=controls.locked_assignments,
                travel_weight=self._definition.objectives[
                    controls.objective
                ].travel_weight,
                max_solver_seconds=2,
            )
        )
    except ValueError as error:
        raise ExerciseCommandInvalid(str(error)) from error
    output = serialize_task_result(solved, routes)
    output["explanation"] = serialize_task_explanation(
        explain_task_plan(None, {**payload, "assignments": output["assignments"]})
    )
    return {
        "sandbox": True,
        "sessionVersion": session.version,
        "inputHash": planning_input_hash(payload),
        "input": payload,
        "output": output,
    }
```

- [ ] **Step 5: Expose the bounded schema and route**

```python
# backend/src/wildfireops/api/schemas/exercises.py
class LockedAssignmentInput(ApiModel):
    resource_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class SandboxPlanRequest(SessionCommand):
    checkpoint_key: str = Field(min_length=1)
    objective: Literal[
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    ]
    closed_edge_ids: tuple[str, ...] = ()
    wind_preset: str = Field(min_length=1)
    unavailable_resource_ids: frozenset[str] = Field(
        default_factory=frozenset
    )
    task_priority_presets: dict[
        str,
        Literal["standard", "elevated", "urgent"],
    ] = Field(default_factory=dict)
    locked_assignments: tuple[LockedAssignmentInput, ...] = ()


class SandboxPlanResponse(ApiModel):
    sandbox: Literal[True]
    session_version: int
    input_hash: str
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
```

The route maps `LockedAssignmentInput` to `LockedTaskAssignment`, calls
`generate_sandbox_plan`, and validates the returned mapping with
`SandboxPlanResponse.model_validate`. It requires no `Idempotency-Key` because
it writes no state.

- [ ] **Step 6: Prove bounds and audit isolation**

Add one parameterized API test that submits each invalid field below and asserts
`422 exercise_command_invalid`, followed by an unchanged audit response:

```python
@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"checkpointKey": "unknown"}, "sandbox checkpoint is not allowed"),
        ({"closedEdgeIds": ["unknown"]}, "sandbox closure is not allowed"),
        ({"windPreset": "unknown"}, "sandbox wind preset is not allowed"),
        (
            {"unavailableResourceIds": ["unknown"]},
            "unknown sandbox resource",
        ),
        (
            {"taskPriorityPresets": {"unknown": "urgent"}},
            "unknown sandbox task",
        ),
    ],
)
async def test_sandbox_rejects_unbounded_controls_without_audit_change(
    completed_exercise_client: CompletedExerciseClient,
    patch: dict[str, object],
    message: str,
) -> None:
    before = await completed_exercise_client.audit()
    response = await completed_exercise_client.sandbox(patch)
    assert response.status_code == 422
    assert response.json()["code"] == "exercise_command_invalid"
    assert message in response.json()["message"]
    assert await completed_exercise_client.audit() == before
```

- [ ] **Step 7: Run and commit the sandbox**

```bash
cd backend
uv run pytest tests/unit/application/test_exercise_planning.py \
  tests/integration/api/test_exercises.py -q
uv run ruff check src/wildfireops/application/exercise_planning.py \
  src/wildfireops/api/schemas/exercises.py \
  src/wildfireops/api/routes/exercises.py
uv run mypy src/wildfireops/application/exercise_planning.py \
  src/wildfireops/api/schemas/exercises.py
cd ..
git add backend/src/wildfireops/application/exercise_planning.py \
  backend/src/wildfireops/api/schemas/exercises.py \
  backend/src/wildfireops/api/routes/exercises.py \
  backend/src/wildfireops/main.py \
  backend/tests/unit/application/test_exercise_planning.py \
  backend/tests/integration/api/test_exercises.py
git commit -m "feat(exercise): add bounded planning sandbox"
```

---

### Task 10: Prove local startup, the complete backend journey, and documentation

**Files:**
- Modify: `README.md`
- Modify: `backend/tests/integration/api/test_exercises.py`
- Modify: `backend/tests/integration/replay/test_park_fire_exercise_golden.py`

**Interfaces:**
- Consumes: the committed package, migrations, seed command, exercise router, and session APIs.
- Produces: one local startup command and one repeatable backend journey ready for the Claude Code frontend plan.

- [ ] **Step 1: Add a failing startup health assertion**

Extend `test_exercises.py` so the configured ASGI app expects:

```python
health = await client.get("/api/health")
assert health.json() == {"status": "ok", "service": "wildfireops-api"}

metadata = await client.get("/api/exercises/park-fire-decision")
assert metadata.status_code == 200
assert metadata.json()["checkpointCount"] == 3
```

- [ ] **Step 2: Confirm startup needs no new moving parts**

`compose.replay.yaml` continues to:

1. migrate the database;
2. seed historical replay state;
3. start the API with `WILDFIREOPS_REPLAY_PACKAGE=/data/replay/park-fire`.

No new process or compose/script change is required. The API loads
`exercise.json` from the existing read-only package mount at startup.

- [ ] **Step 3: Add one exact full backend journey**

The integration test performs:

```python
session = await create_session(client)
session = await select_objective(
    client,
    session,
    "protect-critical-services",
)
initial = await generate_plan(client, session)
session = await advance(client, initial)
disrupted = await generate_plan(client, session)
assert disrupted["explanation"]["changes"]
session = await advance(client, disrupted)
field_plan = await generate_plan(client, session)
override = await apply_override(
    client,
    session,
    resource_id="exercise-bus-1",
    task_id="shelter-capacity-transport",
)
completed = await approve(
    client,
    session,
    display_name="Portfolio Reviewer",
    note="Redirected transport after the shelter capacity field report.",
)
assert completed["status"] == "completed"
audit = await client.get(
    f"/api/exercise-sessions/{session['id']}/audit"
)
assert [item["eventType"] for item in audit.json()["items"]][-2:] == [
    "exercise.override-applied",
    "exercise.plan-approved",
]
debrief = await client.get(
    f"/api/exercise-sessions/{session['id']}/debrief"
)
assert debrief.json()["finalPlan"]["operatorOverride"]["taskId"] == (
    "shelter-capacity-transport"
)
```

- [ ] **Step 4: Document the local exercise boundary**

Add to `README.md`:

```markdown
## Park Fire Decision Exercise

Run `./scripts/replay-preview`, then verify the backend contract:

`curl --fail http://127.0.0.1:8000/api/exercises/park-fire-decision`

The exercise combines pinned historical fire, weather, road, community, and
public-facility inputs with clearly labeled simulated resources, operational
tasks, disruptions, field reports, recommendations, and decisions. It is a
portfolio exercise and must not be used for emergency or life-safety decisions.

The backend exercise contract is available at
`GET /api/exercises/park-fire-decision`. The current frontend remains the
separate, incident-scoped Live Monitor until the planned Claude Code rebuild
consumes the stable exercise responses.
```

- [ ] **Step 5: Run the proportional full verification**

Run:

```bash
docker compose -f compose.yaml -f compose.replay.yaml up -d --build db api
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/exercises/park-fire-decision

cd backend
uv run pytest tests/unit/replay/test_exercise.py \
  tests/unit/decision/test_task_optimizer.py \
  tests/unit/decision/test_task_optimizer_properties.py \
  tests/unit/decision/test_task_explanations.py \
  tests/unit/application/test_exercises.py \
  tests/unit/application/test_exercise_planning.py \
  tests/integration/persistence/test_exercises.py \
  tests/integration/api/test_exercises.py \
  tests/integration/replay/test_park_fire_exercise_golden.py -q
uv run ruff check src tests
uv run mypy src/wildfireops
```

Expected: health and metadata requests return `200`; all selected tests pass; Ruff and mypy report success.

- [ ] **Step 6: Verify existing Live Monitor regressions**

Run:

```bash
cd backend
uv run pytest tests/unit/decision/test_optimizer.py \
  tests/unit/decision/test_optimizer_properties.py \
  tests/integration/api/test_decision_flow.py \
  tests/integration/replay/test_park_fire_golden.py -q
```

Expected: all existing scenario, recommendation, decision, and Park Fire golden tests pass unchanged.

- [ ] **Step 7: Commit local completion**

```bash
git add README.md \
  backend/tests/integration/api/test_exercises.py \
  backend/tests/integration/replay/test_park_fire_exercise_golden.py
git commit -m "docs(exercise): prove local decision journey"
```

---

## Project 1 completion gate

Before writing the Claude Code frontend implementation plan, verify all of the following:

- `exercise.json` is manifest-hashed and validates at API startup.
- The historical and exercise provenance boundary is explicit in metadata and every task/resource record.
- Both incidents compete in one `solve_task_plan()` call.
- At least two objective presets produce different semantic assignments.
- Checkpoint two changes tasks, routes, and assignments.
- Road-crew assignment affects checkpoint-three corridor state.
- Every guided objective path supports the final shelter-bus override.
- Invalid override attempts are atomic.
- Sandbox controls reject unknown values, reuse `solve_task_plan()`, and leave
  the guided session, plan history, and audit unchanged.
- Session commands are isolated, expected-versioned, and idempotent.
- Plan runs are immutable and events append-only.
- Identical inputs reproduce identical semantic output and causal codes.
- Existing Live Monitor tests pass without contract changes.
- Local health, metadata, and complete backend exercise journey pass.
- Stable example JSON responses are available for the Claude Code frontend plan.
