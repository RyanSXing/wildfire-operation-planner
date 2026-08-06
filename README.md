# WildfireOps

**A wildfire resource-allocation system that can explain and defend every decision it recommends.**

Two operator surfaces over one decision engine: a guided training exercise built on the real
July 2024 Park Fire, and a live command centre for planning against incidents currently in the
system. Both are built on a constraint solver, a routed road network, and an append-only audit
trail — and both are designed so an operator never has to trust a number they cannot interrogate.

> **Portfolio simulation only. Do not use for emergency or life-safety decisions.**
> Historical fire, weather, and geographic data are real and cited. Every response unit,
> task, and priority is invented for the exercise. The interface says which is which on
> every screen, because a tool that blurs that line is worse than no tool.

---

## Contents

- [What it does](#what-it-does) · [Screenshots](#screenshots) · [Why it is interesting](#why-it-is-interesting)
- [Architecture](#architecture) · [The decision engine](#the-decision-engine) · [Data provenance](#data-provenance)
- [Metrics](#metrics) · [Running it](#running-it) · [Testing](#testing-and-verification)
- [Engineering decisions](#engineering-decisions-and-trade-offs) · [Known limitations](#known-limitations)

---

## What it does

A wildfire is burning. There are more places that need protecting than there are engines,
crews, and buses to protect them. Something has to be left uncovered, and whoever signs off
on that has to be able to say why.

WildfireOps turns that into a workflow:

1. **Observe** — ingest satellite fire detections, weather, road networks, and exposed
   populations; rank incidents by a transparent, weighted risk model.
2. **Plan** — allocate scarce units to competing tasks with a constraint solver, routed over
   a real road graph, under an objective the operator picks.
3. **Understand** — every allocation comes with what it covers, what it leaves uncovered,
   and *why* — in plain language, not solver vocabulary.
4. **Decide** — sign off with a name and a written reason. The decision, its inputs, and the
   plan it was made against go into an append-only audit trail.

### Two surfaces

| | **Decision Exercise** (`/`) | **Live Command Centre** (`/monitor`) |
|---|---|---|
| **Purpose** | Guided training on a fixed scenario | Planning against live incidents |
| **Data** | Pinned replay package — identical every run | Ingested feeds, refreshed over SSE |
| **Flow** | 3 scripted checkpoints with escalating pressure | Scenario branches you create and compare |
| **Ends with** | Named approval → audit → debrief → what-if sandbox | Approve / reject / edit → audit trail |

They share one design system, one interaction model, and one vocabulary — a command bar that
offers exactly one next action derived from server state, a map you work over, and a detail
drawer that separates *what the plan does* from *how the machine decided it*.

---

## Screenshots

**Decision Exercise** — the cascading-disruption checkpoint. Progress rail, live plot with
satellite fire detections and planned routes, plain-language plan review.

![Decision exercise workspace](docs/screenshots/exercise-workspace.png)

**Live Command Centre** — the same language applied to a live incident, with scenario
branching, replay scrubbing, and decision recording.

![Live command centre](docs/screenshots/monitor-workspace.png)

**Provenance gate** — every surface opens by stating what is real, what is simulated,
and that none of it is safe to act on.

![Provenance briefing](docs/screenshots/exercise-briefing.png)

---

## Why it is interesting

Most "AI/optimisation" demos produce a number. The engineering here is in everything
around the number.

### 1. Explanations are generated from evidence, not narrated

The solver emits **19 structured change codes** and **7 families of binding constraints**.
The frontend translates each into a sentence built from the actual evidence payload:

> `task.uncovered-contention` + `{taskId: "evacuate-chico", resourceIds: ["exercise-bus-1"]}`
> → **"Evacuate Chico city is uncovered — Evacuation bus 1 could do this job, but it is
> already committed elsewhere. Nothing else on scene has the right capability."**

No identifier reaches an operator's screen. Unrecognised codes are still stripped of
identifiers before display, so a backend addition degrades to *readable*, never to leaking
solver vocabulary. This is enforced by tests that assert the rendered text contains no
task ids, resource ids, or edge hashes.

### 2. Determinism is a product requirement, not an aspiration

The exercise runs on a content-addressed replay package with a manifest digest. Same
choices → same plan → same explanation, every time. Golden-output tests pin the solver's
results. The exercise definition carries a digest that every session records, so a plan can
always be traced to the exact inputs that produced it.

### 3. Optimistic concurrency the operator can actually recover from

Every write carries an `expectedVersion`. A stale write returns **409 with the authoritative
session in the response body**, so the client resynchronises without guessing. Idempotency
keys are caller-owned and canonicalised — an unchanged retry reuses its key; a changed body
mints a new one.

### 4. Staleness is latched, not merely detected

If the incident snapshot changes mid-planning, the session is marked stale **and stays
stale** even if the underlying props revert. In-flight results are retained for inspection
but cannot be acted on. Late responses are refused so they cannot resurrect a superseded
plan. Roughly 40 tests pin these semantics.

### 5. Provenance is structural

Simulated resources are *literal-typed* — a resource that fails to declare
`simulated: true` invalidates the entire response. The safety posture is enforced by the
schema, not by a comment.

---

## Architecture

```
┌──────────────── Frontend (React 19 · TypeScript · Vite) ────────────────┐
│                                                                          │
│   /  Decision Exercise            /monitor  Live Command Centre          │
│   ├── ExerciseWorkspace           ├── MonitorWorkspace                   │
│   └── useExerciseCommand          └── useMonitorData                     │
│                                       useScenarioPlanning                │
│              shared: design system · MapLibre plot · plain-language layer │
│                                                                          │
│   Zod-validated API client · TanStack Query · idempotent commands        │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ REST + Server-Sent Events
┌──────────────────────────────────┴───────────────────────────────────────┐
│                    Backend (FastAPI · Python 3.12 · async)                │
│                                                                          │
│  api/routes ──── api/schemas ──── application/ ──── decision/            │
│                                        │              ├── optimizer (CP-SAT)│
│                                        │              ├── task_optimizer   │
│                                        │              ├── risk             │
│                                        │              └── explanations     │
│                                   persistence/    geospatial/  replay/     │
│                                        │           ├── road_graph          │
│                                        │           ├── clustering          │
│                                        │           └── exposure            │
│                              PostGIS + Alembic (5 migrations)              │
└──────────────────────────────────────────────────────────────────────────┘
              ▲
   ingestion/ │ NASA FIRMS (satellite) · NOAA NCEI (weather) · OSM (roads)
```

**Layering is enforced by tests.** `tests/architecture/test_api_boundaries.py` fails the
build if a route reaches past the application layer into persistence.

---

## The decision engine

### Risk model (`risk-v1`)

Incidents are ranked by six weighted, independently-reported contributions — each returned
with its raw inputs so the score can be audited rather than trusted:

| Contribution | Weight | Raw evidence surfaced |
|---|---|---|
| `proximity` | 0.30 | buffer, nearest distance |
| `population` | 0.25 | exposed population, community count |
| `critical_facilities` | 0.20 | count, kinds |
| `wind_alignment` | 0.15 | bearing, speed, weather identity |
| `detection_confidence` | 0.05 | mean confidence, detection count |
| `source_freshness` | 0.05 | fire and weather observation age |

Saturation points are explicit and configurable (population 10,000; critical facilities 5;
wind 15 m/s), so a contribution cannot silently dominate the score.

### Allocation (`task-allocation-v1`, OR-Tools CP-SAT)

Assign scarce units to tasks subject to capability matching, capacity, route reachability,
and deadlines — minimising a weighted objective the operator chooses:

| Objective | Optimises for | Gives up |
|---|---|---|
| Reach tasks fastest | travel time | distant critical sites |
| Protect critical services | hospitals, power, comms | large-population evacuations |
| Cover the most people | population protected | small critical sites |

The trade-off is stated **on the button**, before the choice is made.

### Routing

Real OpenStreetMap road network (**18,154 edges**), with closures applied per scenario.
Routes return real edge geometry and human road names, so the UI can say *"via Golden Oaks
Road"* rather than showing a hash.

---

## Data provenance

| Real and cited | Invented for the exercise |
|---|---|
| **151 VIIRS fire detections** (NASA FIRMS, July 2024 Park Fire) | All 4 response units and their positions |
| **3 NOAA NCEI weather observations** with station identities | Every task, priority, and capacity |
| **8 real places** — Paradise, Chico, Butte Meadows, Adventist Health Feather River, CARD Community Center, Paradise Substation, KPAY-FM, Nunneley Road — each with a source URL | The spot fire at checkpoint 2 |
| OpenStreetMap road network | The road closure and shelter field report |

Every real place links to its published source (Census, OpenStreetMap) directly in the UI.

---

## Metrics

| | |
|---|---|
| **Backend source** | 19,768 lines · 83 modules |
| **Backend tests** | 22,471 lines · 60 files |
| **Frontend source** | 15,925 lines |
| **Frontend tests** | 9,065 lines · 26 files |
| **Test-to-source ratio** | **1.14 : 1** backend · 0.57 : 1 frontend · **0.88 : 1** overall |
| **API surface** | 24 operations across 8 route modules |
| **Database** | PostGIS · 5 Alembic migrations |
| **Road network** | 18,154 routable edges |

### Test suite

| Suite | Count | Requires |
|---|---|---|
| Backend unit | **757** | — |
| Backend architecture | **3** | — |
| Backend integration | **191** | PostGIS on `:55432` |
| Frontend unit / component | **254** across 23 files | — |
| Playwright end-to-end | **9** | running API + dev server |
| **Total** | **1,214** | |

Also enforced: `ruff`, `mypy --strict` on `src` (clean, 83 files), `oxlint`, `tsc -b`.

> Backend unit/architecture (760) and frontend (254) were re-verified at the time of writing.
> Integration (191) and Playwright (9) were verified earlier in the same session and need
> the Docker stack up — see below.

---

## Running it

**Prerequisites:** Docker, Node 22+, [uv](https://docs.astral.sh/uv/).

### Full stack

```bash
make dev
```

Frontend on <http://localhost:5173>, API on <http://localhost:8000>.

### Deterministic Park Fire replay

```bash
./scripts/replay-preview
```

Starts an isolated Compose project (`db`, `api`, `frontend` — no live ingestion worker) with
the pinned replay package seeded. Fails fast if a host port is occupied rather than
disturbing your development stack.

### Frontend routes

| Route | Surface |
|---|---|
| `/` | Park Fire decision exercise |
| `/monitor` | Live command centre |

Both are desktop-only by design: the workspace assumes a rail, a map, and a detail drawer
side by side.

---

## Testing and verification

```bash
# Backend — unit + architecture (no infrastructure needed)
cd backend && uv run pytest tests/unit tests/architecture -q

# Backend — integration (needs PostGIS on :55432)
cd backend && WILDFIREOPS_DATABASE_URL="postgresql+asyncpg://wildfireops:wildfireops@localhost:55432/wildfireops_test" \
  uv run pytest tests/integration -q

# Backend — static analysis
cd backend && uv run ruff check . && uv run mypy src

# Frontend — everything
cd frontend && npm run lint && npx tsc -b && npm test -- --run && npm run build

# End-to-end (needs a running replay stack)
cd frontend && npx playwright test
```

The Playwright global setup **reuses** an already-healthy replay stack and only invokes the
launcher when nothing is listening on the API port — because `scripts/replay-preview` deletes
volumes, and a test harness should not be able to destroy a running database.

---

## Engineering decisions and trade-offs

The parts a reviewer might reasonably question, and the reasoning.

**Headless hooks over component rewrites.** Four components mixed real state machines into
their markup. Rather than rewriting them during a visual redesign, the logic was extracted
into `useScenarioPlanning`, `useMonitorData`, `useDecisionForm`, and `useScenarioDraft` —
each verified by leaving its original test file *byte-for-byte unchanged* and still passing.
That is the proof the move was faithful, and it is checkable with `git status`.

**No fabricated fire perimeter.** The design called for one. The data has satellite detection
points, not a perimeter polygon. Deriving a hull and presenting it as a perimeter would be
inventing a boundary the data does not contain, in a tool whose entire premise is honest
provenance. Detections are drawn as detections.

**Joining fire data by detection identity, not incident name.** The replay's clustering can
place the detection an exercise cites inside an incident whose generated name is *not* "Park
Fire". Matching on name draws a different fire kilometres away with nothing on screen to
reveal the error. The join is by cited identity and is unit-tested for exactly that case.

**Basemap tiles are a convenience, not a dependency.** A style error swaps in a flat plot and
every overlay still renders — covered by a test that emits the error and asserts the fallback.

**The end-to-end decision spec rejects rather than approves.** Approving dispatches a unit
permanently, so it can only pass once per seeded database. Rejection records the same
decision, note, and audit event without consuming a resource, so the suite is repeatable.
Editing is not a workaround — the server only accepts units the recommendation could
actually have used. The approval path stays covered by component tests.

---

## Known limitations

- **Desktop-only.** The original design brief specified four responsive breakpoints for the
  command centre; both surfaces currently assume a desktop layout.
- **`OperationsMap` and `AppShell` are dead code.** Superseded by the command centre; their
  tests still pass and still count toward the totals above. Retiring them removes real
  assertions, so it has not been done silently.
- **The monitor's approval path is once-per-seeded-database.** A dispatched unit cannot be
  redispatched — correct domain behaviour, but it means full approval coverage end-to-end
  needs a fresh seed.
- **Exercise sessions expire after 24 hours.** Handled with an explicit "start a new
  exercise" path rather than a dead end.

---

## Repository layout

```
backend/
  src/wildfireops/
    api/          routes, schemas, error envelope, SSE event bus
    application/  command services, read models, exercise orchestration
    decision/     CP-SAT optimisers, risk model, explanation generators
    geospatial/   road graph, clustering, exposure analysis
    ingestion/    NASA FIRMS + NOAA NCEI sources, quarantine, worker
    persistence/  SQLAlchemy models and repositories
    replay/       deterministic package loader, seeder, manifest
  tests/          unit · integration · architecture
frontend/
  src/
    api/          Zod-validated client, TanStack Query hooks, idempotency
    exercise/     decision exercise surface
    monitor/      live command centre surface
    features/     shared incident, map, scenario, decision components
    ui/           the design system
  e2e/            Playwright specs
data/replay/      pinned Park Fire package
docs/             design specs and implementation plans
```
