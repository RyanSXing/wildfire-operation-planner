# Park Fire Decision Exercise and User-Facing Rebuild

**Status:** Approved for implementation planning

**Date:** 2026-07-24

**Scope:** Local-first exercise engine, curated Park Fire decision exercise, and complete desktop user-facing rebuild

## 1. Purpose

WildfireOps will replace its underpowered showcase flow with a historically anchored, deliberately designed decision exercise that demonstrates full-stack product judgment, backend reliability, data integration, constrained optimization, and human-in-the-loop decision making.

The existing demonstration is technically sound but visually and operationally weak. It exposes one usable incident snapshot, one threatened community, one effective assignment, and a road closure that reduces the recommendation to no assignments. The replay package spans several hours and contains many observations, but the seeded application does not expose a meaningful temporal story.

The new flagship experience is the **Park Fire Decision Exercise**. It uses real historical fire observations, weather, geography, communities, public facilities, and roads while adding clearly labeled simulated operational tasks, resources, disruptions, and field reports. It must never imply that the exercise recreates actual emergency decisions or recommends what responders should have done.

The primary audience is anyone who could help the project owner obtain a full-stack, backend/platform, or data/forward-deployed engineering role. A recruiter must understand the product story within three minutes, while an engineer must be able to inspect the data lineage, constraints, algorithms, failure handling, and audit evidence.

## 2. Product decisions

The approved direction is:

- one guided three-minute flagship exercise followed by optional bounded exploration;
- three meaningful visitor decisions;
- the main Park Fire plus a simulated spot fire competing for one shared resource pool;
- real communities and public facilities with simulated exercise demand and exposure;
- task-based planning for communities, a hospital, an evacuation shelter, a communications site, a power substation, and a blocked corridor;
- simulated engines, evacuation buses, medical teams, and one road-clearing crew;
- objective presets rather than numeric model tuning;
- a cascading wind shift, spot fire, and corridor closure;
- a final human override prompted by a shelter-capacity field report;
- deterministic plain-language explanations with expandable technical evidence;
- three curated time checkpoints with free timeline exploration after completion;
- isolated temporary exercise sessions;
- desktop-only interaction;
- a secondary Live Monitor workspace;
- local execution first, with hosting designed separately later; and
- a complete rebuild of the current user-facing frontend by Claude Code after the backend experience contract is stable.

## 3. Goals

The work must:

- create a memorable but credible decision narrative;
- make both incidents genuinely compete in one optimization model;
- make resource capabilities, capacity, reachability, deadlines, and scarcity materially affect results;
- demonstrate how changing data invalidates a previously reasonable plan;
- preserve the distinction between historical observations, exercise assumptions, computed recommendations, and operator decisions;
- keep every explanation deterministic and traceable to structured evidence;
- preserve human authority through a validated override and required decision note;
- provide an append-only, session-scoped audit receipt;
- keep the guided path understandable without exposing implementation jargon;
- preserve technical evidence for engineering reviewers;
- keep the existing live ingestion and incident-scoped planning capabilities available in a separate workspace;
- work reliably from a documented local startup command; and
- leave a precise implementation contract for the Claude Code frontend rebuild.

## 4. Non-goals

This phase does not include:

- scientific fire-spread prediction;
- a claim that simulated events or recommended actions occurred historically;
- real emergency dispatch or life-safety use;
- a full dispatch scheduling or vehicle-movement simulator;
- continuous resource movement or task-completion timing within a checkpoint;
- authentication, authorization, organizations, or user accounts;
- mobile or tablet interaction;
- generative-AI briefings or explanations;
- arbitrary visitor-created incidents, facilities, or resources;
- a replacement for React, TypeScript, Vite, MapLibre, or TanStack Query without a separately approved dependency proposal;
- public deployment, hosting selection, production session security, or hosted cleanup infrastructure;
- a microservice split, event-sourcing framework, workflow engine, or new frontend framework; or
- unrelated repairs to existing live ingestion.

## 5. Trust and labeling boundaries

### 5.1 Historical foundation

The exercise uses pinned, cited versions of:

- NASA FIRMS fire observations;
- NOAA historical weather observations;
- OpenStreetMap roads and public facilities;
- U.S. Census communities and population data; and
- the bounded Park Fire regional road graph.

Real public facility names and locations may be shown. Their exercise exposure, demand, priority, and recommended assignments are simulated.

### 5.2 Exercise assumptions

The following are explicitly labeled **Exercise assumption** wherever they appear:

- the simulated spot fire;
- resource units, positions, capabilities, and availability;
- operational tasks and deadlines;
- road closure and reopening;
- facility demand and capacity pressure;
- objective presets;
- the shelter field report; and
- all recommendations and operator decisions.

### 5.3 Persistent safety statement

Every exercise and recommendation surface states:

> Portfolio decision exercise only. Historical inputs are combined with simulated operational assumptions. Do not use for emergency or life-safety decisions.

The wording may be shortened in compact surfaces, but the full statement must be available without opening technical evidence.

## 6. End-to-end exercise narrative

### 6.1 Briefing

The application opens on a concise briefing page. It states that the exercise takes approximately three minutes, distinguishes historical inputs from simulated assumptions, generates an exercise callsign, and offers one primary action: **Begin exercise**.

The briefing also exposes a secondary **Live Monitor** link. It is not a conventional portfolio marketing page.

### 6.2 Checkpoint one: initial allocation

The first checkpoint presents the Park Fire and its current tasks. The visitor chooses one planning objective:

- **Fastest response**
- **Protect critical services**
- **Maximize population coverage**

The system runs one shared task plan and presents the result on the map. The visitor can understand which tasks are covered, what remains uncovered, where resources travel, and why the chosen objective produced that plan.

This objective selection is the visitor's first decision.

### 6.3 Checkpoint two: cascading disruption

Time advances through a restrained animated transition. The exercise introduces three connected changes:

1. wind shifts northeast and changes task priority inputs;
2. a simulated spot fire adds new tasks; and
3. a key corridor closes and invalidates one or more candidate routes.

The command center first explains the causal chain in plain language, then shows changed incident, task, route, and assignment states. The visitor may retain or change the objective before rerunning the joint plan.

This response choice is the visitor's second decision.

The accepted checkpoint-two plan determines whether the road-clearing crew is assigned. If it is assigned, the corridor is reopened for checkpoint three. If it is not, the corridor remains closed. This is a bounded cross-checkpoint consequence, not a general scheduling model. All guided objective paths must still leave the final shelter override feasible, although route and outcome trade-offs may differ.

### 6.4 Checkpoint three: human override

A simulated field report states that the evacuation shelter is nearing capacity. The report is new operator context and was not included in the previous planning input.

The visitor redirects one compatible evacuation bus to the shelter. Before accepting the change, the system:

- validates capability, availability, route reachability, capacity, and assignment uniqueness;
- previews the task that loses or changes coverage;
- recalculates outcome metrics; and
- explains the trade-off in plain language.

The visitor may provide an optional display name, must provide a decision note, and approves the final plan.

This validated override and approval are the visitor's third decision.

### 6.5 Debrief

The exercise ends on a debrief containing:

- the generated callsign and optional display name;
- all three visitor decisions;
- baseline, disrupted, and final outcomes;
- covered and uncovered tasks;
- routes and material constraints;
- the field-report override and its trade-off;
- algorithm, graph, source, exercise-definition, and planning-input versions;
- the append-only audit receipt; and
- links to **Open sandbox**, **Engineering details**, **Restart exercise**, and **Live Monitor**.

Reloading the debrief restores the same session.

## 7. Bounded sandbox

After completing the guided exercise, the visitor may create a sandbox branch from a checkpoint. The sandbox exposes only validated controls already supported by the exercise definition:

- objective preset;
- known road closures and reopenings;
- defined wind presets;
- resource availability;
- task priority presets; and
- locked resource-to-task assignments.

Visitors cannot draw arbitrary incidents, create facilities, upload data, add resources, or edit raw model weights.

Sandbox results use the same planner, explanations, and evidence as the guided exercise. Invalid combinations fail before computation with field-level errors. The guided audit remains unchanged.

## 8. Information architecture

The rebuilt frontend contains these primary destinations:

1. **Exercise briefing**
2. **Exercise command center**
3. **Exercise debrief**
4. **Bounded sandbox**
5. **Engineering details**
6. **Live Monitor**

The critical guided path is Briefing → Plan → Disruption → Override → Debrief.

Live Monitor remains a separate secondary workspace. Historical and exercise state must never be blended with live incident state in one planning session.

## 9. Command-center interface

### 9.1 Visual language

The approved direction is **Restrained Operations**:

- deep navy application chrome;
- a quiet spatial grid;
- disciplined cyan, amber, and red status semantics;
- compact but readable operational typography;
- limited motion;
- strong plain-language hierarchy; and
- no military styling, faux classified language, game-like scoring, or sensational fire imagery.

### 9.2 Desktop layout

The minimum supported interaction viewport is 1280×720.

The command center contains:

1. a top bar with product identity, exercise checkpoint, historical-plus-simulated disclosure, source status, and callsign;
2. a left rail for incidents, tasks, objective, and checkpoint progress;
3. a permanent map canvas as the primary workspace;
4. a right causal-briefing panel for changed conditions and affected plan elements;
5. a bottom decision dock for outcome summary and the next primary action; and
6. an optional evidence drawer for routes, objective components, constraints, provenance, versions, and raw identifiers.

The guided workflow must fit at 1280×720 without page-level scrolling. Evidence drawers and long lists may scroll internally.

### 9.3 Visual semantics

The interface visually distinguishes:

- historical observations;
- simulated exercise assumptions;
- draft visitor choices;
- computed recommendations;
- unreachable or uncovered tasks;
- accepted operator overrides; and
- stale results from an earlier checkpoint or objective.

No distinction relies on color alone. Labels, icons, line styles, and text accompany status colors.

### 9.4 Map behavior

The map shows:

- both incident areas;
- historical fire detections;
- communities and public facilities;
- simulated resources;
- task destinations;
- candidate and selected routes;
- corridor closures and reopening;
- draft override connections; and
- covered, uncovered, incompatible, and unreachable task states.

Checkpoint transitions animate only the differences. Reduced-motion mode renders the final state immediately.

### 9.5 Plain language before evidence

Every main result answers:

1. What changed?
2. What did the system recommend?
3. What remains uncovered?
4. Why did the plan change?
5. What decision is required now?

Raw IDs, solver terms, weight values, source payloads, and detailed constraints remain available under Engineering Details or the evidence drawer.

## 10. Architecture

### 10.1 Approved boundary

The system adds a dedicated exercise orchestration workflow beside the existing incident-scoped live workflow.

The exercise workflow owns:

- versioned exercise-definition loading;
- temporary session lifecycle;
- checkpoint materialization;
- joint task planning;
- deterministic change explanation;
- override validation;
- exercise decisions;
- exercise events; and
- debrief projection.

It reuses existing:

- replay-package validation patterns;
- historical observation and static-data parsing;
- road-graph routing;
- risk primitives where their meaning remains valid;
- resource domain validation;
- CP-SAT configuration and deterministic conventions;
- idempotency conventions;
- API error conventions; and
- persistence transaction patterns.

The existing incident-scoped scenarios, recommendations, decisions, and Live Monitor APIs remain intact.

### 10.2 Why the exercise is separate

Current scenarios, scenario versions, recommendations, decisions, and audit events are structurally tied to one incident snapshot. Generalizing the entire live domain to operational areas would require broad schema and API migrations for a use case currently needed only by the exercise.

A dedicated exercise workflow provides real cross-incident optimization without destabilizing live behavior or pretending temporary visitor sessions are observed operational state.

### 10.3 Runtime shape

The exercise remains inside the existing FastAPI modular monolith and PostgreSQL database. It is not a new service or process.

## 11. Exercise definition

An immutable, versioned exercise definition lives beside the replay package. It references pinned historical identities rather than copying historical observations.

The definition contains:

- exercise ID, version, name, and description;
- replay package and graph versions;
- supported objective presets;
- resource inventory;
- three ordered checkpoints;
- incident and asset references for each checkpoint;
- task definitions;
- simulated disruptions and field reports;
- permitted sandbox controls;
- cross-checkpoint consequences;
- expected disclosure text; and
- validation metadata.

### 11.1 Startup validation

Startup fails before serving the exercise if:

- referenced historical IDs do not exist;
- task, resource, checkpoint, or disruption IDs are duplicated;
- task capabilities are unknown;
- capacities or deadlines are invalid;
- resources or tasks fall outside the pinned graph region;
- required route endpoints cannot be snapped;
- checkpoints are not strictly time ordered;
- a simulated field lacks an exercise label;
- an objective preset is missing;
- the final guided override cannot be valid for every guided objective path; or
- the definition and replay package versions disagree.

Errors identify the file, field path, and invalid identity or value.

### 11.2 Fixture counts

The exact public facility identities are fixture data, not design constants. The fixture must include at least one real public facility for every approved asset class where a cited source provides one.

The curated resource pool contains a small, scarce mix of:

- fire engines;
- evacuation buses;
- a medical team or teams; and
- one road-clearing crew.

Checkpoint two contains more tasks, or tasks with greater combined demand, than the resource pool can fully satisfy, ensuring a visible trade-off. Illustrative mockup counts are not golden-output requirements.

## 12. Task domain

A task is operational demand associated with an incident and destination. It contains:

- stable task ID;
- incident ID;
- asset ID;
- task type;
- required capability;
- required capacity;
- response deadline;
- priority inputs, including affected population and critical-service status where applicable;
- geographic destination;
- historical and exercise source references; and
- simulation label.

Tasks may require multiple resources to satisfy capacity. One resource may receive at most one current task within a checkpoint.

The initial task set covers the approved operational categories:

- community evacuation;
- hospital support;
- shelter transport;
- communications protection;
- power-substation protection; and
- corridor clearing.

The specific task mix changes by checkpoint and incident.

## 13. Joint task planner

### 13.1 Planning input

Each plan run stores one canonical, hashed input containing:

- exercise and checkpoint versions;
- both incident states;
- all current tasks;
- resource state;
- candidate routes;
- road state;
- selected objective;
- locked assignments;
- cross-checkpoint consequences;
- source and graph versions; and
- algorithm configuration versions.

### 13.2 Solver boundary

A new `solve_task_plan` operation reuses the current deterministic OR-Tools CP-SAT conventions without changing the existing `solve_allocation` contract used by Live Monitor.

Shared helpers are extracted only when both solvers genuinely use them. No generic optimization framework is introduced.

### 13.3 Constraints

The task planner enforces:

- one current task per resource;
- resource availability;
- resource capability compatibility;
- capacity requirements;
- route reachability;
- response deadlines;
- pinned graph and closure state;
- multiple-resource coverage where required;
- locked visitor assignments; and
- assignment uniqueness.

Uncovered demand is allowed and must remain explicit. Infeasibility caused by real constraints is a valid planning outcome, not an exception.

### 13.4 Objectives

All objective coefficients are integers and versioned.

The presets adjust uncovered-task penalties:

- **Fastest response** places greater emphasis on travel cost.
- **Protect critical services** increases penalties for hospital and communications tasks.
- **Maximize population coverage** increases penalties using affected population.

Presets do not bypass compatibility, reachability, deadline, capacity, or validation constraints.

The curated dataset must produce materially different valid assignments for the presets at one or more checkpoints.

### 13.5 Determinism

The planner uses:

- canonical input ordering;
- stable variable names and tie-breaking;
- one solver worker;
- a fixed random seed;
- integer objective coefficients;
- a two-second solver limit; and
- versioned algorithm and objective configuration.

Identical inputs must produce identical semantic outputs.

### 13.6 Planning output

Every result includes:

- assignment per selected resource;
- route and travel time;
- covered and uncovered tasks;
- unassigned resources;
- incompatible, unavailable, late, and unreachable candidates;
- capacity supplied and required;
- objective components;
- binding constraints;
- solver status and runtime;
- input, graph, source, risk, exercise, and algorithm versions; and
- deterministic explanations.

## 14. Deterministic explanation

No LLM participates in the exercise.

Explanations are generated from structured input and result differences. Rules cover:

- task added or removed;
- task priority changed;
- route invalidated by closure;
- route restored by prior corridor clearing;
- resource unavailable;
- capability mismatch;
- insufficient capacity;
- deadline exceeded;
- objective change causing reassignment;
- task left uncovered because a resource served a higher-penalty task;
- locked assignment constraining the remaining plan; and
- operator override changing coverage or travel.

The main interface converts these facts into short operational sentences. Engineering Details exposes the underlying identifiers, values, and rule codes.

An explanation may never claim causality that is absent from the stored planning inputs or output difference.

## 15. Exercise sessions and persistence

Exercise definitions remain files. Local persistence adds three concepts.

### 15.1 Exercise session

An exercise session stores:

- session ID;
- exercise ID and definition version;
- generated callsign;
- optional display name;
- current checkpoint;
- selected objective;
- status;
- monotonic session version;
- creation and update times; and
- expiry.

Session status is limited to `active`, `completed`, and `expired`. Checkpoint position and the backend-provided allowed actions describe progress inside an active session; no general workflow-state vocabulary is introduced.

### 15.2 Plan run

A plan run is immutable and stores:

- session and checkpoint;
- planning input and hash;
- planning output;
- algorithm and data versions;
- idempotency claim;
- creation time; and
- relationship to the previous plan where applicable.

### 15.3 Exercise event

Exercise events are append-only and record:

- session;
- event type;
- actor callsign and optional display name;
- expected and resulting session versions;
- before and after references;
- command inputs;
- relevant plan IDs;
- note where required; and
- timestamp.

Events include objective selection, plan generation, checkpoint acceptance, override, and final approval.

### 15.4 Isolation and expiry

One session cannot read or mutate another session through exercise-scoped APIs. Reloading restores the same session.

For local use, the opaque session ID scopes data but is not described as an authentication boundary. Public deployment must separately design signed or secret session credentials, cleanup, and retention.

Local sessions expire 24 hours after creation. Expired sessions become read-only and return a start-new-exercise action. Hosted retention and cleanup may change this duration in the later deployment design.

## 16. API shape

The API provides:

- exercise metadata;
- session creation;
- current session projection;
- objective selection;
- plan generation;
- checkpoint advancement;
- override submission;
- final decision submission;
- audit events; and
- debrief projection.

Representative routes are:

- `GET /api/exercises`
- `GET /api/exercises/{exercise_id}`
- `POST /api/exercises/{exercise_id}/sessions`
- `GET /api/exercise-sessions/{session_id}`
- `POST /api/exercise-sessions/{session_id}/objective`
- `POST /api/exercise-sessions/{session_id}/plans`
- `POST /api/exercise-sessions/{session_id}/advance`
- `POST /api/exercise-sessions/{session_id}/overrides`
- `POST /api/exercise-sessions/{session_id}/decisions`
- `GET /api/exercise-sessions/{session_id}/audit`
- `GET /api/exercise-sessions/{session_id}/debrief`

Every mutation requires:

- an `Idempotency-Key` header; and
- the caller's expected session version.

The current session projection includes allowed next actions so the frontend does not duplicate transition rules.

## 17. Error and recovery behavior

- Invalid exercise definitions fail startup with an exact file and field path.
- Reused idempotency keys with identical requests replay the original response.
- Reused keys with different requests return a conflict.
- Stale or out-of-order commands return `409` with current session state and allowed actions.
- Invalid overrides return field-level validation errors and do not change the stored plan.
- Unreachable routes, incompatible resources, missed deadlines, and insufficient capacity produce explicit uncovered tasks.
- Solver `UNKNOWN` or an internal planning failure leaves the last valid plan readable and permits retry.
- A failed plan cannot be accepted or advanced.
- An expired session returns `410` with **Start new exercise**.
- A missing historical source or graph version makes the exercise unavailable rather than silently substituting current data.
- Technical-evidence failures do not hide the plain-language plan already stored.

## 18. Claude Code frontend rebuild contract

### 18.1 Sequence

The exercise engine, definition, session projection, and API contracts are implemented and proven before the full frontend rebuild begins. Claude Code receives the approved specification and stable example responses.

### 18.2 Disposable frontend surface

Claude Code may replace:

- every current user-facing React component;
- all layouts and styles;
- navigation and information architecture;
- interaction composition;
- user-facing copy; and
- frontend tests that assert obsolete behavior.

This is a coherent rebuild, not an incremental reskin of the current dashboard.

### 18.3 Preserved defaults

Claude Code preserves by default:

- React;
- TypeScript;
- Vite;
- MapLibre;
- TanStack Query;
- approved backend API contracts;
- approved domain language;
- accessibility requirements; and
- observed, assumed, computed, and decided state distinctions.

Claude Code may propose replacing one frontend dependency only when it identifies a concrete blocker or material benefit. A wholesale stack migration requires explicit approval.

### 18.4 Required frontend states

The rebuild handles:

- initial loading;
- exercise unavailable;
- session creation;
- restored session;
- every checkpoint and decision state;
- plan running;
- plan ready;
- stale plan;
- retryable solver failure;
- unreachable and uncovered tasks;
- invalid override;
- concurrent or stale command;
- expired session;
- final approval;
- debrief;
- bounded sandbox; and
- Live Monitor loading, empty, stale, and failure states.

### 18.5 Accessibility

The desktop experience provides:

- complete keyboard operation;
- visible focus;
- semantic landmarks and controls;
- text alternatives for map-only information;
- reduced-motion behavior;
- status communication beyond color;
- readable contrast; and
- focus movement and announcements for checkpoint, plan, error, and decision transitions.

## 19. Verification

### 19.1 Fixture and golden behavior

The exercise fixture proves:

- three strictly ordered checkpoints;
- historical and simulated provenance separation;
- two incidents sharing one resource pool;
- all objective presets producing valid plans;
- materially different preset assignments;
- the cascade changing tasks, routes, and assignments;
- road-crew assignment affecting checkpoint three;
- a valid final shelter override for every guided path;
- at least one meaningful uncovered-task trade-off; and
- deterministic semantic outputs.

Golden assertions pin semantic results, identifiers, versions, and causal codes. Exact route geometry is pinned only to the versioned graph.

### 19.2 Backend tests

Focused tests cover:

- exercise-definition validation;
- task capability, capacity, deadline, route, and assignment constraints;
- shared-resource competition;
- deterministic tie-breaking;
- explanation facts matching stored input and result differences;
- session isolation;
- idempotency and expected-version handling;
- expiry;
- invalid override atomicity;
- plan-run immutability; and
- final audit provenance.

The existing optimizer property-testing style is reused for invariant coverage. No second testing framework is added.

### 19.3 Frontend and end-to-end tests

One primary Playwright test proves:

1. begin the exercise;
2. choose an objective;
3. inspect the initial plan;
4. advance through the cascade;
5. replan;
6. inspect causal changes;
7. apply the shelter override;
8. submit the decision note;
9. approve;
10. inspect the audit receipt; and
11. refresh and restore the same debrief.

Additional frontend checks cover state rendering, keyboard behavior, reduced motion, and failure recovery. Obsolete current-interface tests are replaced rather than mechanically preserved.

### 19.4 Visual and performance acceptance

At 1280×720:

- the critical action is visible without page-level scrolling;
- the map remains the dominant surface;
- the decision dock remains visible;
- plain-language outcome and next action precede technical evidence; and
- no required interaction is map-only.

Planning respects the existing two-second solver limit. The complete guided demonstration remains repeatable in approximately three minutes.

## 20. Local completion gate

The local phase is complete only when:

- one documented command starts the database, API, and rebuilt frontend;
- the exercise definition validates and seeds deterministically;
- the complete guided journey passes;
- every objective path reaches a valid final override;
- session restore and isolation work;
- Live Monitor remains available and its existing core behavior is not regressed;
- the audit receipt includes complete provenance;
- the 1280×720 experience passes visual and keyboard review;
- the README explains historical versus simulated data; and
- Engineering Details explains the architectural boundary and trade-offs.

Public hosting, production session security, cleanup, monitoring, screenshots, portfolio copy, and demo video are separate follow-up work after this local completion gate.

## 21. Implementation sequencing

The work is intentionally split into two implementation projects.

### Project 1: Exercise engine and dataset

Deliver:

- versioned exercise definition;
- three-checkpoint historical-plus-simulated fixture;
- task domain;
- joint task planner;
- deterministic explanations;
- exercise sessions, plan runs, and events;
- API and debrief projection;
- golden and integration tests; and
- example API responses for frontend work.

### Project 2: Complete user-facing rebuild

Deliver:

- briefing;
- command center;
- checkpoint transitions;
- objective and replanning interactions;
- override and approval;
- debrief;
- bounded sandbox;
- Engineering Details;
- secondary Live Monitor;
- replacement behavior tests;
- Playwright journey; and
- visual and accessibility verification.

Project 2 begins after Project 1's API contract and fixture outputs are stable. Frontend discovery may occur earlier, but production UI implementation must not invent missing backend states.
