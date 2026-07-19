# WildfireOps Map-First Command Workspace Design

**Status:** Approved for implementation planning

**Date:** 2026-07-18

**Scope:** Interface redesign plus the minimum scenario and routing extensions needed for direct map planning

## 1. Purpose

WildfireOps will evolve from a three-column dashboard into a map-first command workspace. A first-time operator should be able to select the Park Fire, make a reversible planning change directly on the map, run a plan, understand the result visually, and approve or inspect it without scrolling through technical evidence.

The redesign reuses the existing React/TypeScript frontend, MapLibre map, FastAPI APIs, immutable scenario versions, routing and recommendation engines, decision commands, and audit history. It does not introduce a new UI framework, game engine, workflow state machine, or parallel planning backend.

WildfireOps remains a portfolio simulation. The existing warning against emergency or life-safety use remains persistently visible.

## 2. Goals

The redesign must:

- make the tactical map the permanent primary workspace;
- make the first useful action obvious within the first viewport;
- let operators draft road, weather, availability, relocation, and assignment changes directly on the map;
- keep every draft local and reversible until the operator deliberately runs it;
- preserve observed baseline data and immutable scenario history;
- preserve manual assignments while optimizing the remaining resources;
- present recommendations primarily as routes and coverage changes, with a concise plain-language summary;
- keep technical evidence available without putting it in the main workflow;
- retain keyboard-accessible list and form equivalents for every map action; and
- complete the critical workflow at 1280×720 and 1024×768 without scrolling through evidence lists.

## 3. Non-goals

This redesign does not include:

- mobile interaction parity;
- persistent relocation of observed resources;
- scientific fire-spread prediction or invented severity categories;
- deployment, hosting, CI, or portfolio-documentation work;
- repair of the temporal replay dataset or replay clock;
- a new component library, map engine, global state framework, or workflow state machine; or
- changes to the existing safety boundary, authentication scope, or external systems.

If temporal replay remains unavailable, the interface continues to explain that a usable range requires at least two time-ordered snapshots. Replay repair is a separate project.

### 3.1 Relationship to unfinished original work

Excluding work from this redesign does not mark it complete or remove it from the WildfireOps roadmap. The original specification still has these open items:

- the Park Fire package does not produce a usable multi-snapshot temporal replay;
- the existing Playwright demonstration predates the collapsed evidence workflow and currently fails;
- dedicated degraded-mode tests and repeatable performance benchmarks are absent;
- CI, the production image, deployment configuration, public deployment, screenshots, architecture documentation, benchmark report, and demo video are absent;
- the top-level README remains a minimal local-startup document; and
- the completed basemap and first-time-workflow changes are still uncommitted and unmerged.

These items are tracked by the sequencing and completion gates in Section 17. The map-first redesign cannot be described as portfolio-ready merely because its own interface acceptance tests pass.

## 4. Experience principles

### 4.1 Map first

The map is not a supporting visualization. It is the surface where operators select incidents, resources, assets, and roads; preview assumptions; and inspect recommended routes and coverage.

### 4.2 Draft before write

Map gestures and command-dock controls modify one local `planningDraft`. They do not call scenario or decision APIs. The dock always distinguishes observed data, draft assumptions, and computed results.

### 4.3 Operational meaning before implementation detail

Operational surfaces use names such as “Park Fire,” “Engine — Butte Meadows,” and “Butte Meadows CDP.” Raw UUIDs, graph edge IDs, source payloads, model weights, and solver configuration appear only in audit or technical evidence.

The existing risk value is labeled **Priority score** and paired with its top contributing factor. The product does not describe the score as a scientific severity category or probability.

### 4.4 Human decision remains explicit

Running a plan produces a recommendation, not an automatic action. Approval, rejection, or editing still requires the existing decision flow and operator note. The existing append-only audit path remains authoritative.

## 5. Responsive layout

### 5.1 Desktop command center at 1024px and above

The primary layout contains:

1. **Tactical map canvas:** fills the available workspace below the top bar.
2. **Incident rail:** a compact collapsible rail on the left containing only incident choices and their short operational summaries.
3. **Selected-object card:** a contextual floating card for the selected incident, resource, exposed asset, road, or route.
4. **Map controls:** zoom, layer visibility, selection mode, and existing attribution.
5. **Command dock:** a bottom dock containing the active planning tool, draft summary, Undo, Clear draft, and Run plan.
6. **Details & evidence drawer:** an optional drawer containing full lists, forms, recommendation tables, decisions, audit, and technical evidence.

The top bar keeps the product name, persistent safety statement, selected incident label, freshness summary, and an Audit entry point. Dark tactical chrome surrounds a readable daylight basemap. Cyan is reserved for routes and active controls; fire red/orange marks fire observations; draft assumptions use amber; errors and unreachable paths use red plus text and line style.

### 5.2 Smaller-screen fallback

Below 1024px, the same information becomes a simplified stacked experience: incident list, map, command controls, result summary, and optional details. Direct drag interaction is not required for parity on small screens; the list and form equivalents remain complete. This is a responsive fallback, not a mobile-specific workflow.

## 6. Core interaction flow

### 6.1 Observe

On load, the highest-priority incident remains selected using the existing selection behavior. In the replay, this selects Park Fire. Activating Park Fire from the rail or map reselects and recenters it. Selecting any map object updates the contextual card without changing the draft.

The selected incident card shows:

- incident name;
- status and freshness;
- Priority score and top driver;
- count of exposed assets and simulated resources; and
- a clear first action, such as selecting or moving a resource.

### 6.2 Draft

The operator may make these local changes:

- close or reopen a visible road;
- change wind speed and direction;
- mark a simulated resource available or unavailable;
- drag a resource and choose **Assign** or **Relocate** at the drop point;
- assign a resource to an exposed asset from either object’s contextual card; and
- remove a manual assignment or relocation.

**Assign** creates a locked resource-to-destination pair. **Relocate** changes the resource’s scenario-only routing origin. A drop never guesses between the two actions.

Draft overlays update immediately and use styling that cannot be confused with observed reality or a computed recommendation. The command dock displays a concise change count and exposes:

- **Undo last change**, which reverts the most recent draft mutation;
- **Clear draft**, which restores the selected incident’s observed baseline after confirmation when more than one change exists; and
- **Run plan**, enabled when the draft is valid and the selected incident is current. An empty draft runs the observed baseline; a nonempty draft runs the proposed changes.

Switching incidents with unsaved draft changes requires confirmation. Cancel keeps the current incident and draft. Confirm discards the draft and switches incidents.

### 6.3 Run plan

Run plan is the only planning write action. While it runs:

- draft editing is locked;
- the dock shows progress in text, not only animation;
- duplicate submission is prevented; and
- the current draft remains visible.

The frontend uses the existing command sequence:

1. ensure a baseline scenario exists for the incident;
2. use that baseline for an empty draft, or create one immutable version when the draft differs from the active version;
3. request a recommendation for that exact version; and
4. retain the draft until a matching recommendation succeeds.

If scenario creation succeeds but recommendation generation fails, the scenario version remains immutable and reusable. **Retry** requests the recommendation again for that version with the existing idempotent command behavior. **Edit assumptions** restores editing and creates a new immutable version on the next run.

### 6.4 Recommend

A successful recommendation changes the dock to **PLAN READY**. The map highlights recommended routes, assignment ownership, newly covered assets, uncovered assets, and unreachable paths.

The compact result summary includes:

- a plain-language coverage statement;
- locked and optimized assignment counts;
- total travel-time or coverage change when available;
- explicit uncovered or unreachable asset counts; and
- **Adjust**, **Approve plan**, and secondary **Reject** actions.

Recommended routes may animate when motion is allowed. Reduced-motion mode renders the final line state without animation. Unreachable routes use a dashed red treatment and adjacent text. Uncovered assets remain visibly marked rather than disappearing.

Raw assignment tables, objective components, constraints, algorithm versions, and source versions remain available in Details & evidence.

### 6.5 Decide and audit

Adjust returns to the draft while retaining its assumptions. Approve and Reject reuse the existing decision dialog and require an operator note. The existing Edit recommendation flow remains available in the drawer for assignment-level edits.

After a successful decision:

- the dock confirms the recorded action;
- focus moves to the confirmation;
- the Audit action opens the matching append-only audit event; and
- the audit includes scenario inputs, relocation and locked-assignment assumptions, recommendation version, final assignments, actor, note, and timestamp.

## 7. First-use guidance

Guidance is contextual rather than a forced wizard. Short mission prompts appear beside the relevant control:

1. observe Park Fire, completed by the valid default or an explicit selection;
2. select or move a resource;
3. run the plan; and
4. review the recommendation.

Each prompt disappears after its action succeeds. Completion derives from existing selected-incident, draft, recommendation, and decision state. Guidance does not create a separate workflow state machine, block expert use, or prevent the operator from dismissing it.

Replay is conditional guidance, not a requirement of this redesign. While the package has fewer than two ordered snapshots, the map control explains why replay is unavailable and the mission prompts continue directly from Observe to Plan. Once a usable timeline exists, Replay appears as the second prompt between Observe and Plan and completes from the existing replay position/playback state; this does not move replay repair into this redesign's scope.

## 8. Frontend architecture

### 8.1 Command workspace ownership

The command workspace owns exactly one local `planningDraft` for the selected incident. The draft contains:

- the incident, incident snapshot, and road-graph versions it was based on;
- road closures;
- at most one active wind override for direct manipulation;
- resource availability overrides;
- scenario-only resource relocations;
- locked manual assignments; and
- enough prior draft snapshots to support Undo last change.

The draft is replaced when the incident or pinned snapshot changes after confirmation. Existing TanStack Query server state remains server state; the draft is not added to the query cache or persisted to local storage.

### 8.2 Map boundary

`OperationsMap` remains responsible for MapLibre lifecycle, sources, images, layers, and viewport state. It receives observed features, draft preview overlays, recommendation overlays, selected-object identity, active tool, and reduced-motion preference as props.

It emits semantic interaction events rather than modifying application state. Events cover:

- selecting an incident, resource, asset, road, or route;
- a resource drop with its geographic coordinate;
- toggling a road closure;
- requesting an assignment; and
- viewport-bound changes used to query visible road geometry.

The command workspace interprets those events, updates the local draft, and feeds the derived overlays back to the map. MapLibre event objects never escape the map component.

### 8.3 Existing component reuse

The redesign reuses current incident, scenario, comparison, recommendation, decision, and audit components. They move into the Details & evidence drawer or are adapted into compact summaries; their existing loading, error, disabled, and stale states remain authoritative.

Existing scenario list and form controls remain the keyboard-accessible equivalents of map actions. Both surfaces read and update the same draft, so they cannot diverge.

### 8.4 Preview overlay derivation

Preview overlays are pure derivations of observed data plus `planningDraft`. They include:

- amber road closures;
- draft resource positions;
- manual assignment connectors;
- availability changes;
- the draft wind indicator; and
- distinct selected and focused states.

Computed recommendation overlays remain separate from draft overlays. A stale recommendation is visually demoted and accompanied by “Run plan again”; it is never shown as the current result.

## 9. Viewport-bounded roads

The existing road-edge read API is extended with a `bbox=minLongitude,minLatitude,maxLongitude,maxLatitude` query. Values must be finite WGS84 coordinates with increasing bounds. The map requests only selectable edges intersecting the current viewport and pinned graph version. The response retains deterministic ordering, exact edge IDs, human-readable labels, geometry, and the existing `total` count so truncation remains visible when `total` exceeds the returned item count.

The client requests roads after `moveend`, cancels or ignores superseded requests, and does not query the nationwide or complete regional graph. Existing exact-ID lookup remains available for recommendation routes, audit evidence, and drawer search.

Road selection is enabled only for geometry from the scenario’s pinned graph version. A graph-version mismatch disables the road tool and explains that the incident must be refreshed before planning.

## 10. Scenario contract extensions

### 10.1 Resource relocation

An immutable scenario version may contain zero or one relocation per resource:

- stable resource ID;
- requested WGS84 longitude and latitude;
- snapped routing-graph node or point; and
- snap distance needed for explanation and audit.

Before the scenario version is persisted, coordinates must be finite, inside the demonstration region, and within the configured maximum distance of a routable node in the pinned graph. The stored version contains both the requested point and the validated snapped point. Relocation changes routing origin only for that scenario version. It never updates the observed resource row, future baselines, or another scenario.

### 10.2 Locked assignment

An immutable scenario version may contain locked resource-to-destination assignments. A resource can appear in at most one locked assignment. A locked assignment must reference resources and destinations from the pinned incident snapshot.

Before the scenario version is persisted, each locked assignment is validated against the complete scenario:

- the resource is available after overrides;
- capability and capacity satisfy the destination demand;
- the destination remains relevant to the incident;
- a route exists from the observed or relocated origin without crossing a closed road; and
- the configured response-time limit is satisfied.

Invalid relocations or locked assignments reject scenario-version creation with field-specific errors, leaving the local draft intact. Valid assignments are never silently unlocked or reassigned. Recommendation generation verifies the stored snapshot and graph versions but does not reinterpret the validated assignment.

### 10.3 Optimizer behavior

Validated locked assignments are reserved before the existing optimization model runs. Their resources are removed from the remaining candidate set and their supplied capacity is applied to destination demand. The optimizer then allocates only the remaining resources and unmet demand.

The final recommendation preserves all locked assignments and identifies every assignment as `manual` or `optimized`. Objective totals, coverage, uncovered demand, and explanations include both sets. The optimizer must not change, duplicate, or omit a valid manual assignment.

### 10.4 Compatibility

Existing scenario versions contain no relocations or locked assignments and keep their current behavior. New request fields default to empty collections. Existing road, weather, and availability override semantics remain unchanged.

## 11. Human-readable labels

Operational API responses add display labels without replacing stable IDs.

Label priority is:

1. a nonblank source or replay-package name;
2. a deterministic label composed from known type and location metadata; or
3. a deterministic type-based label with a stable ordinal inside the pinned snapshot or graph, such as “Engine unit 2” or “Unnamed road 12,” when no trustworthy name exists.

Examples include “Park Fire,” “Engine — Butte Meadows,” “Butte Meadows CDP,” and an OSM road name. Labels do not infer scientific meaning or fabricate real agency ownership. Stable IDs remain in API payloads and are shown in audit and technical evidence where exact identity matters.

## 12. Details & evidence drawer

The drawer is optional and does not block the map. It contains:

- complete incident and resource lists;
- keyboard-operable scenario controls equivalent to every map action;
- baseline and scenario comparison;
- recommendation assignments and decision controls;
- audit history and event detail;
- risk factors and model configuration;
- source provenance and freshness;
- raw detections, assets, resources, exact road IDs, and raw JSON; and
- solver inputs, constraints, versions, and diagnostics.

Native disclosures remain collapsed by default for technical sections. Opening and closing the drawer preserves the selected object and draft. Focus moves into the drawer when opened and returns to the invoking control when closed.

## 13. Error and conflict behavior

- **Run failure:** keep the draft and overlays; show Retry and Edit assumptions.
- **Unreachable route:** use dashed red geometry, an Unreachable label, and the affected resource and destination names.
- **Uncovered asset:** keep the asset visible and name it in the result summary.
- **Stale recommendation:** disable approval and editing, visually demote routes, and require Run plan again.
- **Stale incident snapshot:** preserve the draft until the operator chooses Refresh and discard or Stay on current snapshot.
- **Invalid relocation:** keep the marker at its draft position, identify why it cannot snap, and let the operator move or remove it.
- **Invalid locked assignment:** identify the resource, destination, and failed availability, capability, capacity, reachability, or response-time constraint.
- **Road data failure:** preserve other draft changes, disable road selection, and retain drawer search retry.
- **Basemap failure:** retain the existing one-time inline gray fallback and all operational overlays.
- **Incident switch with changes:** require discard confirmation.
- **API or solver timeout:** keep the last valid result visually separate from the failed current run and offer retry.

Error messages use human-readable labels first and include exact IDs only in technical details.

## 14. Accessibility and input parity

The redesign must provide:

- keyboard-selectable incidents, resources, assets, roads, routes, and result summaries;
- complete drawer-based controls for assignment, relocation coordinates, closures, wind, and availability;
- visible focus styles against both map and tactical chrome;
- correct heading, landmark, dialog, status, and live-region semantics;
- selection announcements without stealing focus from map or drawer controls, plus deliberate focus movement into blocking dialogs, plan results, and recorded-decision confirmations;
- Escape to cancel a transient map action without clearing the draft;
- 44px minimum targets for primary pointer controls;
- text, icons, fill patterns, and line styles in addition to color;
- a reduced-motion path that disables route animation and nonessential transitions; and
- preservation of loading, error, disabled, and stale explanations for assistive technology.

Map gestures are conveniences, not the only way to complete a task.

## 15. Testing strategy

### 15.1 Frontend unit and component tests

Tests cover:

- draft creation, replacement, validation, Undo, and Clear;
- incident-switch confirmation and focus restoration;
- semantic map events without leaking MapLibre objects;
- draft versus recommendation overlay styling;
- resource drop choice between Assign and Relocate;
- contextual prompts disappearing after successful use;
- loading, failure, retry, stale, and reduced-motion states;
- Details & evidence keyboard equivalents; and
- human-readable labels with deterministic fallbacks.

### 15.2 Backend unit and property tests

Tests cover:

- relocation coordinate and snap-distance validation;
- immutable persistence of relocations and locked assignments;
- locked assignment uniqueness and scenario membership;
- availability, compatibility, capacity, reachability, closure, and response-time validation;
- optimizer preservation of locked assignments while allocating remaining resources; and
- observed resource positions remaining unchanged.

Property tests continue to assert resource uniqueness, capacity bounds, availability, route validity, and deterministic results.

### 15.3 API and persistence integration tests

Tests cover:

- backward-compatible scenario requests;
- relocation and locked-assignment round trips;
- viewport-bounded road queries on the pinned graph;
- idempotent retries after recommendation failure;
- stale snapshot and graph-version conflicts;
- decision and audit records containing the new assumptions; and
- migrations preserving existing scenarios and recommendations.

### 15.4 Browser acceptance

At both 1280×720 and 1024×768, an operator must be able to:

1. select the Park Fire;
2. create at least one local map draft change;
3. run the plan;
4. see routes, coverage, and exceptions on the map;
5. approve the recommendation with a note; and
6. open the matching audit event.

The primary path must not require scrolling through risk factors, detections, assets, resources, raw assignments, or JSON. A second browser path completes the same planning actions using only keyboard-accessible drawer controls. Browser checks also verify basemap attribution, readable labels, 44px targets, visible focus, reduced motion, and no console errors.

## 16. Acceptance criteria

The redesign is complete when:

- the tactical map remains visible throughout Observe → Draft → Run plan → Recommend → Decide;
- Park Fire and the next primary action are visible in the first viewport;
- every supported map action updates a reversible local draft without a server write;
- Run plan creates an immutable scenario version and a matching recommendation through existing command APIs;
- relocation affects only the scenario routing origin;
- valid manual assignments are preserved exactly and the optimizer fills remaining gaps;
- failures preserve the draft and offer Retry or Edit assumptions;
- stale results cannot be approved;
- recommendation routes, uncovered assets, and unreachable paths are visually and textually explicit;
- operational surfaces use human-readable labels and reserve exact IDs for audit or technical evidence;
- every map action has a keyboard-accessible equivalent;
- the approved browser workflow passes at 1280×720 and 1024×768; and
- existing incident, scenario, recommendation, decision, audit, basemap-fallback, and replay-unavailable behavior remains covered.

## 17. Delivery sequencing and project completion gates

The implementation roadmap must preserve these boundaries:

1. **Land the current baseline:** commit, review, and merge the already verified basemap and first-time-workflow changes before starting the command-workspace redesign. The new design must be based on that merged behavior rather than silently absorbing unrelated uncommitted work.
2. **Restore missing product proof:** repair temporal replay so the Park Fire package exposes at least two ordered snapshots; add the dedicated degraded-mode and performance suites; and record measured results.
3. **Implement the map-first redesign:** build the command workspace and scenario extensions in this specification. Replace the stale Playwright journey with the browser acceptance paths in Section 15.4 instead of patching it twice against an intermediate layout.
4. **Finish the portfolio release:** add CI, the production Docker image, deployment configuration, public deployment, README expansion, diagrams, screenshots, benchmark report, and demo video only after product behavior is stable. External deployment and video publication still require explicit user authorization.

Track 1 is a prerequisite for every new track. After it lands, Tracks 2 and 3 may proceed independently. Track 4 begins only after the product behavior and proof from both are stable.

The first implementation plan written from this specification covers Track 3 and identifies Track 1 as its baseline prerequisite. Temporal replay/proof and portfolio release remain separate implementation plans because they change different subsystems and have independent acceptance criteria.

WildfireOps is not complete under the original specification until all four tracks are merged, the replacement Playwright journey passes, performance results are measured, and the public demonstration is verified.

## 18. Approved visual references

The following companion artifacts define the intended information hierarchy and interaction direction:

- `.superpowers/brainstorm/79684-1784412965/content/final-layout-architecture.html`
- `.superpowers/brainstorm/79684-1784412965/content/interaction-flow.html`
- `.superpowers/brainstorm/79684-1784412965/content/information-components.html`

Earlier selected comparisons are:

- layout A, tactical map canvas;
- visual style C, hybrid command; and
- recommendation presentation A, on-map proposal.

These references are directional rather than pixel-perfect acceptance images. Accessibility, live data states, and the explicit behaviors in this specification take precedence.
