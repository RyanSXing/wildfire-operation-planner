import type {
  ExerciseAsset,
  ExerciseCheckpoint,
  ExerciseEvent,
  ExerciseSession,
  PlanOutput,
} from "../api/exerciseTypes";
import type { RoadEdge } from "../api/types";
import { DRAWER_TABS, type DrawerTab } from "./drawerTabs";
import {
  assetKindLabel,
  describeConstraint,
  eventLabel,
  formatDistance,
  formatMinutes,
  OBJECTIVE_COPY,
  resourceDetail,
  resourceLabel,
  taskDetail,
  taskLabel,
  windLabel,
  type NameBook,
  type PlainChange,
} from "./language";

export type DetailDrawerProps = {
  tab: DrawerTab;
  onTabChange: (tab: DrawerTab) => void;
  session: ExerciseSession;
  checkpoint: ExerciseCheckpoint;
  plan: PlanOutput | null;
  changes: readonly PlainChange[];
  book: NameBook;
  assets: readonly ExerciseAsset[];
  events: readonly ExerciseEvent[];
  routeEdges: readonly RoadEdge[];
  selectedId: string | null;
  onLocate: (kind: "asset" | "resource", id: string) => void;
};

export function DetailDrawer({
  tab,
  onTabChange,
  session,
  checkpoint,
  plan,
  changes,
  book,
  assets,
  events,
  routeEdges,
  selectedId,
  onLocate,
}: DetailDrawerProps) {
  return (
    <aside className="wf-drawer" aria-label="Checkpoint details">
      <div className="wf-drawer__head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className="wf-drawer__title">{checkpoint.title}</h2>
          <p className="wf-drawer__meta">
            {checkpoint.tasks.length} tasks · wind{" "}
            {windLabel(checkpoint.disruption)}
          </p>
        </div>
      </div>
      <div className="wf-tabs" role="tablist" aria-label="Checkpoint detail">
        {DRAWER_TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            id={`wf-tab-${entry.id}`}
            className="wf-tab"
            aria-selected={tab === entry.id}
            aria-controls={`wf-tabpanel-${entry.id}`}
            onClick={() => onTabChange(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div
        className="wf-drawer__body"
        role="tabpanel"
        id={`wf-tabpanel-${tab}`}
        aria-labelledby={`wf-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "plan" && (
          <PlanTab plan={plan} changes={changes} book={book} routeEdges={routeEdges} />
        )}
        {tab === "tasks" && (
          <TasksTab
            checkpoint={checkpoint}
            plan={plan}
            book={book}
            assets={assets}
            selectedId={selectedId}
            onLocate={onLocate}
          />
        )}
        {tab === "evidence" && (
          <EvidenceTab
            session={session}
            checkpoint={checkpoint}
            plan={plan}
            book={book}
            assets={assets}
          />
        )}
        {tab === "audit" && <AuditTab events={events} book={book} />}
      </div>
    </aside>
  );
}

function PlanTab({
  plan,
  changes,
  book,
  routeEdges,
}: {
  plan: PlanOutput | null;
  changes: readonly PlainChange[];
  book: NameBook;
  routeEdges: readonly RoadEdge[];
}) {
  if (!plan) {
    return (
      <p className="wf-prose wf-prose--muted">
        No plan yet for this checkpoint. Choose an objective, then generate a
        plan from the command bar below the map.
      </p>
    );
  }

  const edgeNames = new Map(
    routeEdges.map((edge) => [edge.edgeId, edge.label] as const),
  );

  return (
    <>
      <h3 className="wf-section">WHAT THE PLAN DOES</h3>
      <div className="wf-stack">
        {plan.assignments.map((assignment) => {
          const road = assignment.route.edgeIds
            .map((edgeId) => edgeNames.get(edgeId))
            .find((label): label is string => Boolean(label));
          return (
            <article
              className="wf-card"
              key={`${assignment.resourceId}-${assignment.taskId}`}
            >
              <div className="wf-card__head">
                <span className="wf-card__name">
                  {resourceLabel(assignment.resourceId, book)}
                </span>
                <span className="wf-card__eta">
                  {formatMinutes(assignment.travelMinutes)}
                </span>
              </div>
              <p className="wf-card__task">{taskLabel(assignment.taskId, book)}</p>
              <p className="wf-card__meta">
                {assignment.capacity} units of capacity ·{" "}
                {formatDistance(assignment.route.distanceMeters)}
                {road ? ` · via ${road}` : ""}
              </p>
            </article>
          );
        })}
        {plan.assignments.length === 0 && (
          <p className="wf-prose wf-prose--muted">
            The planner assigned nothing at this checkpoint.
          </p>
        )}
      </div>

      {changes.length > 0 && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            WHY IT LOOKS LIKE THIS
          </h3>
          <div className="wf-stack">
            {changes.map((change, index) => (
              <div
                className="wf-note"
                data-tone={change.tone}
                key={`${change.code}-${index}`}
              >
                <strong>{change.headline}</strong>
                {change.detail}
              </div>
            ))}
          </div>
        </>
      )}

      {plan.unassignedResourceIds.length > 0 && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            UNITS WITH NOTHING TO DO
          </h3>
          <div className="wf-stack">
            {plan.unassignedResourceIds.map((resourceId) => (
              <div className="wf-card" key={resourceId}>
                <p className="wf-card__name">{resourceLabel(resourceId, book)}</p>
                <p className="wf-card__meta">
                  {resourceDetail(resourceId, book)} — nothing at this checkpoint
                  needs what it carries.
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}

function TasksTab({
  checkpoint,
  plan,
  book,
  assets,
  selectedId,
  onLocate,
}: {
  checkpoint: ExerciseCheckpoint;
  plan: PlanOutput | null;
  book: NameBook;
  assets: readonly ExerciseAsset[];
  selectedId: string | null;
  onLocate: (kind: "asset" | "resource", id: string) => void;
}) {
  const coverage = new Map(
    (plan?.taskCoverage ?? []).map((entry) => [entry.taskId, entry]),
  );
  const assignedBy = new Map(
    (plan?.assignments ?? []).map((assignment) => [
      assignment.taskId,
      assignment.resourceId,
    ]),
  );
  const assetById = new Map(assets.map((asset) => [asset.assetId, asset]));

  return (
    <>
      <p className="wf-prose wf-prose--muted" style={{ marginBottom: 12 }}>
        Every task in this checkpoint. Selecting one highlights its location on
        the plot — the keyboard equivalent of clicking the map.
      </p>
      <div className="wf-stack">
        {checkpoint.tasks.map((task) => {
          const covered = coverage.get(task.taskId)?.covered ?? null;
          const assignee = assignedBy.get(task.taskId);
          const asset = assetById.get(task.assetId);
          return (
            <article className="wf-card" key={task.taskId}>
              <div className="wf-card__head">
                <span className="wf-card__name">
                  {taskLabel(task.taskId, book)}
                </span>
                {covered !== null && (
                  <span
                    className="wf-card__eta"
                    style={{ color: covered ? "#5fd08a" : "#ff6a3d" }}
                  >
                    {covered ? "COVERED" : "UNCOVERED"}
                  </span>
                )}
              </div>
              <p className="wf-card__meta">{taskDetail(task.taskId, book)}</p>
              <p className="wf-card__meta">
                {assignee
                  ? `${resourceLabel(assignee, book)} is assigned.`
                  : "No unit assigned."}
                {asset ? ` ${assetKindLabel(asset.assetKind)}.` : ""}
              </p>
              <div className="wf-actions" style={{ marginTop: 10 }}>
                <button
                  type="button"
                  className="wf-secondary"
                  aria-pressed={selectedId === task.assetId}
                  onClick={() => onLocate("asset", task.assetId)}
                >
                  Show on plot
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}

function EvidenceTab({
  session,
  checkpoint,
  plan,
  book,
  assets,
}: {
  session: ExerciseSession;
  checkpoint: ExerciseCheckpoint;
  plan: PlanOutput | null;
  book: NameBook;
  assets: readonly ExerciseAsset[];
}) {
  const objective = session.objective;
  const usedAssetIds = new Set(checkpoint.tasks.map((task) => task.assetId));
  const cited = assets.filter((asset) => usedAssetIds.has(asset.assetId));

  return (
    <>
      <h3 className="wf-section">HOW THIS PLAN WAS MADE</h3>
      <dl className="wf-kv">
        <div>
          <dt>Objective</dt>
          <dd>
            {objective
              ? `${OBJECTIVE_COPY[objective].title} — ${OBJECTIVE_COPY[objective].plain}`
              : "Not chosen yet"}
          </dd>
        </div>
        <div>
          <dt>Planner</dt>
          <dd>{plan?.algorithmVersion ?? "task-allocation-v1"}</dd>
        </div>
        <div>
          <dt>Result</dt>
          <dd>
            {plan
              ? `${plan.status} in ${plan.runtimeMilliseconds} ms`
              : "No plan generated"}
          </dd>
        </div>
        {plan && (
          <div>
            <dt>Score</dt>
            <dd>
              {plan.objectiveComponents.objectiveValue} — travel{" "}
              {plan.objectiveComponents.travelCost}, uncovered-task penalty{" "}
              {plan.objectiveComponents.uncoveredTaskPenalty}. Lower is better.
            </dd>
          </div>
        )}
        <div>
          <dt>Weather</dt>
          <dd>
            {windLabel(checkpoint.disruption)} · observed{" "}
            {checkpoint.historicalWeatherIdentity}
          </dd>
        </div>
        <div>
          <dt>Situation time</dt>
          <dd>{checkpoint.referenceAt}</dd>
        </div>
        <div>
          <dt>Exercise definition</dt>
          <dd>
            {session.exerciseId} v{session.definitionVersion} · digest{" "}
            {session.definitionDigest.slice(0, 12)}…
          </dd>
        </div>
      </dl>

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        WHAT THE PLANNER COULD NOT DO
      </h3>
      {plan && plan.bindingConstraints.length > 0 ? (
        <div className="wf-stack">
          {plan.bindingConstraints.map((constraint) => (
            <div className="wf-note" data-tone="neutral" key={constraint}>
              {describeConstraint(constraint, book)}
            </div>
          ))}
        </div>
      ) : (
        <p className="wf-prose wf-prose--muted">
          No blocking constraints recorded for this checkpoint.
        </p>
      )}

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        SOURCES FOR THE PLACES IN THIS CHECKPOINT
      </h3>
      <dl className="wf-kv">
        {cited.map((asset) => (
          <div key={asset.assetId}>
            <dt>{asset.name}</dt>
            <dd>
              {asset.sourceName} · {asset.sourceVersion} ·{" "}
              <a href={asset.citationUrl} target="_blank" rel="noreferrer">
                record {asset.sourceRecordId}
              </a>
            </dd>
          </div>
        ))}
      </dl>

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        SIMULATED, NOT HISTORICAL
      </h3>
      <dl className="wf-kv">
        {checkpoint.incidents.map((incident) => (
          <div key={incident.incidentKey}>
            <dt>{incident.name}</dt>
            <dd>
              {incident.provenance === "historical"
                ? `Historical — detections ${incident.detectionIdentities.join(", ")}`
                : "Invented for this exercise. It did not happen."}
            </dd>
          </div>
        ))}
        <div>
          <dt>Tasks and units</dt>
          <dd>
            Every task, priority, capacity, and response unit in this exercise is
            an assumption written for training.
          </dd>
        </div>
      </dl>
    </>
  );
}

function AuditTab({
  events,
  book,
}: {
  events: readonly ExerciseEvent[];
  book: NameBook;
}) {
  if (events.length === 0) {
    return (
      <p className="wf-prose wf-prose--muted">
        Nothing recorded yet. Every action you take appears here.
      </p>
    );
  }
  return <AuditTimeline events={events} book={book} />;
}

export function AuditTimeline({
  events,
  book,
}: {
  events: readonly ExerciseEvent[];
  book: NameBook;
}) {
  return (
    <ol className="wf-timeline">
      {events.map((event) => (
        <li className="wf-timeline__row" key={event.id}>
          <span className="wf-timeline__time">{clockTime(event.occurredAt)}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p
              className="wf-timeline__what"
              data-tone={
                event.eventType === "exercise.plan-approved" ? "approval" : undefined
              }
            >
              {eventLabel(event.eventType)}
            </p>
            <p className="wf-timeline__who">
              {event.displayName ?? event.actorCallsign} · version{" "}
              {event.expectedSessionVersion} → {event.resultingSessionVersion}
              {describeInputs(event, book)}
            </p>
            {event.note !== null && (
              <p className="wf-timeline__note">{event.note}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function describeInputs(event: ExerciseEvent, book: NameBook): string {
  const inputs = event.inputs as Record<string, unknown>;
  const objective = inputs.objective;
  if (typeof objective === "string" && objective in OBJECTIVE_COPY) {
    return ` · ${OBJECTIVE_COPY[objective as keyof typeof OBJECTIVE_COPY].title}`;
  }
  const resourceId = inputs.resourceId;
  const taskId = inputs.taskId;
  if (typeof resourceId === "string" && typeof taskId === "string") {
    return ` · pinned ${resourceLabel(resourceId, book)} to ${taskLabel(taskId, book)}`;
  }
  return "";
}

function clockTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}
