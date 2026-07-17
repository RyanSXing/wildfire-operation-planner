# WildfireOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build and publicly demonstrate a replay-first geospatial wildfire decision-support application that turns sourced observations into explainable, scenario-specific, auditable resource recommendations.

**Architecture:** Use a modular Python monolith with separate FastAPI and ingestion-worker processes sharing domain, persistence, geospatial, and decision modules. PostgreSQL/PostGIS is the operational source of truth; a React/TypeScript client receives server-sent events and provides the incident, map, scenario, recommendation, and audit workflow. Implement the project as dependent vertical slices so every task leaves independently testable behavior.

**Tech Stack:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL/PostGIS, GeoAlchemy2, httpx, scikit-learn, pyproj, NetworkX, OSMnx, OR-Tools CP-SAT, structlog, pytest, Hypothesis, React, TypeScript, Vite, TanStack Query, MapLibre GL JS, Vitest, Testing Library, Playwright, Docker Compose, GitHub Actions, Render Blueprint.

## Global Constraints

- Display a persistent statement that WildfireOps is a portfolio simulation and must not be used for emergency or life-safety decisions.
- Limit the MVP to the 2024 Park Fire region in Northern California and a bounded road graph.
- Treat NASA FIRMS, NOAA/NWS, OpenStreetMap, and Census-derived records as real observations with source identity, observation time, ingestion time, version, validation, and freshness.
- Label all crews and response vehicles as simulated data.
- Keep observed reality immutable; scenario versions are immutable overlays.
- Reject approval when a recommendation's scenario or relevant source state has changed since computation.
- Never assign unavailable resources, exceed capacity, or route across a scenario-closed road.
- Keep the Python system a modular monolith. Do not add Kafka, Kubernetes, a service mesh, or independently deployed microservices.
- Do not add authentication, multiple organizations, mobile-native workflows, chatbots, scientific fire-spread prediction, or real emergency notifications.
- Make replay mode deterministic and usable without external network access after dependencies and container images are installed.
- Provide one documented local startup command, a public deployment, critical automated tests, measured benchmarks, and a three-minute demonstration path.
- Use measured values only in resume claims.
- Lock resolved dependency versions in uv.lock and package-lock.json when scaffolding.

---

## Planned file structure

### Repository root

- **Makefile** — single entry points for setup, local startup, migrations, replay loading, tests, linting, and benchmarks.
- **compose.yaml** — local PostGIS, API, worker, and frontend processes.
- **Dockerfile** — production multi-stage image that builds the frontend and packages the Python application.
- **render.yaml** — Render web service, worker, and PostGIS-capable database definition.
- **README.md** — problem, safety statement, architecture, setup, demo, tests, benchmarks, trade-offs, and screenshots.
- **.github/workflows/ci.yml** — backend, frontend, integration, and end-to-end checks.
- **data/replay/park-fire/** — versioned replay manifest, normalized observations, static data versions, and golden outputs.

### Backend

- **backend/pyproject.toml** and **backend/uv.lock** — Python package and locked dependencies.
- **backend/src/wildfireops/config.py** — environment configuration.
- **backend/src/wildfireops/main.py** — application factory, lifespan, routers, and production static-client mounting.
- **backend/src/wildfireops/db.py** — async engine and session lifecycle.
- **backend/src/wildfireops/domain/** — immutable domain types, enums, and invariants.
- **backend/src/wildfireops/persistence/** — SQLAlchemy models, repositories, transactions, and Alembic migrations.
- **backend/src/wildfireops/sources/** — FIRMS, NWS, and replay adapters.
- **backend/src/wildfireops/ingestion/** — polling, normalization, quarantine, idempotent writes, clustering, and replay orchestration.
- **backend/src/wildfireops/geospatial/** — exposure queries, road-graph construction, and route calculation.
- **backend/src/wildfireops/decision/** — risk scoring, scenario overlays, allocation, recommendation explanations, and commands.
- **backend/src/wildfireops/api/** — typed request/response schemas, read routers, command routers, SSE, and stable errors.
- **backend/tests/unit/** — pure domain, source, algorithm, and serializer tests.
- **backend/tests/integration/** — PostGIS, ingestion, transaction, API, and golden replay tests.
- **backend/tests/performance/** — repeatable query and optimizer benchmarks.

### Frontend

- **frontend/package.json** and **frontend/package-lock.json** — client package and locked dependencies.
- **frontend/src/app/** — providers, layout, routing, simulation disclaimer, and error boundary.
- **frontend/src/api/** — typed API client and TanStack Query hooks.
- **frontend/src/features/incidents/** — incident queue, details, source freshness, and timeline.
- **frontend/src/features/map/** — MapLibre canvas, layers, selected state, resources, routes, and closed roads.
- **frontend/src/features/scenarios/** — immutable override editor and baseline comparison.
- **frontend/src/features/decisions/** — recommendation explanation and approve/reject/edit flow.
- **frontend/src/features/audit/** — audit event list and detail view.
- **frontend/src/test/** — test server, fixtures, and MapLibre test shim.
- **frontend/e2e/** — Playwright replay workflow.

---

### Task 1: Repository foundation and health vertical slice

**Files:**
- Create: Makefile
- Create: compose.yaml
- Create: infra/postgres/init-test-db.sql
- Create: backend/pyproject.toml
- Create: backend/src/wildfireops/config.py
- Create: backend/src/wildfireops/db.py
- Create: backend/src/wildfireops/main.py
- Create: backend/tests/unit/test_health.py
- Create: frontend package generated by Vite
- Modify: frontend/src/App.tsx
- Create: frontend/src/App.test.tsx

**Interfaces:**
- Consumes: none
- Produces: Settings, create_app(settings: Settings | None = None) -> FastAPI, GET /api/health, make dev, make test

- [ ] **Step 1: Scaffold and lock the backend package**

Run:

~~~bash
mkdir -p backend/src/wildfireops backend/tests/unit
cd backend
uv init --lib --name wildfireops --python 3.12
uv add fastapi uvicorn sqlalchemy asyncpg geoalchemy2 alembic pydantic-settings httpx
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy
~~~

Expected: backend/uv.lock exists and pyproject.toml uses the src package layout.

- [ ] **Step 2: Write the failing health test**

Create backend/tests/unit/test_health.py:

~~~python
from fastapi.testclient import TestClient

from wildfireops.main import create_app


def test_health_reports_service_name() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wildfireops-api"}
~~~

- [ ] **Step 3: Run the health test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/test_health.py -v
~~~

Expected: FAIL because wildfireops.main does not exist.

- [ ] **Step 4: Implement configuration and the application factory**

Create backend/src/wildfireops/config.py:

~~~python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "wildfireops-api"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WILDFIREOPS_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
~~~

Create backend/src/wildfireops/main.py:

~~~python
from fastapi import FastAPI

from wildfireops.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="WildfireOps")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved.app_name}

    return app


app = create_app()
~~~

- [ ] **Step 5: Run the health test and confirm the green state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/test_health.py -v
~~~

Expected: 1 passed.

- [ ] **Step 6: Scaffold the client and write its failing shell test**

Run:

~~~bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install @tanstack/react-query maplibre-gl zod
npm install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
~~~

Create frontend/src/App.test.tsx:

~~~tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("identifies the product as a simulation", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "WildfireOps" })).toBeInTheDocument();
    expect(screen.getByText(/portfolio simulation/i)).toBeInTheDocument();
  });
});
~~~

Configure Vitest with a jsdom environment, import @testing-library/jest-dom in frontend/src/test/setup.ts, and add the package script "test": "vitest" before running the test.

- [ ] **Step 7: Run the client test and confirm the red state**

Run:

~~~bash
cd frontend
npm test -- --run src/App.test.tsx
~~~

Expected: FAIL because the default Vite page does not contain the simulation statement.

- [ ] **Step 8: Implement the minimal application shell**

Replace frontend/src/App.tsx:

~~~tsx
export default function App() {
  return (
    <main>
      <header>
        <h1>WildfireOps</h1>
        <p role="note">
          Portfolio simulation only. Do not use for emergency or life-safety decisions.
        </p>
      </header>
    </main>
  );
}
~~~

- [ ] **Step 9: Add local orchestration and verify both test suites**

Create compose.yaml with a postgis/postgis database, API, and Vite frontend. Mount infra/postgres/init-test-db.sql into /docker-entrypoint-initdb.d so the initial database startup creates both wildfireops and wildfireops_test. Create Makefile targets dev, down, test-backend, test-frontend, and test. The dev target must run docker compose up --build and expose frontend port 5173 and API port 8000. Add the worker service only after its entry point exists in Task 6.

Run:

~~~bash
docker compose config
make test
~~~

Expected: Compose configuration is valid; backend and frontend tests pass.

- [ ] **Step 10: Commit the foundation**

~~~bash
git add Makefile compose.yaml infra/postgres/init-test-db.sql backend frontend
git commit -m "chore: scaffold WildfireOps application"
~~~

---

### Task 2: Immutable domain types and invariants

> **Resolved contract:** Observation timestamps must have a UTC offset of exactly zero,
> and observation payloads must be defensively copied into recursively immutable JSON
> values. These stronger invariants supersede the original sample wherever it differed.

**Files:**
- Create: backend/src/wildfireops/domain/enums.py
- Create: backend/src/wildfireops/domain/observations.py
- Create: backend/src/wildfireops/domain/operations.py
- Create: backend/src/wildfireops/domain/scenarios.py
- Create: backend/tests/unit/domain/test_types.py

**Interfaces:**
- Consumes: Settings from Task 1
- Produces: NormalizedObservation, WeatherObservation, SourceObservation, ResourceUnit, DemandPoint, ScenarioVersion, RoadClosure, WeatherOverride, ResourceOverride, domain validation exceptions

- [ ] **Step 1: Write failing tests for observation identity and immutable scenarios**

Create backend/tests/unit/domain/test_types.py:

~~~python
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from wildfireops.domain.observations import NormalizedObservation
from wildfireops.domain.scenarios import RoadClosure, ScenarioVersion


def test_observation_identity_is_source_scoped() -> None:
    record = NormalizedObservation(
        source_name="nasa_firms",
        source_record_id="viirs-42",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
        confidence=0.9,
        intensity=18.4,
        raw_payload={"satellite": "NOAA-20"},
    )
    assert record.identity == "nasa_firms:viirs-42"


def test_scenario_version_is_immutable() -> None:
    scenario = ScenarioVersion(
        scenario_id="scenario-1",
        version=1,
        incident_snapshot_id="incident-snapshot-1",
        road_closures=(RoadClosure(edge_id="edge-9"),),
        weather_overrides=(),
        resource_overrides=(),
    )

    with pytest.raises(FrozenInstanceError):
        scenario.version = 2
~~~

Also add shared, parameterized coverage for both observation types that rejects missing
and nonzero UTC offsets, accepts zero-offset aware timestamps, rejects mutation of the
top-level payload and nested mappings/sequences, proves caller-owned input mutation is
isolated after construction, and rejects unsupported non-JSON values.

- [ ] **Step 2: Run the tests and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/domain/test_types.py -v
~~~

Expected: FAIL because the domain modules do not exist.

- [ ] **Step 3: Implement observation and operation value objects**

Create immutable dataclasses with slots. Both observation types must require
`observed_at.utcoffset() == timedelta(0)`; timestamps with a missing or nonzero offset
are invalid. NormalizedObservation must also validate longitude in [-180, 180], latitude
in [-90, 90], confidence in [0, 1], and a non-empty source identity. Observation payloads
use the public `FrozenJsonValue` and `FrozenJsonObject` types. Construction defensively
copies and recursively freezes mappings as read-only mappings and sequences as tuples;
unsupported non-JSON content is rejected.

Use this public shape in backend/src/wildfireops/domain/observations.py:

~~~python
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from types import MappingProxyType


type FrozenJsonScalar = None | bool | int | float | str
type FrozenJsonValue = (
    FrozenJsonScalar | Mapping[str, FrozenJsonValue] | tuple[FrozenJsonValue, ...]
)
type FrozenJsonObject = Mapping[str, FrozenJsonValue]


def freeze_json_value(value: object) -> FrozenJsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(
                "raw_payload contains unsupported JSON value: non-finite float"
            )
        return value
    if isinstance(value, Mapping):
        return freeze_json_object(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(freeze_json_value(item) for item in value)
    raise ValueError(
        f"raw_payload contains unsupported JSON value: {type(value).__name__}"
    )


def freeze_json_object(payload: Mapping[str, object]) -> FrozenJsonObject:
    frozen: dict[str, FrozenJsonValue] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ValueError("raw_payload mapping keys must be strings")
        frozen[key] = freeze_json_value(value)
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    source_name: str
    source_record_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    confidence: float
    intensity: float | None
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be UTC")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence is outside valid range")
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))

    @property
    def identity(self) -> str:
        return f"{self.source_name}:{self.source_record_id}"
~~~

Define ResourceUnit and DemandPoint in operations.py:

~~~python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceUnit:
    resource_id: str
    capabilities: frozenset[str]
    capacity: int
    available: bool
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("resource capacity must be positive")
        if not self.capabilities:
            raise ValueError("resource capabilities are required")


@dataclass(frozen=True, slots=True)
class DemandPoint:
    destination_id: str
    required_capability: str
    required_capacity: int
    weighted_risk: float
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if self.required_capacity <= 0:
            raise ValueError("required capacity must be positive")
        if self.weighted_risk < 0:
            raise ValueError("weighted risk cannot be negative")
~~~

Add WeatherObservation and the union used by ingestion and persistence:

~~~python
@dataclass(frozen=True, slots=True)
class WeatherObservation:
    source_name: str
    source_record_id: str
    observed_at: datetime
    longitude: float
    latitude: float
    wind_speed_mps: float
    wind_direction_degrees: float
    temperature_celsius: float | None
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        if not self.source_name or not self.source_record_id:
            raise ValueError("source identity is required")
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be UTC")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude is outside valid range")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude is outside valid range")
        if self.wind_speed_mps < 0:
            raise ValueError("wind speed cannot be negative")
        if not 0 <= self.wind_direction_degrees < 360:
            raise ValueError("wind direction is outside valid range")
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))

    @property
    def identity(self) -> str:
        return f"{self.source_name}:{self.source_record_id}"


SourceObservation = NormalizedObservation | WeatherObservation
~~~

- [ ] **Step 4: Implement scenario overlays**

Create RoadClosure(edge_id: str), WeatherOverride(wind_speed_mps: float, wind_direction_degrees: float), ResourceOverride(resource_id: str, available: bool), and ScenarioVersion using frozen dataclasses and tuple fields. Validate version >= 1, wind speed >= 0, and direction in [0, 360).

- [ ] **Step 5: Run domain tests and static checks**

Run:

~~~bash
cd backend
uv run pytest tests/unit/domain -v
uv run ruff check src/wildfireops/domain tests/unit/domain
uv run mypy src/wildfireops/domain
~~~

Expected: all commands exit 0.

- [ ] **Step 6: Commit domain types**

~~~bash
git add backend/src/wildfireops/domain backend/tests/unit/domain
git commit -m "feat: define immutable operational domain"
~~~

---

### Task 3: PostGIS schema and idempotent observation repository

**Files:**
- Create: backend/alembic.ini
- Create: backend/migrations/env.py
- Create: backend/migrations/versions/0001_operational_schema.py
- Create: backend/src/wildfireops/persistence/base.py
- Create: backend/src/wildfireops/persistence/observed_models.py
- Create: backend/src/wildfireops/persistence/decision_models.py
- Create: backend/src/wildfireops/persistence/observations.py
- Create: backend/tests/integration/conftest.py
- Create: backend/tests/integration/persistence/test_observations.py

**Interfaces:**
- Consumes: SourceObservation from Task 2, Settings from Task 1
- Produces: Base, async_session_factory, ObservationRepository.upsert_many(session, observations) -> IngestStats, complete initial database schema

- [ ] **Step 1: Add database dependencies and create the failing idempotency test**

Run:

~~~bash
cd backend
uv add geoalchemy2 alembic asyncpg
~~~

Create backend/tests/integration/persistence/test_observations.py with two identical NormalizedObservation values. Call upsert_many twice and assert the first IngestStats is inserted=1, deduplicated=1, while the second is inserted=0, deduplicated=2. Query source_observations and assert the table contains one row.

- [ ] **Step 2: Run the repository test and confirm the red state**

Run:

~~~bash
docker compose up -d db
cd backend
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops_test uv run pytest tests/integration/persistence/test_observations.py -v
~~~

Expected: FAIL because persistence modules and tables do not exist.

- [ ] **Step 3: Define SQLAlchemy base and observed-reality models**

Implement UUID primary keys, timezone-aware timestamps, JSONB raw metadata, and GeoAlchemy2 Geometry columns with SRID 4326. The source_observations table must include observation_kind, nullable fire-specific fields, nullable weather-specific fields, and enforce a unique constraint on (source_name, source_record_id). Add GiST indexes to observation, incident, asset, and resource geometries.

The initial migration must enable PostGIS and create:

- source_observations
- quarantined_observations
- wildfire_incidents
- incident_detections
- exposed_assets
- resource_units
- source_status

- [ ] **Step 4: Define scenario and decision models**

Add these tables in the same initial migration:

- incident_snapshots
- scenarios
- scenario_versions
- scenario_road_closures
- scenario_weather_overrides
- scenario_resource_overrides
- recommendations
- recommendation_assignments
- decision_actions
- audit_events
- idempotency_keys

Use foreign keys and unique constraints to enforce one version number per scenario and one decision action per idempotency key. Store recommendation input_version, algorithm_version, solver_status, objective_components JSONB, and explanation JSONB.

- [ ] **Step 5: Implement idempotent PostgreSQL upsert**

In backend/src/wildfireops/persistence/observations.py expose:

~~~python
from dataclasses import dataclass
from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import SourceObservation
from wildfireops.persistence.observed_models import SourceObservationModel


@dataclass(frozen=True, slots=True)
class IngestStats:
    inserted: int
    deduplicated: int


class ObservationRepository:
    async def upsert_many(
        self,
        session: AsyncSession,
        observations: Sequence[SourceObservation],
    ) -> IngestStats:
        identities = {(item.source_name, item.source_record_id) for item in observations}
        inserted = 0
        for source_name, source_record_id in sorted(identities):
            record = next(
                value
                for value in observations
                if value.source_name == source_name
                and value.source_record_id == source_record_id
            )
            statement = (
                insert(SourceObservationModel)
                .values(SourceObservationModel.from_domain(record))
                .on_conflict_do_nothing(
                    index_elements=["source_name", "source_record_id"]
                )
                .returning(SourceObservationModel.id)
            )
            inserted += int((await session.execute(statement)).scalar_one_or_none() is not None)
        return IngestStats(
            inserted=inserted,
            deduplicated=len(observations) - inserted,
        )
~~~

Keep transaction ownership with the caller; the repository must not commit.

SourceObservationModel.from_domain must return a SQLAlchemy values mapping with source_name, source_record_id, observation_kind, observed_at, geometry as SRID=4326 point WKT, normalized fire or weather fields, and raw_payload. At this persistence boundary it materializes the domain `FrozenJsonObject` into ordinary JSON dict/list containers for JSONB serialization. It must use isinstance to distinguish NormalizedObservation from WeatherObservation; no caller may infer the kind from nullable values.

- [ ] **Step 6: Run migrations and integration tests**

Run:

~~~bash
cd backend
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops_test uv run alembic upgrade head
WILDFIREOPS_DATABASE_URL=postgresql+asyncpg://wildfireops:wildfireops@localhost:5432/wildfireops_test uv run pytest tests/integration/persistence/test_observations.py -v
~~~

Expected: migration succeeds and the test passes.

- [ ] **Step 7: Inspect indexes and constraints**

Run:

~~~bash
docker compose exec db psql -U wildfireops -d wildfireops_test -c "\d+ source_observations"
docker compose exec db psql -U wildfireops -d wildfireops_test -c "\d+ scenario_versions"
~~~

Expected: source identity is unique, geometry has a GiST index, and scenario version has a unique parent/version constraint.

- [ ] **Step 8: Commit the operational schema**

~~~bash
git add backend/alembic.ini backend/migrations backend/src/wildfireops/persistence backend/tests/integration
git commit -m "feat: add PostGIS operational schema"
~~~

---

### Task 4: FIRMS and National Weather Service source adapters

**Files:**
- Create: backend/src/wildfireops/sources/base.py
- Create: backend/src/wildfireops/sources/firms.py
- Create: backend/src/wildfireops/sources/nws.py
- Create: backend/src/wildfireops/sources/http.py
- Modify: backend/src/wildfireops/config.py
- Create: backend/tests/fixtures/firms_sample.csv
- Create: backend/tests/fixtures/nws_observation.json
- Create: backend/tests/unit/sources/test_firms.py
- Create: backend/tests/unit/sources/test_nws.py
- Create: backend/tests/unit/sources/test_http.py

**Interfaces:**
- Consumes: SourceObservation from Task 2
- Produces: SourceValidationFailure, SourceBatch, SourceAdapter protocol, FirmsAdapter.fetch() -> SourceBatch, NwsAdapter.fetch() -> SourceBatch, fetch_with_retry(client, request, policy)

- [ ] **Step 1: Write a representative FIRMS fixture and failing parser test**

Create backend/tests/fixtures/firms_sample.csv:

~~~csv
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
39.805,-121.612,341.6,h,2024-07-24,1812,N20,VIIRS
39.807,-121.609,335.2,n,2024-07-24,1818,N20,VIIRS
~~~

The test must assert two normalized observations, UTC observation times 18:12 and 18:18, confidence mappings h=0.95 and n=0.75, and stable source_record_id values derived from source fields.

- [ ] **Step 2: Run the source test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/sources/test_firms.py -v
~~~

Expected: FAIL because FirmsAdapter does not exist.

- [ ] **Step 3: Implement the common adapter contract and FIRMS parser**

Define:

~~~python
from dataclasses import dataclass
from typing import Protocol

from wildfireops.domain.observations import (
    FrozenJsonObject,
    SourceObservation,
    freeze_json_object,
)


@dataclass(frozen=True, slots=True)
class SourceValidationFailure:
    source_name: str
    reason: str
    raw_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_payload", freeze_json_object(self.raw_payload))


@dataclass(frozen=True, slots=True)
class SourceBatch:
    observations: tuple[SourceObservation, ...]
    failures: tuple[SourceValidationFailure, ...]


class SourceAdapter(Protocol):
    @property
    def source_name(self) -> str:
        raise NotImplementedError

    async def fetch(self) -> SourceBatch:
        raise NotImplementedError
~~~

FirmsAdapter must parse CSV through csv.DictReader, normalize acquisition time to UTC, map confidence values explicitly, and hash satellite, instrument, acquisition time, rounded latitude, and rounded longitude into a deterministic source_record_id. A malformed row becomes SourceValidationFailure and does not prevent valid rows from being returned in the same SourceBatch.

- [ ] **Step 4: Write and implement the NWS normalization test**

Create a minimal GeoJSON Feature fixture containing properties.timestamp, properties.windSpeed, properties.windDirection, properties.temperature, and point geometry. Assert conversion into a WeatherObservation whose raw payload retains the original NWS properties and whose SourceBatch has no failures.

- [ ] **Step 5: Test and implement bounded retry**

Write a test using httpx.MockTransport that returns 503 twice and 200 once. Assert three requests, no retry for 400, and a SourceUnavailable error after the configured maximum.

Implement RetryPolicy(max_attempts: int = 3, base_delay_seconds: float = 0.25, timeout_seconds: float = 10.0). Inject the sleep callable so the unit test does not wait.

Add firms_map_key and nws_user_agent to Settings so their environment names are WILDFIREOPS_FIRMS_MAP_KEY and WILDFIREOPS_NWS_USER_AGENT. Treat the map key as a Pydantic SecretStr and never include it in errors or structured logs.

- [ ] **Step 6: Run source tests**

Run:

~~~bash
cd backend
uv run pytest tests/unit/sources -v
uv run ruff check src/wildfireops/sources tests/unit/sources
~~~

Expected: all source and retry tests pass.

- [ ] **Step 7: Commit source adapters**

~~~bash
git add backend/src/wildfireops/sources backend/tests/fixtures backend/tests/unit/sources backend/pyproject.toml backend/uv.lock
git commit -m "feat: normalize wildfire and weather sources"
~~~

---

### Task 5: Deterministic replay packages

**Files:**
- Create: backend/src/wildfireops/replay/manifest.py
- Create: backend/src/wildfireops/replay/clock.py
- Create: backend/src/wildfireops/replay/loader.py
- Create: backend/src/wildfireops/replay/build.py
- Create: backend/tests/fixtures/replay-small/manifest.json
- Create: backend/tests/fixtures/replay-small/fire_detections.jsonl
- Create: backend/tests/unit/replay/test_loader.py

**Interfaces:**
- Consumes: source-normalized domain values from Task 4
- Produces: ReplayManifest, ReplayClock, ReplayLoader.iter_until(at: datetime), python -m wildfireops.replay.build command

- [ ] **Step 1: Write the failing deterministic replay test**

Create a two-record JSONL fixture at timestamps 18:12 and 18:18 and a manifest containing package_id, region, start_at, end_at, schema_version, algorithm_config_version, and SHA-256 file hashes.

Test:

~~~python
from datetime import UTC, datetime
from pathlib import Path

from wildfireops.replay.loader import ReplayLoader


def test_replay_returns_identical_order_for_same_clock_time() -> None:
    package = Path("tests/fixtures/replay-small")
    cutoff = datetime(2024, 7, 24, 18, 15, tzinfo=UTC)

    first = list(ReplayLoader(package).iter_until(cutoff))
    second = list(ReplayLoader(package).iter_until(cutoff))

    assert [item.identity for item in first] == [item.identity for item in second]
    assert len(first) == 1
~~~

- [ ] **Step 2: Run the replay test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/replay/test_loader.py -v
~~~

Expected: FAIL because replay modules do not exist.

- [ ] **Step 3: Implement manifest validation and hash checks**

ReplayManifest must reject unknown schema versions, non-UTC timestamps, end_at before start_at, missing files, and mismatched hashes. Loader initialization validates the entire manifest before yielding data.

- [ ] **Step 4: Implement the replay clock and ordered loader**

ReplayClock exposes current_time, advance(delta), and reset(). ReplayLoader sorts by observed_at and then identity to guarantee stable ordering. iter_until returns new immutable domain values without mutating the package or clock.

- [ ] **Step 5: Implement the package builder command**

The command accepts:

~~~bash
uv run python -m wildfireops.replay.build \
  --package-id park-fire-2024-v1 \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --start 2024-07-24T00:00:00Z \
  --end 2024-08-02T00:00:00Z \
  --output ../data/replay/park-fire
~~~

It writes normalized JSONL files, static-data version metadata, source citations, and hashes. It must fail before writing the manifest if required files are empty or validation fails.

- [ ] **Step 6: Run replay tests and corruption check**

Add a test that changes one byte in a temporary copy and asserts ReplayPackageCorrupt with the affected filename.

Run:

~~~bash
cd backend
uv run pytest tests/unit/replay -v
~~~

Expected: deterministic and corruption tests pass.

- [ ] **Step 7: Commit replay infrastructure**

~~~bash
git add backend/src/wildfireops/replay backend/tests/fixtures/replay-small backend/tests/unit/replay
git commit -m "feat: add deterministic replay packages"
~~~

---

### Task 6: Ingestion orchestration and deterministic incident clustering

**Files:**
- Create: backend/src/wildfireops/ingestion/service.py
- Create: backend/src/wildfireops/ingestion/worker.py
- Create: backend/src/wildfireops/ingestion/quarantine.py
- Create: backend/src/wildfireops/observability.py
- Create: backend/src/wildfireops/geospatial/clustering.py
- Create: backend/src/wildfireops/persistence/incidents.py
- Modify: compose.yaml
- Create: backend/tests/unit/geospatial/test_clustering.py
- Create: backend/tests/integration/ingestion/test_service.py

**Interfaces:**
- Consumes: SourceAdapter and SourceBatch from Task 4, ObservationRepository from Task 3, ReplayLoader from Task 5
- Produces: ClusteringConfig, DetectionCluster, cluster_detections(records, config), IngestionService.run_source(adapter) -> IngestionRun, refresh_incidents(session, clusters)

- [ ] **Step 1: Add clustering dependencies and write the failing determinism test**

Run:

~~~bash
cd backend
uv add numpy scikit-learn pyproj
~~~

Write a test with two close detection pairs and one noise point. Call cluster_detections once in input order and once in reverse order. Assert identical sorted member-identity tuples, two clusters, and the same centroid coordinates.

- [ ] **Step 2: Run the clustering test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/geospatial/test_clustering.py -v
~~~

Expected: FAIL because clustering.py does not exist.

- [ ] **Step 3: Implement projected spatiotemporal clustering**

Expose:

~~~python
from dataclasses import dataclass
from collections.abc import Sequence

from wildfireops.domain.observations import NormalizedObservation


@dataclass(frozen=True, slots=True)
class ClusteringConfig:
    spatial_radius_meters: float
    temporal_window_seconds: float
    minimum_points: int
    algorithm_version: str


@dataclass(frozen=True, slots=True)
class DetectionCluster:
    member_identities: tuple[str, ...]
    centroid_longitude: float
    centroid_latitude: float


def cluster_detections(
    records: Sequence[NormalizedObservation],
    config: ClusteringConfig,
) -> tuple[DetectionCluster, ...]:
    if not records:
        return ()
    ordered = sorted(records, key=lambda item: (item.observed_at, item.identity))
    projected = project_to_epsg_3310(ordered)
    features = build_normalized_space_time_features(projected, ordered, config)
    labels = DBSCAN(eps=1.0, min_samples=config.minimum_points).fit_predict(features)
    clusters = build_clusters(ordered, labels)
    return tuple(sorted(clusters, key=lambda item: item.member_identities))
~~~

Implement project_to_epsg_3310, build_normalized_space_time_features, and build_clusters in the same focused module. Convert cluster centroids back to EPSG:4326 and exclude label -1 as noise.

- [ ] **Step 4: Write the failing ingestion transaction test**

Use a fake adapter that returns a SourceBatch with one valid record repeated twice and one SourceValidationFailure. Assert:

- one observation is inserted
- one is counted as deduplicated
- one quarantine row is written with a validation reason
- source_status records the successful run and accepted/quarantined counts
- all writes roll back when incident refresh raises

- [ ] **Step 5: Implement ingestion orchestration**

IngestionService must:

1. fetch a SourceBatch through the adapter
2. separate fire and weather observations by their explicit domain type
3. upsert valid observations
4. write SourceValidationFailure values to quarantine
5. compute current clusters
6. match clusters to existing incident identities
7. refresh incident membership and source status
8. commit once

Incident matching uses maximum member overlap first, then centroid distance within the configured spatial radius. Ties resolve by existing incident UUID string order so repeated input remains deterministic.

- [ ] **Step 6: Implement the worker entry point**

backend/src/wildfireops/ingestion/worker.py must create adapters from Settings, run each source on its configured interval, log one structured event per run, and support:

~~~bash
uv run python -m wildfireops.ingestion.worker --once
uv run python -m wildfireops.ingestion.worker --replay data/replay/park-fire
~~~

Configure structlog in wildfireops/observability.py with UTC timestamps and JSON output in production. Worker events include job_id, source_name, accepted, deduplicated, quarantined, duration_ms, and outcome without raw payloads or secrets.

The --once command exits nonzero only when every configured source fails; partial source failure updates source_status and continues. Add the worker service to compose.yaml now that this entry point exists.

- [ ] **Step 7: Run clustering and ingestion tests**

Run:

~~~bash
cd backend
uv add structlog
uv run pytest tests/unit/geospatial/test_clustering.py tests/integration/ingestion/test_service.py -v
~~~

Expected: determinism, idempotency, quarantine, and rollback tests pass.

- [ ] **Step 8: Commit ingestion and clustering**

~~~bash
git add backend/src/wildfireops/ingestion backend/src/wildfireops/geospatial/clustering.py backend/src/wildfireops/persistence/incidents.py backend/tests/unit/geospatial backend/tests/integration/ingestion backend/pyproject.toml backend/uv.lock
git commit -m "feat: ingest and cluster wildfire detections"
~~~

---

### Task 7: Exposure analysis and explainable risk scoring

**Files:**
- Create: backend/src/wildfireops/geospatial/exposure.py
- Create: backend/src/wildfireops/persistence/exposures.py
- Create: backend/src/wildfireops/decision/risk.py
- Create: backend/tests/unit/decision/test_risk.py
- Create: backend/tests/integration/geospatial/test_exposure.py

**Interfaces:**
- Consumes: incident geometry and exposed assets from Task 3, DetectionCluster from Task 6
- Produces: ExposureRepository.find_for_incident(session, incident_id, buffer_meters), RiskFactors, RiskBreakdown, score_risk(factors, config)

- [ ] **Step 1: Write the failing risk explanation test**

Create backend/tests/unit/decision/test_risk.py:

~~~python
from wildfireops.decision.risk import RiskFactors, default_risk_config, score_risk


def test_risk_breakdown_sums_to_total() -> None:
    factors = RiskFactors(
        proximity=0.8,
        population=0.6,
        critical_facilities=0.5,
        wind_alignment=0.75,
        detection_confidence=0.9,
        source_freshness=1.0,
    )

    result = score_risk(factors, default_risk_config())

    assert result.score == 69.75
    assert round(sum(item.contribution for item in result.contributions), 6) == result.score
    assert [item.name for item in result.contributions] == [
        "proximity",
        "population",
        "critical_facilities",
        "wind_alignment",
        "detection_confidence",
        "source_freshness",
    ]
~~~

The default weights are 0.30, 0.25, 0.20, 0.15, 0.05, and 0.05 in that order.

- [ ] **Step 2: Run the risk test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/decision/test_risk.py -v
~~~

Expected: FAIL because risk.py does not exist.

- [ ] **Step 3: Implement versioned risk scoring**

Implement frozen RiskFactors, RiskConfig, RiskContribution, and RiskBreakdown values. score_risk must reject factor values outside [0, 1], reject weights that do not sum to 1 within 1e-9, multiply weighted contributions by 100, and round only the serialized output rather than intermediate calculations. Set algorithm_version to risk-v1.

- [ ] **Step 4: Write the failing PostGIS exposure test**

Seed an incident polygon, one community inside 10 km, one hospital inside 10 km, and one shelter outside 10 km. Assert find_for_incident returns the community and hospital with distance_meters and excludes the shelter.

- [ ] **Step 5: Implement bounded exposure queries**

Use ST_DWithin on geography casts for meter-based distance and ST_Distance for the returned measurement. Require buffer_meters between 100 and 100000. Order results by distance and stable asset ID. Create the necessary GiST index in a new Alembic migration if Task 3 did not cover it.

- [ ] **Step 6: Connect exposure refresh to ingestion**

After incident membership refresh, recompute exposed assets and persist the exact buffer, incident snapshot ID, source data versions, normalized risk factors, risk configuration version, and resulting breakdown.

- [ ] **Step 7: Run unit and PostGIS tests**

Run:

~~~bash
cd backend
uv run pytest tests/unit/decision/test_risk.py tests/integration/geospatial/test_exposure.py -v
~~~

Expected: risk total and spatial boundary tests pass.

- [ ] **Step 8: Commit exposure and risk**

~~~bash
git add backend/src/wildfireops/geospatial/exposure.py backend/src/wildfireops/persistence/exposures.py backend/src/wildfireops/decision/risk.py backend/tests/unit/decision backend/tests/integration/geospatial backend/migrations
git commit -m "feat: rank wildfire exposure with explainable risk"
~~~

---

### Task 8: Incident, timeline, freshness, and event APIs

**Files:**
- Create: backend/src/wildfireops/api/dependencies.py
- Create: backend/src/wildfireops/api/errors.py
- Create: backend/src/wildfireops/api/schemas/incidents.py
- Create: backend/src/wildfireops/api/schemas/sources.py
- Create: backend/src/wildfireops/api/routes/incidents.py
- Create: backend/src/wildfireops/api/routes/sources.py
- Create: backend/src/wildfireops/api/routes/events.py
- Create: backend/src/wildfireops/api/event_bus.py
- Create: backend/src/wildfireops/api/request_metrics.py
- Modify: backend/src/wildfireops/main.py
- Create: backend/tests/integration/api/test_incidents.py
- Create: backend/tests/unit/api/test_event_bus.py

**Interfaces:**
- Consumes: persisted incidents, exposure, risk, and source status from Tasks 3, 6, and 7
- Produces: GET /api/incidents, GET /api/incidents/{incident_id}, GET /api/incidents/{incident_id}/timeline, GET /api/sources/status, GET /api/events

- [ ] **Step 1: Write the failing incident-list contract test**

Seed two incidents with different risk and freshness. Assert GET /api/incidents returns risk-descending items with:

~~~json
{
  "items": [
    {
      "id": "incident-high",
      "name": "Redwood Creek",
      "risk": {
        "score": 82.0,
        "algorithmVersion": "risk-v1",
        "contributions": []
      },
      "exposedAssetCount": 3,
      "lastObservedAt": "2024-07-24T18:18:00Z",
      "freshness": "fresh"
    }
  ]
}
~~~

Use actual seeded contribution rows in the test response rather than accepting an empty production breakdown.

- [ ] **Step 2: Run the API test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/integration/api/test_incidents.py -v
~~~

Expected: FAIL with 404 because the router is not registered.

- [ ] **Step 3: Implement typed read schemas and query service**

Pydantic response models use camelCase aliases and UTC ISO timestamps. Routes call an IncidentQueryService interface rather than SQLAlchemy models directly. The detail response includes geometry as GeoJSON, detections, exposed assets, simulated resources, freshness, and complete risk explanation.

- [ ] **Step 4: Implement stable API errors**

Create ApiError(code, message, details) and exception handlers producing:

~~~json
{
  "error": {
    "code": "incident_not_found",
    "message": "Incident was not found",
    "details": {"incidentId": "incident-missing"}
  }
}
~~~

Return 404 for missing reads, 409 for state conflicts, and field-level 422 for invalid commands.

- [ ] **Step 5: Add structured request metrics**

Add middleware that creates or propagates X-Request-ID and logs request_id, method, route template, status_code, and duration_ms through the structlog configuration from Task 6. Test that a 200 response and an ApiError response each emit one event and never include request bodies, API keys, or database URLs.

- [ ] **Step 6: Implement source status and timeline routes**

Source status returns source name, last attempt, last success, next retry, freshness state, accepted count, deduplicated count, quarantined count, and last error code. Timeline returns stable ordered observation frames for replay.

- [ ] **Step 7: Implement an in-process SSE event bus**

EventBus.subscribe creates a bounded asyncio.Queue per subscriber. EventBus.publish drops and replaces the oldest queued incident-refresh event for slow subscribers rather than blocking ingestion. GET /api/events emits named incident-updated and source-status-updated events plus a 20-second heartbeat.

- [ ] **Step 8: Run API and event tests**

Run:

~~~bash
cd backend
uv run pytest tests/integration/api/test_incidents.py tests/unit/api/test_event_bus.py -v
~~~

Expected: read contracts, missing incident error, request metrics, event ordering, and slow-subscriber behavior pass.

- [ ] **Step 9: Commit read APIs**

~~~bash
git add backend/src/wildfireops/api backend/src/wildfireops/main.py backend/tests/integration/api backend/tests/unit/api
git commit -m "feat: expose incident and freshness APIs"
~~~

---

### Task 9: Immutable scenarios and road-closure routing

**Files:**
- Create: backend/src/wildfireops/geospatial/road_graph.py
- Create: backend/src/wildfireops/decision/scenarios.py
- Create: backend/src/wildfireops/persistence/scenarios.py
- Create: backend/tests/unit/geospatial/test_road_graph.py
- Create: backend/tests/integration/decision/test_scenarios.py

**Interfaces:**
- Consumes: ScenarioVersion from Task 2 and scenario tables from Task 3
- Produces: RoadGraph.load(path), compute_route(graph, origin, destination, closed_edge_ids), ScenarioService.create(), ScenarioService.add_version()

- [ ] **Step 1: Write the failing closed-road routing test**

Build a directed NetworkX graph in the test with edges:

- A to B, edge AB, 5 minutes
- B to C, edge BC, 5 minutes
- A to C, edge AC, 15 minutes

Assert baseline A to C uses AB and BC in 10 minutes. Assert closing BC uses AC in 15 minutes. Assert closing BC and AC returns RouteStatus.UNREACHABLE.

- [ ] **Step 2: Run the routing test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py -v
~~~

Expected: FAIL because road_graph.py does not exist.

- [ ] **Step 3: Implement versioned graph loading and route calculation**

RoadGraph.load reads GraphML once, validates unique edge IDs and nonnegative travel_minutes, and records graph_version from a SHA-256 digest. compute_route works on a view with closed edge IDs filtered out and returns:

~~~python
from dataclasses import dataclass
from enum import StrEnum


class RouteStatus(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class RouteResult:
    status: RouteStatus
    edge_ids: tuple[str, ...]
    distance_meters: float
    travel_minutes: float
    graph_version: str
    closure_hash: str
~~~

Cache keys contain graph_version, closure_hash, origin node, and destination node.

- [ ] **Step 4: Write the failing scenario-version integration test**

Create a scenario from incident snapshot S1, then add a version with one RoadClosure, one WeatherOverride, and one ResourceOverride. Assert:

- version 1 remains unchanged
- version 2 contains all three overrides
- a second request with the same idempotency key returns version 2
- the same key with a different body returns 409 idempotency_conflict

- [ ] **Step 5: Implement scenario persistence and validation**

ScenarioService.create pins the current incident snapshot. add_version copies the previous version's overlays, applies the requested replacement set, validates road IDs against graph_version and resource IDs against the snapshot, and writes a new immutable row. It never updates prior version rows.

- [ ] **Step 6: Add the Park Fire graph build command**

Expose:

~~~bash
uv run python -m wildfireops.geospatial.road_graph build \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --output ../data/replay/park-fire/roads.graphml.gz
~~~

The command records the OSM retrieval timestamp, bounding box, network type, OSMnx version, graph digest, and edge count in the replay manifest.

- [ ] **Step 7: Run routing and scenario tests**

Run:

~~~bash
cd backend
uv run pytest tests/unit/geospatial/test_road_graph.py tests/integration/decision/test_scenarios.py -v
~~~

Expected: baseline, closure fallback, unreachable, immutability, and idempotency tests pass.

- [ ] **Step 8: Commit scenarios and routing**

~~~bash
git add backend/src/wildfireops/geospatial/road_graph.py backend/src/wildfireops/decision/scenarios.py backend/src/wildfireops/persistence/scenarios.py backend/tests/unit/geospatial/test_road_graph.py backend/tests/integration/decision/test_scenarios.py data/replay
git commit -m "feat: add scenario branching and closure-aware routing"
~~~

---

### Task 10: Constraint-based resource allocation

**Files:**
- Create: backend/src/wildfireops/decision/optimizer.py
- Create: backend/src/wildfireops/decision/explanations.py
- Create: backend/tests/unit/decision/test_optimizer.py
- Create: backend/tests/unit/decision/test_optimizer_properties.py

**Interfaces:**
- Consumes: ResourceUnit and DemandPoint from Task 2, RouteResult from Task 9
- Produces: OptimizationRequest, OptimizationResult, solve_allocation(request), explain_result(result)

- [ ] **Step 1: Add OR-Tools and write the failing deterministic example**

Run:

~~~bash
cd backend
uv add ortools
uv add --dev hypothesis
~~~

Create two available engines, two demand points, and four candidate routes. Make the close engine compatible with the high-risk demand and assert:

- solver status is OPTIMAL
- the close compatible engine covers the high-risk demand
- one lower-risk destination remains uncovered when capacity is insufficient
- the objective components equal travel cost plus uncovered-risk penalty

- [ ] **Step 2: Run the optimizer test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/unit/decision/test_optimizer.py -v
~~~

Expected: FAIL because optimizer.py does not exist.

- [ ] **Step 3: Define exact optimizer inputs and outputs**

Use frozen types:

~~~python
from dataclasses import dataclass

from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult


@dataclass(frozen=True, slots=True)
class CandidateRoute:
    resource_id: str
    destination_id: str
    route: RouteResult


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    resources: tuple[ResourceUnit, ...]
    demands: tuple[DemandPoint, ...]
    routes: tuple[CandidateRoute, ...]
    max_response_minutes: int
    max_solver_seconds: float = 2.0
    algorithm_version: str = "allocation-v1"


@dataclass(frozen=True, slots=True)
class Assignment:
    resource_id: str
    destination_id: str
    travel_minutes: float
    capacity: int


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    status: str
    assignments: tuple[Assignment, ...]
    uncovered_destination_ids: tuple[str, ...]
    travel_cost: int
    uncovered_risk_penalty: int
    objective_value: int
    runtime_milliseconds: int
    algorithm_version: str
~~~

- [ ] **Step 4: Implement the CP-SAT model**

Create one Boolean x variable for each available, compatible, reachable resource/destination pair within max_response_minutes and one covered Boolean per destination. Add:

- sum of x values per resource <= 1
- sum of assigned capacity per destination >= required_capacity multiplied by covered
- sum of x values per destination <= candidate count multiplied by covered

Minimize integer travel minutes plus 1000 multiplied by normalized uncovered weighted risk. Set num_search_workers=1 and random_seed=0 for replay determinism. Return INFEASIBLE, FEASIBLE, OPTIMAL, or UNKNOWN without inventing assignments for non-solution statuses.

- [ ] **Step 5: Add property-based invariant tests**

Generate up to eight resources and eight demands. For every FEASIBLE or OPTIMAL result assert:

- no resource appears twice
- unavailable resources never appear
- every assignment is compatible
- every route is reachable and within the response limit
- covered demand receives at least its required capacity
- assignments and uncovered IDs are stably sorted

- [ ] **Step 6: Implement human-readable explanations**

explain_result returns:

- selected assignments with travel time and capacity rationale
- uncovered destinations with the limiting reason
- binding availability, compatibility, route, capacity, and response-time constraints
- objective component values
- solver status, runtime, and algorithm version

The explanation must use deterministic templates and must not use an LLM.

- [ ] **Step 7: Run example and property tests**

Run:

~~~bash
cd backend
uv run pytest tests/unit/decision/test_optimizer.py tests/unit/decision/test_optimizer_properties.py -v
~~~

Expected: deterministic example and generated invariants pass.

- [ ] **Step 8: Commit allocation**

~~~bash
git add backend/src/wildfireops/decision/optimizer.py backend/src/wildfireops/decision/explanations.py backend/tests/unit/decision backend/pyproject.toml backend/uv.lock
git commit -m "feat: optimize explainable resource assignments"
~~~

---

### Task 11: Recommendation commands, operator decisions, and audit transactions

**Files:**
- Create: backend/src/wildfireops/decision/recommendations.py
- Create: backend/src/wildfireops/decision/commands.py
- Create: backend/src/wildfireops/persistence/recommendations.py
- Create: backend/src/wildfireops/persistence/decisions.py
- Create: backend/src/wildfireops/api/schemas/scenarios.py
- Create: backend/src/wildfireops/api/schemas/decisions.py
- Create: backend/src/wildfireops/api/routes/scenarios.py
- Create: backend/src/wildfireops/api/routes/decisions.py
- Create: backend/src/wildfireops/api/routes/audit.py
- Modify: backend/src/wildfireops/main.py
- Create: backend/tests/integration/api/test_decision_flow.py
- Create: backend/tests/integration/decision/test_audit_transaction.py

**Interfaces:**
- Consumes: ScenarioService from Task 9, route calculation from Task 9, optimizer and explanations from Task 10
- Produces: scenario and recommendation command APIs, DecisionCommandService.decide(), GET /api/audit-events

- [ ] **Step 1: Write the failing complete-decision API test**

Seed an incident snapshot, scenario version, two resources, two demands, and routes. Execute:

1. POST /api/scenario-versions/{version_id}/recommendations with Idempotency-Key rec-1
2. POST /api/recommendations/{recommendation_id}/decisions with Idempotency-Key decision-1 and action approve
3. GET /api/audit-events?recommendationId={recommendation_id}

Assert the recommendation includes assignments, uncovered destinations, objective components, solver status, runtime, algorithm version, and explanation. Assert approval creates assignments and exactly one audit event.

- [ ] **Step 2: Run the decision-flow test and confirm the red state**

Run:

~~~bash
cd backend
uv run pytest tests/integration/api/test_decision_flow.py -v
~~~

Expected: FAIL because command routers are not registered.

- [ ] **Step 3: Implement recommendation generation**

RecommendationService.generate must:

1. load the immutable scenario and pinned incident snapshot
2. reject missing or invalid source versions
3. apply weather, road, and resource overlays
4. recompute risk inputs
5. calculate closure-aware routes
6. solve allocation
7. persist request inputs, graph version, source versions, risk version, allocation version, result, and explanation
8. return the stored recommendation

The same idempotency key and body returns the existing recommendation. The same key with a different body returns 409 idempotency_conflict.

- [ ] **Step 4: Write stale and edited-decision tests**

Test that:

- changing the relevant incident snapshot after recommendation generation causes approval to return 409 recommendation_stale
- reject stores the note but creates no assignments
- edit validates revised assignments against availability, compatibility, capacity, route closure, and response time before storing an edited decision
- an invalid edit returns 422 and creates no decision or audit rows

- [ ] **Step 5: Implement atomic decision handling**

Expose:

~~~python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    action: Literal["approve", "reject", "edit"]
    note: str
    edited_assignments: tuple[tuple[str, str], ...] = ()


class DecisionCommandService:
    async def decide(
        self,
        recommendation_id: str,
        request: DecisionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> str:
        recommendation = await self.repository.lock_recommendation(
            recommendation_id
        )
        self.validator.require_current(recommendation)
        validated = await self.validator.validate_decision(recommendation, request)
        decision_id = await self.repository.store_decision(validated, actor_id)
        await self.repository.store_assignments_if_approved(validated, decision_id)
        await self.repository.append_audit_event(validated, actor_id, decision_id)
        await self.repository.commit()
        return decision_id
~~~

The real implementation receives a session-scoped repository and rolls back on any exception. Require a nonblank note for all three actions.

- [ ] **Step 6: Register command and audit routes**

Implement:

- POST /api/incidents/{incident_id}/scenarios
- POST /api/scenarios/{scenario_id}/versions
- POST /api/scenario-versions/{version_id}/recommendations
- POST /api/recommendations/{recommendation_id}/decisions
- GET /api/audit-events
- GET /api/audit-events/{event_id}

All command routes require Idempotency-Key. The portfolio actor is the constant demo-operator until authentication exists outside MVP scope.

- [ ] **Step 7: Prove rollback and audit atomicity**

Inject a repository failure after assignment insertion and before audit insertion. Assert decision, assignment, and audit tables all remain unchanged. Retry with the same idempotency key after removing the injected failure and assert one decision, its assignments, and one audit event.

- [ ] **Step 8: Run command and transaction tests**

Run:

~~~bash
cd backend
uv run pytest tests/integration/api/test_decision_flow.py tests/integration/decision/test_audit_transaction.py -v
~~~

Expected: approve, reject, edit, stale conflict, validation, idempotency, and rollback cases pass.

- [ ] **Step 9: Commit decision workflow**

~~~bash
git add backend/src/wildfireops/decision backend/src/wildfireops/persistence backend/src/wildfireops/api backend/src/wildfireops/main.py backend/tests/integration/api backend/tests/integration/decision
git commit -m "feat: record auditable operator decisions"
~~~

---

### Task 12: Frontend incident queue, map, timeline, and freshness

**Files:**
- Create: frontend/src/app/AppProviders.tsx
- Create: frontend/src/app/AppShell.tsx
- Create: frontend/src/app/ErrorBoundary.tsx
- Create: frontend/src/api/client.ts
- Create: frontend/src/api/types.ts
- Create: frontend/src/api/hooks.ts
- Create: frontend/src/features/incidents/IncidentQueue.tsx
- Create: frontend/src/features/incidents/IncidentDetails.tsx
- Create: frontend/src/features/incidents/FreshnessBadge.tsx
- Create: frontend/src/features/incidents/ReplayTimeline.tsx
- Create: frontend/src/features/map/OperationsMap.tsx
- Create: frontend/src/features/map/layers.ts
- Create: frontend/src/test/server.ts
- Create: frontend/src/test/fixtures.ts
- Create: frontend/src/test/maplibre.ts
- Create: frontend/src/features/incidents/IncidentQueue.test.tsx
- Create: frontend/src/app/AppShell.test.tsx
- Modify: frontend/src/App.tsx

**Interfaces:**
- Consumes: read APIs and SSE from Task 8
- Produces: typed ApiClient, useIncidents(), useIncident(id), useSourceStatus(), useIncidentEvents(), complete observe workflow

- [ ] **Step 1: Add client test dependencies and write the failing queue test**

Run:

~~~bash
cd frontend
npm install msw
~~~

Create a fixture with Redwood Creek risk 82 and Bear Ridge risk 61. Render IncidentQueue and assert risk-descending order, exposed counts, freshness text, selection callback, and visible simulated-data legend.

- [ ] **Step 2: Run the queue test and confirm the red state**

Run:

~~~bash
cd frontend
npm test -- --run src/features/incidents/IncidentQueue.test.tsx
~~~

Expected: FAIL because IncidentQueue does not exist.

- [ ] **Step 3: Define typed API contracts and client behavior**

frontend/src/api/types.ts must mirror the backend camelCase schemas, including:

~~~ts
export type Freshness = "fresh" | "stale" | "unavailable";

export interface RiskContribution {
  name: string;
  rawValue: number;
  normalizedValue: number;
  weight: number;
  contribution: number;
}

export interface IncidentSummary {
  id: string;
  name: string;
  risk: {
    score: number;
    algorithmVersion: string;
    contributions: RiskContribution[];
  };
  exposedAssetCount: number;
  lastObservedAt: string;
  freshness: Freshness;
}
~~~

ApiClient must parse responses with Zod, convert non-2xx responses into ApiClientError(code, message, details, status), and use relative /api URLs in production.

- [ ] **Step 4: Implement providers and incident query hooks**

AppProviders creates one QueryClient. useIncidentEvents opens one EventSource, invalidates only affected incident and source-status keys, and reconnects through the browser's SSE behavior. Tests mock EventSource and assert targeted invalidation.

- [ ] **Step 5: Implement the queue, detail panel, and freshness states**

IncidentQueue renders keyboard-accessible buttons ordered by the server response. FreshnessBadge pairs text and icon with color. IncidentDetails displays each risk factor's raw value, weight, contribution, algorithm version, source timestamps, exposed assets, and the simulated-resource label.

- [ ] **Step 6: Write the failing application-shell test**

Mock the API and assert the desktop surface contains:

- persistent safety statement
- incident queue
- map region with accessible name Wildfire operations map
- decision workspace heading
- source freshness summary
- replay timeline

- [ ] **Step 7: Implement MapLibre and replay timeline**

OperationsMap owns a single MapLibre instance and updates named GeoJSON sources for detections, incident geometry, assets, simulated resources, routes, and closures. layers.ts defines stable layer IDs and source IDs. The test shim records source data and layer visibility without WebGL.

ReplayTimeline accepts currentTime, startTime, endTime, playing, onSeek, and onPlayChange. It uses a native range input with a visible UTC timestamp.

- [ ] **Step 8: Assemble the responsive application shell**

Use CSS Grid with an incident rail, dominant map, and decision workspace at laptop width. Stack the decision workspace below the map below 900 px. Do not create a mobile-specific navigation system.

- [ ] **Step 9: Run frontend unit tests and build**

Run:

~~~bash
cd frontend
npm test -- --run
npm run lint
npm run build
~~~

Expected: incident, shell, API, SSE, and map-shim tests pass; TypeScript build succeeds.

- [ ] **Step 10: Commit the observation interface**

~~~bash
git add frontend
git commit -m "feat: visualize incidents and source freshness"
~~~

---

### Task 13: Frontend scenarios, comparisons, recommendations, and audit

**Files:**
- Create: frontend/src/features/scenarios/ScenarioEditor.tsx
- Create: frontend/src/features/scenarios/ScenarioComparison.tsx
- Create: frontend/src/features/scenarios/ScenarioEditor.test.tsx
- Create: frontend/src/features/decisions/RecommendationPanel.tsx
- Create: frontend/src/features/decisions/DecisionDialog.tsx
- Create: frontend/src/features/decisions/RecommendationPanel.test.tsx
- Create: frontend/src/features/audit/AuditDrawer.tsx
- Create: frontend/src/features/audit/AuditDrawer.test.tsx
- Modify: frontend/src/api/types.ts
- Modify: frontend/src/api/hooks.ts
- Modify: frontend/src/app/AppShell.tsx

**Interfaces:**
- Consumes: command and audit APIs from Task 11
- Produces: create-scenario, compare, generate-recommendation, approve/reject/edit, and audit-detail UI

- [ ] **Step 1: Write the failing scenario-editor interaction test**

Render ScenarioEditor with known road and resource options. Add one road closure, set wind speed to 12 m/s and direction to 220 degrees, mark Crew 4 unavailable, and submit. Assert the callback receives:

~~~ts
{
  roadClosures: [{ edgeId: "edge-9" }],
  weatherOverrides: [{ windSpeedMps: 12, windDirectionDegrees: 220 }],
  resourceOverrides: [{ resourceId: "crew-4", available: false }]
}
~~~

- [ ] **Step 2: Run the scenario test and confirm the red state**

Run:

~~~bash
cd frontend
npm test -- --run src/features/scenarios/ScenarioEditor.test.tsx
~~~

Expected: FAIL because ScenarioEditor does not exist.

- [ ] **Step 3: Implement typed immutable scenario editing**

ScenarioEditor creates a new version request instead of mutating loaded scenario data. Use native fields with labels and field-level API validation messages. Disable submit when values are invalid or unchanged.

- [ ] **Step 4: Implement baseline comparison**

ScenarioComparison displays baseline and scenario values for:

- risk score and factor changes
- weighted risk covered
- weighted risk uncovered
- total travel minutes
- unreachable destinations
- unavailable resources

Show absolute values and deltas together. Pair all status colors with text.

- [ ] **Step 5: Write failing recommendation and decision tests**

Test that RecommendationPanel renders assignments, routes, uncovered destinations, solver status, runtime, algorithm versions, objective components, and constraint explanations. Test approve, reject, and edit dialogs require a nonblank note and send a fresh Idempotency-Key per new action.

- [ ] **Step 6: Implement recommendation and decision controls**

RecommendationPanel must not collapse infeasible or unknown solver results into an empty success state. DecisionDialog shows recommendation freshness and disables approval after an SSE invalidation until the operator regenerates the recommendation.

- [ ] **Step 7: Implement audit history**

AuditDrawer lists actor, event type, timestamp, scenario version, recommendation ID, source versions, algorithm versions, before/after references, and operator note. Its detail view visibly distinguishes observed, simulated, calculated, and operator-entered values.

- [ ] **Step 8: Connect scenario changes to map layers**

When a scenario version is selected, update weather direction annotation, closed-road layer, unavailable-resource style, route layer, and comparison panel from the same scenario-version response. Baseline selection removes only scenario overlays, not observed layers.

- [ ] **Step 9: Run frontend tests and build**

Run:

~~~bash
cd frontend
npm test -- --run
npm run lint
npm run build
~~~

Expected: scenario, comparison, recommendation, decision, audit, and full existing frontend tests pass.

- [ ] **Step 10: Commit the decision interface**

~~~bash
git add frontend
git commit -m "feat: add scenario and decision workspace"
~~~

---

### Task 14: Park Fire golden replay, degraded modes, and benchmarks

**Files:**
- Create: data/replay/park-fire/manifest.json
- Create: data/replay/park-fire/fire_detections.jsonl
- Create: data/replay/park-fire/weather_observations.jsonl
- Create: data/replay/park-fire/static_data_versions.json
- Create: data/replay/park-fire/source_citations.json
- Create: data/replay/park-fire/exposed_assets.geojson
- Create: data/replay/park-fire/resources.json
- Create: data/replay/park-fire/roads.graphml.gz
- Create: data/replay/park-fire/golden_outputs.json
- Create: backend/tests/integration/replay/test_park_fire_golden.py
- Create: backend/tests/integration/resilience/test_degraded_modes.py
- Create: backend/tests/performance/test_incident_query.py
- Create: backend/tests/performance/test_optimizer_runtime.py
- Create: frontend/e2e/replay-decision.spec.ts

**Interfaces:**
- Consumes: the complete backend and frontend workflow from Tasks 1-13
- Produces: deterministic offline demonstration, golden assertions, failure-mode proof, published benchmark source

- [ ] **Step 1: Build and validate the Park Fire package**

Acquire and normalize NASA FIRMS, NOAA historical observations, versioned
Census-derived community data, and a versioned OSM facility extract outside the
committed package. Credentials are never passed to the builder. Stage these
inputs before building:

~~~text
fire_detections.jsonl
weather_observations.jsonl
metadata.json
exposed_assets.geojson
resources.json
~~~

The builder produces `static_data_versions.json` and `source_citations.json`
from the source maps in staged `metadata.json`; do not stage duplicate source-map
files.

Run:

~~~bash
cd backend
uv run python -m wildfireops.replay.build \
  --source-dir ../data/staging/park-fire \
  --package-id park-fire-2024-v1 \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --start 2024-07-24T00:00:00Z \
  --end 2024-08-02T00:00:00Z \
  --output ../data/replay/park-fire
uv run python -m wildfireops.geospatial.road_graph build \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --output ../data/replay/park-fire/roads.graphml.gz
~~~

The replay builder's final `ReplayLoader(temporary)` call validates the replay
package; the road-graph builder then attaches graph metadata to the completed
package.

Expected: every manifest hash and schema check passes, every file is nonempty, and no secret appears in the package.

- [ ] **Step 2: Create and manually inspect golden outputs**

Load the replay, run the fixed baseline and road-closure scenario, then write golden_outputs.json containing:

- incident memberships and centroids
- source versions and freshness at the selected replay time
- risk factor values and total
- route status and edge IDs for selected origin/destination pairs
- solver status
- assignment resource/destination pairs
- uncovered destination IDs
- objective components and algorithm versions

Review the file against the UI and source records before committing it.

- [ ] **Step 3: Write the golden integration test**

The test loads the package into an empty database, advances the replay clock to `manifest.end_at`, runs clustering, exposure, risk, routing, and allocation, and compares stable semantic outputs with golden_outputs.json. Exclude wall-clock runtime and generated database UUIDs from equality.

- [ ] **Step 4: Write explicit degraded-mode tests**

Test:

- FIRMS 503 preserves prior observations and marks the source stale
- malformed source record enters quarantine with a reason
- repeated replay load creates no duplicate observations
- closed roads never appear in a route
- unreachable demand remains visible
- capacity shortage returns a deterministic solution with uncovered destinations
- stale recommendation approval returns 409
- injected audit failure rolls the decision back

- [ ] **Step 5: Write the full Playwright demonstration**

frontend/e2e/replay-decision.spec.ts must:

1. load the replay
2. select the highest-risk Park Fire incident
3. verify risk factors and freshness
4. create a road closure
5. generate a recommendation
6. compare baseline and scenario
7. approve with note "Stage resources for replay exercise"
8. verify the audit event

Capture screenshots after incident selection, scenario comparison, and audit confirmation for README use.

- [ ] **Step 6: Add repeatable performance tests**

The incident-query test loads the full replay and records p50 and p95 across 100 selected-incident requests after 10 warmups. The optimizer test runs fixed cases at 5/10, 10/25, and 20/50 resource/destination sizes and records median and p95 runtime.

Write machine metadata, dataset manifest hash, Python version, Postgres version, graph version, and algorithm versions beside results.

- [ ] **Step 7: Run golden, degraded, browser, and performance checks**

Run:

~~~bash
make replay-reset
make test-golden
make test-degraded
cd frontend
npx playwright test e2e/replay-decision.spec.ts
cd ..
make benchmark
~~~

Expected: golden and degraded-mode tests pass; the Playwright workflow passes; benchmark output reports whether the p95 incident target of 500 ms and the 20/50 recommendation target of two seconds are met.

- [ ] **Step 8: Commit replay proof**

~~~bash
git add data/replay/park-fire backend/tests/integration/replay backend/tests/integration/resilience backend/tests/performance frontend/e2e docs/images
git commit -m "test: prove the Park Fire decision workflow"
~~~

Do not commit videos, traces, or the full Playwright HTML report. Copy only the three selected screenshots into docs/images before running the commit command.

---

### Task 15: CI, production packaging, public deployment configuration, and portfolio documentation

**Files:**
- Create: Dockerfile
- Modify: compose.yaml
- Create: render.yaml
- Create: .github/workflows/ci.yml
- Create: README.md
- Create: docs/architecture.md
- Create: docs/data-sources.md
- Create: docs/benchmarks.md
- Create: docs/demo-script.md
- Create: docs/images/incident.png
- Create: docs/images/scenario.png
- Create: docs/images/audit.png
- Modify: backend/src/wildfireops/main.py
- Modify: .gitignore

**Interfaces:**
- Consumes: all implementation and verification tasks
- Produces: reproducible CI, one-command local startup, deployable production image, reviewed Render Blueprint, public portfolio presentation

- [ ] **Step 1: Write the failing production-image smoke check**

Add make smoke-production to build the root Dockerfile, start it with a disposable PostGIS database, run migrations and replay seed, request /api/health, request /, and assert the root returns the built React application containing the safety statement.

Run:

~~~bash
make smoke-production
~~~

Expected: FAIL because the production Dockerfile and static mounting do not exist.

- [ ] **Step 2: Implement the production image**

Use a multi-stage Dockerfile:

1. Node stage runs npm ci and npm run build in frontend.
2. Python stage installs uv, runs uv sync --frozen --no-dev in backend, copies backend source and frontend/dist, and runs the API as a non-root user.
3. The worker uses the same image with a different command.

In production only, FastAPI mounts the built client assets and serves index.html for non-API routes. API, docs, health, and SSE routes retain the /api prefix.

- [ ] **Step 3: Implement CI**

.github/workflows/ci.yml must use:

- actions/checkout@v6
- actions/setup-python@v5 with Python 3.12
- actions/setup-node@v4 with the Node version recorded in frontend/package.json
- a postgis/postgis service container
- uv sync --frozen
- npm ci

Jobs run backend lint, mypy, unit tests, PostGIS integration tests, frontend lint, Vitest, frontend build, golden replay, production-image smoke, and Playwright. Cache only package-manager caches, never replay outputs or secrets.

- [ ] **Step 4: Create and validate the Render Blueprint**

Create a root render.yaml defining:

- wildfireops-api as type web, runtime docker, healthCheckPath /api/health, and autoDeployTrigger checksPass
- wildfireops-worker as type worker, runtime docker, and dockerCommand running the ingestion worker
- wildfireops-db as Render Postgres with external IP access disabled
- WILDFIREOPS_DATABASE_URL sourced from the database connection string
- WILDFIREOPS_FIRMS_MAP_KEY as sync false
- WILDFIREOPS_ENVIRONMENT set to production

Render currently supports web, worker, Docker, Blueprint-managed Postgres, and the PostGIS extension. Validate the file against the current [Render Blueprint reference](https://render.com/docs/blueprint-spec) and [Render Postgres extension list](https://render.com/docs/postgresql-extensions).

Do not apply the Blueprint yet. A background worker and persistent Postgres can incur charges.

- [ ] **Step 5: Write portfolio documentation**

README.md must lead with:

- one-sentence operator problem
- simulation and safety statement
- 60-90 second demo video link
- three screenshots
- architecture diagram
- Observe → Decide → Act → Audit walkthrough
- measured dataset and performance numbers
- one-command local setup
- test commands
- design trade-offs and non-goals

docs/data-sources.md records source URLs, licenses or attribution requirements, retrieval dates, versioning, transformations, freshness rules, and which records are simulated.

docs/benchmarks.md contains actual command output summarized with machine and dataset metadata. Never copy acceptance targets into the measured-results column.

Record the 60-90 second demo from the verified public deployment. Keep the local video out of Git; publishing it to a GitHub release or unlisted video host is an external write that requires user approval.

- [ ] **Step 6: Run the complete local verification**

Run:

~~~bash
make clean
make dev-detached
make migrate
make replay-load
make test
make test-golden
make test-degraded
make benchmark
make smoke-production
cd frontend
npx playwright test
cd ..
git diff --check
~~~

Expected: every command exits 0 and the documented benchmark report is regenerated from the committed replay manifest.

- [ ] **Step 7: Review deployment cost and request authorization**

Check current Render service and database pricing, show the user the exact recurring cost and free limitations, and request explicit approval before creating external resources or applying render.yaml. Ask separately whether the user wants the demo video attached to a GitHub release or published through an unlisted video host.

- [ ] **Step 8: Deploy only after approval**

After authorization, apply the Blueprint, enable PostGIS with CREATE EXTENSION postgis, run migrations, load the replay, set FIRMS_MAP_KEY, verify the health endpoint, run the three-minute demonstration against the public URL, and record the URL in README.md.

- [ ] **Step 9: Commit production and portfolio assets**

~~~bash
git add Dockerfile compose.yaml render.yaml .github README.md docs backend/src/wildfireops/main.py .gitignore
git commit -m "docs: publish WildfireOps portfolio project"
~~~

---

## Spec-to-task coverage

| Specification area | Implemented by |
|---|---|
| Product thesis, safety, and three-minute workflow | Tasks 1, 12-15 |
| Real data, provenance, freshness, and simulation labels | Tasks 2-8, 12, 14 |
| Modular-monolith architecture and one-command startup | Tasks 1, 3, 15 |
| Observed, scenario, recommendation, decision, and audit model | Tasks 2, 3, 9-11 |
| Incident clustering and stable identity | Task 6 |
| Exposure and explainable risk | Task 7 |
| Read APIs, errors, timeline, source status, and SSE | Task 8 |
| Immutable scenario overlays and routing | Task 9 |
| Constraint-based allocation and explanations | Task 10 |
| Idempotent commands, stale checks, decisions, and atomic audit | Task 11 |
| Incident, map, replay, scenario, comparison, and audit UI | Tasks 12-13 |
| Source failures, quarantine, idempotency, unreachable and infeasible states | Tasks 4, 6, 9-11, 14 |
| Unit, property, PostGIS, golden, Playwright, and performance tests | Tasks 1-14 |
| Observability, CI, packaging, deployment, and documentation | Tasks 6, 8, 10, 14-15 |
| Completion evidence and resume measurements | Tasks 14-15 |

## Final execution gate

Before calling the implementation complete, rerun Task 15 Step 6 from a clean working tree, inspect its complete output, and compare every completion criterion in the design specification with the coverage table above. Any unmet criterion remains open even if all currently written tests pass.
