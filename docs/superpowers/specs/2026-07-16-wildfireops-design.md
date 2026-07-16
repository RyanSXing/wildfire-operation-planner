# WildfireOps Design Specification

**Status:** Approved design

**Date:** 2026-07-16

## 1. Purpose

WildfireOps is a portfolio-grade geospatial decision-support application for a county emergency coordinator responding to a wildfire. It integrates real fire, weather, road, infrastructure, and population data; identifies exposed locations; lets an operator test operational assumptions; recommends how to allocate limited simulated resources; and records the operator's final decision.

The project is designed for a rising-junior software engineering candidate applying to Palantir. It demonstrates the qualities emphasized in Palantir's current Software Engineer internship description: end-to-end product ownership, clean code, data and storage systems, cloud infrastructure, frontend development, independent decision-making, and collaboration with non-technical users. The reference job description is <https://jobs.lever.co/palantir/7d69cf8a-06fd-4f05-bd84-27149db29c4d>.

WildfireOps is a portfolio simulation, not an emergency-management product. It must display a persistent disclaimer that its risk scores and recommendations are illustrative and must not be used for life-safety decisions.

## 2. Product thesis

Most student data projects end with a dashboard. WildfireOps instead implements a complete operational loop:

1. **Observe:** ingest, normalize, and display real external data with provenance and freshness.
2. **Decide:** rank incidents, evaluate scenarios, and compute constrained recommendations.
3. **Act:** let an operator approve, reject, or edit a recommendation.
4. **Audit:** store the inputs, assumptions, model version, action, author, and timestamp.

The primary portfolio signal is not the wildfire theme. It is the ability to convert imperfect, changing data into an explainable and reliable operator workflow.

## 3. Target user and core job

The target user is a fictional county emergency coordinator responsible for prioritizing wildfire incidents and staging a limited inventory of crews and response vehicles.

Their core job is:

> Given the current fire observations, weather, roads, exposed communities, and available resources, determine which locations require attention and how resources should be staged under changing conditions.

The application supports this job without claiming to predict fire behavior. It surfaces observations, applies transparent portfolio heuristics, computes routing and allocation outcomes, and leaves the final decision with the operator.

## 4. Demonstration narrative

The polished demonstration must take no more than three minutes:

1. Open a replay of the 2024 Park Fire in Northern California.
2. Select a high-risk incident from the incident queue.
3. Inspect its fire detections, exposed communities and facilities, data freshness, and risk-factor breakdown.
4. Create a scenario in which wind changes direction, a road closes, or a resource becomes unavailable.
5. Compare baseline and scenario travel times, covered weighted risk, and uncovered locations.
6. Review the recommended resource assignments and their constraints.
7. Approve, reject, or edit the recommendation with an operator note.
8. Open the audit entry showing the scenario inputs, algorithm version, recommendation, and decision.

Live mode is a secondary capability. Replay mode is the primary demonstration because it remains deterministic when no nearby wildfire is active or an external API is unavailable.

## 5. Scope

### 5.1 Required MVP capabilities

- Ingest NASA FIRMS fire detections and live National Weather Service observations or alerts.
- Load a bounded OpenStreetMap road and facility extract plus U.S. Census population data for the demonstration region.
- Package archived fire and weather observations for a deterministic Park Fire replay.
- Store source, source identifier, observation time, ingestion time, freshness state, and raw-record reference for every external observation.
- Cluster fire detections into operational incidents.
- Link incidents spatially to exposed communities, hospitals, shelters, and roads.
- Calculate and display an explainable heuristic risk score.
- Display an incident queue, interactive map, time controls, selected-incident details, and source-freshness indicators.
- Create immutable scenarios containing weather, road, and resource-availability overrides.
- Recalculate routing and resource allocation for a scenario without mutating observed reality.
- Compare baseline and scenario outcomes.
- Produce a constrained, explainable allocation recommendation.
- Let an operator approve, reject, or edit the recommendation.
- Store an append-only audit record for each decision.
- Handle stale feeds, malformed records, repeated ingestion, invalid scenarios, and infeasible optimization explicitly.
- Run locally with one documented command and be accessible through a public portfolio deployment.

### 5.2 Explicit non-goals

- Scientific fire-spread prediction
- Real emergency dispatch, notifications, or public warnings
- Authentication, authorization, or multiple organizations
- Mobile-native applications
- Chatbots or generative-AI recommendations
- Kafka, Kubernetes, a service mesh, or independently deployed microservices
- Nationwide road-graph routing
- Long-term data-lake or warehouse infrastructure
- Automated decisions without human approval

These exclusions protect the eight-to-ten-week schedule and keep attention on one complete, defensible workflow.

## 6. Data sources and geographic scope

### 6.1 Geographic boundary

The MVP covers the 2024 Park Fire region in Northern California, using a fixed regional bounding box that includes affected portions of Butte and Tehama counties plus a modest routing buffer. Every geospatial query and road-graph build is constrained to this boundary.

### 6.2 External sources

| Source | Use | Mode |
|---|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/usfs/active_fire/) | Satellite fire detections, confidence, intensity, and observation time | Live and archived replay |
| [National Weather Service API](https://www.weather.gov/documentation/services-web-api) | Live forecasts, observations, and alerts | Live |
| [NOAA historical observations](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database) | Historical wind observations near the replay region | Archived replay |
| OpenStreetMap regional extract | Roads, hospitals, fire stations, shelters, and other facilities | Versioned static snapshot |
| U.S. Census data | Population estimates for exposed communities | Versioned static snapshot |

Simulated resource data includes a small inventory of crews and response vehicles with typed capabilities, bases, availability, and capacity. The UI and documentation must distinguish simulated resource inventory from real observations.

### 6.3 Provenance and freshness

Each external observation stores:

- `source_name`
- `source_record_id` or deterministic content hash
- `observed_at`, represented by a timezone-aware `datetime` whose UTC offset is
  exactly zero; missing or nonzero offsets are rejected at the domain boundary
- `ingested_at`
- `source_version` when available
- `raw_payload`, represented in the domain as `FrozenJsonObject` with recursive
  `FrozenJsonValue` content: string-keyed read-only mappings, tuples for JSON
  sequences, and immutable JSON scalar values
- validation status
- freshness status derived from source-specific thresholds

Source adapters must never silently invent missing measurements. Missing values remain null, fail validation when required, or reduce the confidence contribution to a risk score.

Observation construction defensively copies and recursively freezes source payloads, so
later mutation of caller-owned mappings or sequences cannot change observed reality.
Unsupported non-JSON values fail validation. Persistence adapters materialize plain JSON
containers only at the serialization boundary.

## 7. System architecture

WildfireOps uses a modular monolith: one Python codebase with explicit internal modules and two runtime process types, plus a separate frontend.

### 7.1 Runtime components

1. **React/TypeScript frontend**
   - Vite-based single-page application
   - MapLibre GL JS map
   - Incident queue, timeline, layers, scenario editor, comparison view, recommendation panel, and audit view
   - Server-sent events for low-complexity live refresh

2. **FastAPI application**
   - Read APIs for incidents, observations, assets, resources, scenarios, recommendations, and audit history
   - Command APIs for scenario creation, optimization, and operator decisions
   - Pydantic validation and stable error responses
   - No ingestion logic inside HTTP route handlers

3. **Python ingestion worker**
   - Scheduled source polling
   - Source-specific validation and normalization
   - Idempotent database writes
   - Incident clustering and exposure refresh after successful ingestion
   - Replay import from versioned local fixtures

4. **Decision engine**
   - Risk scoring
   - Road-graph routing
   - Scenario overlay application
   - Constraint-based resource allocation
   - Recommendation explanation and versioning

5. **PostgreSQL with PostGIS**
   - Operational source of truth
   - Spatial indexes and geospatial joins
   - Observations, domain objects, scenarios, recommendations, decisions, and audit events

The API and ingestion worker import the same domain and persistence modules. They are separate processes for operational clarity, not separate services with remote interfaces.

### 7.2 Internal module boundaries

| Module | Responsibility | May depend on |
|---|---|---|
| `sources` | External clients, raw schemas, validation, and normalization | Configuration and shared types |
| `ingestion` | Idempotent ingestion orchestration and replay loading | `sources`, `domain`, `persistence` |
| `domain` | Domain objects, rules, and invariants | Shared types only |
| `geospatial` | Clustering, exposure queries, and road graph | `domain`, geospatial libraries |
| `decision` | Risk scoring, scenarios, routing, allocation, explanations | `domain`, `geospatial` |
| `persistence` | SQLAlchemy models, repositories, transactions, and migrations | `domain` |
| `api` | HTTP/SSE transport and request/response mapping | Application services, not database models directly |

These boundaries make each unit independently understandable and testable while avoiding speculative distributed infrastructure.

## 8. Operational domain model

### 8.1 Observed reality

- **WildfireIncident:** an operational grouping of recent fire detections, with an approximate geometry, severity state, and last-observed time.
- **FireDetection:** a sourced satellite observation with point geometry, confidence, intensity attributes, and timestamps.
- **ExposedAsset:** a community, hospital, shelter, road segment, or other facility relevant to an incident.
- **ResourceUnit:** a simulated crew or vehicle with a type, base, capacity, availability, and status.

An incident contains detections, threatens exposed assets, and may receive resource assignments.

### 8.2 Scenario branch

- **Scenario:** an immutable branch from an incident state, with an author, creation time, objective, and algorithm-configuration version.
- **WeatherOverride:** a changed wind direction, speed, or forecast horizon.
- **RoadConstraint:** a closed road segment, reduced capacity, or reopening time.
- **ResourceOverride:** an unavailable resource, added capacity, or delayed availability.

A scenario reads observed reality through a pinned snapshot and applies overlays during computation. It never overwrites an observation or a previously evaluated scenario.

### 8.3 Decision record

- **Recommendation:** proposed assignments, routes, score, constraints, uncovered demand, explanation, and algorithm version.
- **DecisionAction:** operator approval, rejection, or edit plus a required note and timestamp.
- **ResourceAssignment:** a resource, destination, route, estimated travel time, and lifecycle status.
- **AuditEvent:** append-only actor, event type, before/after references, relevant inputs, and timestamp.

### 8.4 Domain invariants

- Observed reality cannot be edited through a scenario.
- A recommendation belongs to exactly one scenario snapshot and one algorithm version.
- A recommendation cannot be approved if its scenario or relevant source state has changed since computation; the operator must recompute it.
- An unavailable resource cannot appear in an assignment.
- A resource cannot have more than one overlapping active assignment.
- A route cannot traverse a road closed in the scenario.
- Capacity and compatibility constraints cannot be exceeded.
- Every decision creates an append-only audit event.

## 9. Algorithms

### 9.1 Incident clustering

Recent detections are grouped with a spatiotemporal DBSCAN pass. Spatial distance and observation-time distance are normalized separately before clustering. Configuration stores the spatial radius, temporal window, minimum points, and algorithm version. The defaults are tuned against the replay dataset and documented as operational grouping heuristics, not fire-perimeter estimates.

Clustering must be deterministic for the same ordered input and configuration. A stable incident identity is derived by matching new clusters to existing incident geometries and recent members rather than creating unrelated incident records on every run.

### 9.2 Exposure analysis

PostGIS spatial queries find communities and facilities within a configurable buffer of an incident geometry. Roads intersecting the incident buffer or scenario closure geometry are flagged for routing analysis. Exposure results record the incident snapshot, spatial parameters, and data versions used.

### 9.3 Explainable risk score

The risk score is a versioned, deterministic weighted sum of normalized factors:

- fire proximity
- exposed population
- exposed critical facilities
- wind alignment and speed
- detection confidence
- source freshness

The initial weights are product heuristics selected for demonstration and stored in configuration. The UI displays each factor's raw value, normalized value, weight, and contribution. The score must never be described as a scientific probability or official severity rating.

### 9.4 Routing

A versioned OpenStreetMap extract produces a bounded directed road graph. Edge weights represent estimated travel time based on road class, length, and available speed metadata. A scenario applies road closures by removing or disabling affected edges before running shortest-path calculations.

Routes are cached by graph version, scenario-constraint hash, origin, and destination. If no route exists, the destination remains explicitly unreachable and is passed to the optimizer as infeasible for that resource.

### 9.5 Resource allocation

OR-Tools CP-SAT solves a small binary assignment problem. A decision variable represents assigning an available compatible resource to an exposed destination. Constraints enforce:

- at most one active destination per resource
- resource availability
- resource and destination compatibility
- capacity limits
- route reachability
- configurable maximum response time

The objective minimizes travel-time cost plus a penalty for uncovered weighted risk. The output includes selected assignments, unassigned resources, uncovered destinations, objective components, binding constraints, runtime, solver status, and algorithm version.

If the model is infeasible or no assignment improves the baseline, the system returns that result directly. It does not fabricate a partial success. A separately labeled diagnostic may explain which constraints prevented coverage.

## 10. End-to-end data flows

### 10.1 Live observation flow

1. The ingestion worker polls a source with bounded retry and timeout policies.
2. The source adapter validates and normalizes each record.
3. Invalid records enter a quarantine table with a reason and raw-record reference.
4. Valid records are upserted using source identity or deterministic hash.
5. The worker clusters current detections and refreshes spatial exposure.
6. Updated incident identifiers are emitted through the API's server-sent-event channel.
7. The frontend refetches the affected incident while retaining the last known view if the refresh fails.

### 10.2 Scenario and decision flow

1. The operator creates a scenario from a pinned incident snapshot.
2. The operator adds weather, road, or resource overrides.
3. The API validates the scenario and stores an immutable version.
4. The decision engine recalculates risk, routing, and allocation.
5. It stores a versioned recommendation with inputs and explanations.
6. The UI compares baseline and scenario outcomes.
7. The operator approves, rejects, or edits the recommendation with a note.
8. A single database transaction records the decision, resulting assignments when approved, and the audit event.

### 10.3 Replay flow

Replay packages contain versioned normalized observations, source metadata, expected timestamps, and a manifest. The replay clock advances independently from wall time. Replaying the same package with the same configuration must yield the same incident groupings, risk values, routes, and recommendation outputs.

## 11. API behavior

The API uses resource-oriented reads and explicit command endpoints for state transitions. Representative routes are:

- `GET /incidents`
- `GET /incidents/{incident_id}`
- `GET /incidents/{incident_id}/timeline`
- `GET /sources/status`
- `POST /incidents/{incident_id}/scenarios`
- `POST /scenarios/{scenario_id}/versions`
- `POST /scenario-versions/{version_id}/recommendations`
- `POST /recommendations/{recommendation_id}/decisions`
- `GET /audit-events`
- `GET /events` for server-sent updates

Command requests accept an idempotency key. Validation failures return field-level `422` responses. State conflicts, including approving a stale recommendation, return `409`. Missing resources return `404`. Upstream-source failures do not make read endpoints fail when previously ingested data is available; reads return the data with freshness metadata.

## 12. Operator experience

The desktop interface has three primary regions:

1. **Incident queue:** ordered by explainable risk with severity, exposed locations, and freshness summaries.
2. **Map and time surface:** fire detections, incident geometry, exposed assets, resources, routes, scenario changes, and replay controls.
3. **Decision workspace:** factor breakdown, scenario controls, baseline comparison, recommendation, uncovered demand, and approve/reject/edit actions.

The map supplies geographic context but does not hide the decision workflow. Selecting an incident updates the map and decision workspace. Every risk value and recommendation has a visible explanation path. Stale data, simulated data, unreachable locations, and infeasible results use text and icons in addition to color.

The MVP is optimized for a laptop-sized desktop viewport. Responsive behavior may stack the decision workspace below the map, but mobile-specific workflows are out of scope.

## 13. Error handling and degraded operation

### 13.1 Source failures

- Apply bounded exponential backoff with jitter and explicit timeouts.
- Retain the last successfully ingested observations.
- Mark data stale using source-specific thresholds.
- Display the last success, next retry, and affected capabilities.
- Quarantine malformed records and expose aggregate quarantine counts to the operator.

### 13.2 Idempotency and transactions

- Source records use unique source identity or content hashes.
- Repeated ingestion cannot duplicate observations.
- Scenario creation and decision commands accept idempotency keys.
- Decision, assignment, and audit writes occur in one transaction.

### 13.3 Decision-engine failures

- Invalid scenario overrides fail before computation with field-level errors.
- Unreachable locations remain visible with a reason.
- Timeouts return solver status and preserve diagnostic data.
- Infeasible allocation returns uncovered destinations and conflicting constraints.
- The previous valid recommendation remains readable but cannot be represented as the result of the new scenario.

### 13.4 Replay fallback

The public demonstration provides a prominent switch to the bundled replay. The replay does not depend on live APIs, so the complete workflow remains available during source outages or after external schemas change.

## 14. Testing strategy

### 14.1 Unit and property tests

- Risk-factor normalization, weighting, and explanation totals
- Scenario overlay behavior and immutability
- Source validation and deterministic identity generation
- Cluster determinism for identical data and configuration
- Optimizer invariants using property-based generated inputs
- Road closures never appearing in returned routes
- Unavailable resources and exceeded capacities never appearing in recommendations

### 14.2 Integration tests

- PostGIS spatial joins and indexes against a containerized test database
- Idempotent ingestion using recorded NASA and weather fixtures
- Quarantine behavior for malformed fixtures
- Scenario, recommendation, decision, and audit transaction boundaries
- Stable API error contracts

### 14.3 End-to-end tests

Playwright covers one critical operator journey:

1. load the replay
2. select an incident
3. create a road-closure scenario
4. generate a recommendation
5. compare it with baseline
6. approve it with a note
7. verify the corresponding audit event

### 14.4 Golden replay

The versioned Park Fire replay is a golden test. Expected incident memberships, risk-factor outputs, unreachable-road cases, solver status, and key recommendation properties are stored with the fixture manifest. Exact route geometry is asserted only when the graph version is pinned.

### 14.5 Performance tests

Before finalizing resume claims, benchmark and publish:

- ingestion throughput for the complete replay package
- p50 and p95 selected-incident query latency
- scenario routing time
- optimizer runtime by number of resources and destinations
- browser time to interactive for the deployed replay

The initial engineering targets are a p95 selected-incident response below 500 ms and a recommendation below two seconds for 20 resources and 50 destinations on the documented benchmark machine. These are acceptance targets, not resume claims until measurements confirm them.

## 15. Observability

The backend emits structured logs containing request or job identifiers, source names, scenario IDs, recommendation IDs, durations, and outcome status without logging secrets or unnecessary raw payloads.

Operational metrics include:

- last successful ingestion and source freshness
- records accepted, deduplicated, and quarantined
- clustering and exposure-refresh duration
- API latency and error counts
- routing and optimizer runtime
- solver result counts by status

A small source-status view in the application is sufficient. A full observability platform is not required for the MVP.

## 16. Deployment and developer experience

Local development uses Docker Compose to start PostgreSQL/PostGIS, the API, ingestion worker, and frontend through one documented command. Separate component commands remain available for debugging. A seeded replay command loads the complete demonstration state.

The public deployment consists of:

- a static React frontend
- a containerized FastAPI application and ingestion worker
- managed PostgreSQL with PostGIS
- scheduled ingestion with secrets supplied through environment variables

The repository must include:

- a concise top-level README
- architecture and data-flow diagrams
- source and safety disclaimers
- setup and replay commands
- testing and benchmark instructions
- screenshots and a short demo video link
- a trade-off section explaining the modular monolith, deterministic risk score, replay-first demo, simulated resources, and omitted infrastructure

## 17. Security, privacy, and safety

- No personal data is required or stored.
- API keys and database credentials remain in environment variables and never enter fixtures, logs, or the repository.
- External payloads are treated as untrusted input and validated before persistence.
- Command inputs are bounded to prevent excessive scenario size or solver work.
- The deployed application is read-only with respect to external systems; actions affect only the portfolio database.
- Every screen showing risk or recommendations states that the system is a portfolio simulation and not for emergency use.

## 18. Completion criteria

WildfireOps is complete when all of the following are true:

- The three-minute demonstration narrative works on the public deployment.
- Replay mode works without external-network access after images and dependencies are installed.
- At least NASA FIRMS, NOAA/NWS, OpenStreetMap, and Census-derived data are represented with provenance.
- Baseline and modified scenarios produce explainable, reproducible comparisons.
- Operator approval, rejection, editing, and audit history work end to end.
- Stale-source, malformed-record, unreachable-route, and infeasible-allocation behavior are demonstrated and tested.
- Critical unit, property, integration, golden-replay, and Playwright tests pass.
- Performance results are measured and documented on a named dataset and machine.
- One documented local startup path succeeds from a fresh clone.
- The README, diagrams, screenshots, trade-offs, safety statement, and demo video are present.

## 19. Resume and interview presentation

Resume bullets must use measured quantities from the completed system rather than estimates. A strong final bullet should identify:

- the number of ingested or processed observations
- the number and type of integrated data sources
- measured geospatial query or recommendation latency
- the implemented decision workflow
- one reliability or correctness property

During interviews, the candidate should be ready to explain:

- why the project uses a modular monolith instead of microservices
- how ingestion remains idempotent
- how incident identity survives reclustering
- why the risk score is explainable and explicitly non-scientific
- how scenario isolation prevents accidental mutation
- how routing closures and optimizer constraints interact
- what happens during source and solver failure
- which performance bottleneck appeared first and how measurement guided the response

This explanation is as important as the deployed interface. The project succeeds when it provides evidence of engineering judgment, not when it merely contains many technologies.
