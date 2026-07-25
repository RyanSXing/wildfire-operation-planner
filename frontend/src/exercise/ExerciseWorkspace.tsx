import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { ApiClientError } from "../api/client";
import {
  useExerciseAudit,
  useExerciseCommand,
  useExerciseDebrief,
  useExerciseMetadata,
  useExerciseSession,
  useCitedDetections,
  useSandboxPlan,
} from "../api/exerciseHooks";
import type {
  ExerciseObjective,
  ExerciseSession,
  ExerciseTask,
  SandboxPlan,
  SandboxPlanRequest,
} from "../api/exerciseTypes";
import { useExactRoadEdges } from "../api/hooks";
import type { RoadEdge } from "../api/types";
import { DebriefPanel } from "./DebriefPanel";
import { DetailDrawer } from "./DetailDrawer";
import type { DrawerTab } from "./drawerTabs";

import { IntroPanel } from "./IntroPanel";

// MapLibre stays in its own chunk rather than weighing down first paint of the
// introduction, which needs no map at all.
const ExerciseMap = lazy(() =>
  import("./ExerciseMap").then((module) => ({ default: module.ExerciseMap })),
);
import {
  ApprovalPanel,
  ChangeBriefing,
  ObjectivePanel,
  OverridePanel,
} from "./panels";
import {
  assetLabel,
  buildNameBook,
  formatPopulation,
  humanize,
  resourceLabel,
  toPlainChanges,
  windLabel,
} from "./language";
import "./exercise.css";

const SESSION_STORAGE_KEY = "wildfireops.exercise.sessionId";

type OpenPanel = "objective" | "override" | "approval" | null;

export function ExerciseWorkspace() {
  const [sessionId, setSessionId] = useState<string | null>(() =>
    readStoredSessionId(),
  );
  const [seenTasks, setSeenTasks] = useState<ReadonlyMap<string, ExerciseTask>>(
    () => new Map(),
  );
  const [tab, setTab] = useState<DrawerTab>("plan");
  const [selection, setSelection] = useState<{
    kind: "asset" | "resource";
    id: string;
  } | null>(null);
  const [acknowledgedPlan, setAcknowledgedPlan] = useState<string | null>(null);
  const [manualPanel, setManualPanel] = useState<OpenPanel>(null);
  const [sandboxResult, setSandboxResult] = useState<SandboxPlan | null>(null);
  // Approving does not yank the operator into the debrief: the workspace holds
  // the approved state until they choose to leave it.
  const [debriefOpen, setDebriefOpen] = useState(false);

  const metadataQuery = useExerciseMetadata();
  const sessionQuery = useExerciseSession(sessionId);
  const session = sessionQuery.data ?? null;

  const adoptSession = useCallback((next: ExerciseSession) => {
    setSessionId(next.id);
    writeStoredSessionId(next.id);
  }, []);

  const command = useExerciseCommand(session, adoptSession);
  const sandbox = useSandboxPlan(sessionId);

  const completed = session?.status === "completed";
  const auditQuery = useExerciseAudit(sessionId, session !== null);
  const debriefQuery = useExerciseDebrief(sessionId, completed);

  // Checkpoint task definitions only ever arrive with the checkpoint that owns
  // them, so they are accumulated as the exercise runs and the debrief can then
  // name every task from every checkpoint rather than only the last one.
  const checkpointTasks = session?.currentCheckpoint.tasks;
  useEffect(() => {
    if (!checkpointTasks) {
      return;
    }
    setSeenTasks((previous) => {
      const next = new Map(previous);
      let changed = false;
      for (const task of checkpointTasks) {
        if (!next.has(task.taskId)) {
          next.set(task.taskId, task);
          changed = true;
        }
      }
      return changed ? next : previous;
    });
  }, [checkpointTasks]);

  // `session.latestPlan` is the newest plan in the whole session, which after
  // "Continue" is still the previous checkpoint's. The server offers
  // `generate-plan` exactly when the current checkpoint has no accepted plan,
  // so that flag — not the plan's presence — decides what is on screen.
  const awaitingPlan = session?.allowedActions.includes("generate-plan") ?? false;
  const plan = awaitingPlan ? null : (session?.latestPlan ?? null);
  const graphVersion = readString(plan?.versions, "graph") ?? "";
  // A corridor the exercise scripts as closed may have been cleared by an
  // earlier decision. The plan's own change list is the authority on what is
  // actually shut, so the plot never contradicts the briefing text.
  const closedEdgeIds = useMemo(() => {
    const scripted = new Set(
      session?.currentCheckpoint.disruption.closedEdgeIds ?? [],
    );
    for (const change of plan?.explanation.changes ?? []) {
      const edgeId = change.evidence.edgeId;
      if (typeof edgeId !== "string") {
        continue;
      }
      if (change.code === "route.reopened") {
        scripted.delete(edgeId);
      } else if (change.code === "route.closed") {
        scripted.add(edgeId);
      }
    }
    return [...scripted];
  }, [session, plan]);
  const wantedEdgeIds = useMemo(() => {
    const ids = new Set<string>(closedEdgeIds);
    for (const assignment of plan?.assignments ?? []) {
      for (const edgeId of assignment.route.edgeIds) {
        ids.add(edgeId);
      }
    }
    return [...ids];
  }, [plan, closedEdgeIds]);
  // The checkpoint cites the satellite detections that establish its historical
  // incidents; those are the fire on the plot.
  const citedIdentities = useMemo(
    () =>
      (session?.currentCheckpoint.incidents ?? []).flatMap(
        (incident) => incident.detectionIdentities,
      ),
    [session],
  );
  const detectionQuery = useCitedDetections(citedIdentities);

  const { query: edgeQuery } = useExactRoadEdges(graphVersion, wantedEdgeIds);
  const edges = useMemo(
    () => edgeQuery.data?.items ?? [],
    [edgeQuery.data],
  );

  const routeEdgeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const assignment of plan?.assignments ?? []) {
      for (const edgeId of assignment.route.edgeIds) {
        ids.add(edgeId);
      }
    }
    return ids;
  }, [plan]);
  const routeEdges = useMemo(
    () => edges.filter((edge: RoadEdge) => routeEdgeIds.has(edge.edgeId)),
    [edges, routeEdgeIds],
  );
  const closedEdges = useMemo(
    () => edges.filter((edge: RoadEdge) => closedEdgeIds.includes(edge.edgeId)),
    [edges, closedEdgeIds],
  );

  const book = useMemo(
    () =>
      buildNameBook(
        metadataQuery.data?.assets ?? [],
        metadataQuery.data?.resources ?? [],
        [...seenTasks.values()],
        new Map(
          edges
            .filter((edge: RoadEdge) => edge.label !== null)
            .map((edge: RoadEdge) => [edge.edgeId, edge.label] as const),
        ),
        session?.currentCheckpoint.incidents ?? [],
      ),
    [metadataQuery.data, seenTasks, edges, session],
  );

  const changes = useMemo(() => toPlainChanges(plan, book), [plan, book]);
  const labelFor = useCallback(
    (kind: "asset" | "resource", id: string) =>
      kind === "asset" ? assetLabel(id, book) : resourceLabel(id, book),
    [book],
  );

  const allowed = useMemo(
    () => new Set(session?.allowedActions ?? []),
    [session],
  );

  const planKey = readString(plan?.versions, "inputHash");
  const briefingChanges = changes.filter(
    (change) => change.code !== "plan.outcome",
  );
  const showBriefing =
    session !== null &&
    !completed &&
    planKey !== null &&
    planKey !== acknowledgedPlan &&
    briefingChanges.length > 0;

  const panel = resolvePanel(session, manualPanel, showBriefing);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && manualPanel !== null) {
        setManualPanel(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [manualPanel]);

  const commandError = errorMessage(command.error);
  const running = command.isPending;

  const runSandbox = useCallback(
    (request: SandboxPlanRequest) => {
      sandbox.mutate(request, { onSuccess: setSandboxResult });
    },
    [sandbox],
  );

  const restart = useCallback(() => {
    clearStoredSessionId();
    setSessionId(null);
    setSeenTasks(new Map());
    setAcknowledgedPlan(null);
    setSandboxResult(null);
    setManualPanel(null);
    setDebriefOpen(false);
    command.reset();
  }, [command]);

  if (metadataQuery.isPending) {
    return <Splash message="Loading the exercise…" />;
  }
  if (metadataQuery.isError || !metadataQuery.data) {
    return (
      <Splash
        message={
          errorMessage(metadataQuery.error) ??
          "The exercise could not be loaded."
        }
      />
    );
  }

  const metadata = metadataQuery.data;

  if (sessionId === null) {
    return (
      <div className="wf">
        <IntroPanel
          metadata={metadata}
          starting={running}
          error={commandError}
          onStart={() => command.mutate({ name: "create-session" })}
        />
      </div>
    );
  }

  if (session === null) {
    return (
      <Splash
        message={
          sessionQuery.isError
            ? "That exercise session is no longer available."
            : "Restoring your session…"
        }
        action={
          sessionQuery.isError
            ? { label: "Start a new exercise", onClick: restart }
            : undefined
        }
      />
    );
  }

  // Sessions expire 24 hours after they start. The server keeps answering with
  // status "expired" and a single allowed action, so the exercise has to offer
  // that action rather than leave the operator on a dock with nothing to press.
  if (session.status === "expired") {
    return (
      <div className="wf">
        <div className="wf-centre">
          <main className="wf-sheet" aria-labelledby="wf-expired-title">
            <p className="wf-sheet__eyebrow">SESSION EXPIRED</p>
            <h1 className="wf-sheet__title" id="wf-expired-title">
              This exercise timed out
            </h1>
            <p className="wf-sheet__lede">
              Sessions run for 24 hours so the replay data behind them stays
              consistent. Everything {session.callsign} recorded is still in the
              audit trail; a new run starts from the first checkpoint.
            </p>
            <div className="wf-actions">
              <button type="button" className="wf-primary" onClick={restart}>
                Start a new exercise
              </button>
            </div>
          </main>
        </div>
      </div>
    );
  }

  if (completed && debriefOpen && debriefQuery.data) {
    return (
      <div className="wf">
        <DebriefPanel
          session={session}
          metadata={metadata}
          debrief={debriefQuery.data}
          book={book}
          sandboxResult={sandboxResult}
          sandboxPending={sandbox.isPending}
          sandboxError={errorMessage(sandbox.error)}
          onRunSandbox={runSandbox}
          onRestart={restart}
        />
      </div>
    );
  }

  const checkpoint = session.currentCheckpoint;
  const fieldReport = checkpoint.fieldReports[0] ?? null;
  const uncovered = plan?.uncoveredTaskIds.length ?? 0;

  return (
    <div className="wf">
      {/* inert removes the subtree from both the tab order and the
          accessibility tree while the modal briefing is open. */}
      <nav className="wf-rail" aria-label="Exercise progress" inert={showBriefing}>
        <div className="wf-brand">
          <span className="wf-brand__dot" />
          <span className="wf-brand__name">WildfireOps</span>
          <span className="wf-brand__chip">EXERCISE</span>
        </div>
        <p className="wf-label">YOUR PROGRESS</p>
        <ol className="wf-steps">
          {buildSteps(session, metadata.checkpointCount).map((step) => (
            <li
              className="wf-step"
              data-state={step.state}
              key={step.key}
              aria-current={step.state === "current" ? "step" : undefined}
            >
              <span className="wf-step__mark" aria-hidden="true">
                {step.state === "done" ? "✓" : step.ordinal}
              </span>
              <span style={{ minWidth: 0 }}>
                <span className="wf-visually-hidden">{STEP_STATE_TEXT[step.state]}</span>
                <span className="wf-step__title">{step.title}</span>
                <span className="wf-step__note">{step.note}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className="wf-rail__foot">
          <span className="wf-dot-good" />
          <span>
            {session.callsign} · <a href="/monitor">Live Monitor</a>
          </span>
        </div>
      </nav>

      <main className="wf-main">
        <Suspense
          fallback={
            <div className="wf-map__fallback" role="status">
              loading plot…
            </div>
          }
        >
          <ExerciseMap
            checkpoint={checkpoint}
            assets={metadata.assets}
            resources={metadata.resources}
            plan={plan}
            detections={detectionQuery.data ?? []}
            routeEdges={routeEdges}
            closedEdges={closedEdges}
            selectedId={selection?.id ?? null}
            onSelect={setSelection}
            labelFor={labelFor}
          />
        </Suspense>

        <div className="wf-map__top">
          <span className="wf-phase" data-tone={phaseTone(session)}>
            {phaseLabel(session)}
          </span>
          <div className="wf-stats">
            <span className="wf-stat">
              <span>TASKS</span>
              {checkpoint.tasks.length}
            </span>
            <span className="wf-stat">
              <span>UNCOVERED</span>
              {plan ? uncovered : "—"}
            </span>
            <span className="wf-stat">
              <span>WIND</span>
              {windLabel(checkpoint.disruption)}
            </span>
            <span className="wf-stat">
              <span>PEOPLE</span>
              {formatPopulation(
                checkpoint.tasks.reduce(
                  (total, task) => total + task.affectedPopulation,
                  0,
                ),
              )}
            </span>
          </div>
        </div>

        <div className="wf-legend" aria-label="Plot legend">
          <span>
            <span className="wf-key-fire" /> Fire detection (satellite)
          </span>
          {checkpoint.incidents.some((item) => item.simulatedPosition) && (
            <span>
              <span className="wf-key-simulated" /> Simulated fire
            </span>
          )}
          <span>
            <span className="wf-key-unit" /> Response unit
          </span>
          <span>
            <span className="wf-key-asset" /> Place with a task
          </span>
          <span>
            <span className="wf-key-route" /> Planned route
          </span>
          <span>
            <span className="wf-key-closed">✕</span> Closed corridor
          </span>
        </div>

        {panel === "objective" && (
          <ObjectivePanel
            current={session.objective}
            pending={running}
            replanning={session.objective !== null}
            onChoose={(objective: ExerciseObjective) => {
              setManualPanel(null);
              command.mutate({ name: "select-objective", objective });
            }}
            onClose={
              session.objective === null ? null : () => setManualPanel(null)
            }
          />
        )}

        {panel === "override" && fieldReport !== null && (
          <OverridePanel
            report={fieldReport}
            plan={plan}
            book={book}
            pending={running}
            onApply={(resourceId, taskId) =>
              command.mutate({ name: "apply-override", resourceId, taskId })
            }
          />
        )}

        {panel === "approval" && (
          <ApprovalPanel
            callsign={session.callsign}
            plan={plan}
            book={book}
            pending={running}
            error={commandError}
            onApprove={(displayName, note) =>
              command.mutate({ name: "decide", displayName, note })
            }
          />
        )}

        {showBriefing && (
          <ChangeBriefing
            checkpoint={checkpoint}
            changes={briefingChanges}
            index={session.checkpointIndex}
            total={metadata.checkpointCount}
            onDismiss={() => setAcknowledgedPlan(planKey)}
          />
        )}

        <CommandDock
          inert={showBriefing}
          session={session}
          allowed={allowed}
          running={running}
          error={commandError}
          panel={panel}
          onGenerate={() => command.mutate({ name: "generate-plan" })}
          onAdvance={() => command.mutate({ name: "advance" })}
          onChangeObjective={() => setManualPanel("objective")}
          onOpenDebrief={() => setDebriefOpen(true)}
        />
      </main>

      <DetailDrawer
        inert={showBriefing}
        tab={tab}
        onTabChange={setTab}
        session={session}
        checkpoint={checkpoint}
        plan={plan}
        changes={changes}
        book={book}
        assets={metadata.assets}
        events={auditQuery.data?.items ?? []}
        routeEdges={routeEdges}
        selectedId={selection?.id ?? null}
        onLocate={(kind, id) => setSelection({ kind, id })}
      />
    </div>
  );
}

function CommandDock({
  inert: isInert,
  session,
  allowed,
  running,
  error,
  panel,
  onGenerate,
  onAdvance,
  onChangeObjective,
  onOpenDebrief,
}: {
  inert: boolean;
  session: ExerciseSession;
  allowed: ReadonlySet<string>;
  running: boolean;
  error: string | null;
  panel: OpenPanel;
  onGenerate: () => void;
  onAdvance: () => void;
  onChangeObjective: () => void;
  onOpenDebrief: () => void;
}) {
  const plan = session.latestPlan;

  if (session.objective === null) {
    return (
      <Dock
        isInert={isInert}
        title="Start by choosing an objective"
        hint="It decides which task wins when two need the same unit."
        error={error}
      />
    );
  }

  if (allowed.has("generate-plan")) {
    return (
      <Dock
        isInert={isInert}
        title="Ready to plan"
        hint="The planner will assign every unit it can and tell you what it could not cover."
        error={error}
        actions={
          <>
            <button
              type="button"
              className="wf-secondary"
              onClick={onChangeObjective}
              disabled={running}
            >
              Change objective
            </button>
            <button
              type="button"
              className="wf-primary"
              onClick={onGenerate}
              disabled={running}
            >
              {running ? "Planning…" : "Generate the plan"}
            </button>
          </>
        }
        busy={running}
      />
    );
  }

  if (allowed.has("advance")) {
    return (
      <Dock
        isInert={isInert}
        title={coverageLine(plan)}
        hint="Read the plan on the right. Continue when you are satisfied, or change the objective and plan again."
        tone="active"
        error={error}
        actions={
          <>
            <button
              type="button"
              className="wf-secondary"
              onClick={onChangeObjective}
              disabled={running}
            >
              Change objective
            </button>
            <button
              type="button"
              className="wf-primary"
              onClick={onAdvance}
              disabled={running}
            >
              {running ? "Advancing…" : "Continue"}
            </button>
          </>
        }
        busy={running}
      />
    );
  }

  if (allowed.has("apply-override")) {
    return (
      <Dock
        isInert={isInert}
        title="A field report needs your judgement"
        hint={
          panel === "override"
            ? "Decide whether to pin a unit to the reported task."
            : "Open the field report to continue."
        }
        tone="active"
        error={error}
        busy={running}
      />
    );
  }

  if (allowed.has("approve-plan")) {
    return (
      <Dock
        isInert={isInert}
        title={coverageLine(plan)}
        hint="Sign the plan off with your name and the reason for it."
        tone="active"
        error={error}
        busy={running}
      />
    );
  }

  if (allowed.has("view-debrief")) {
    return (
      <Dock
        isInert={isInert}
        title="Exercise complete"
        hint="Your decision is recorded in the audit trail."
        tone="done"
        error={error}
        actions={
          <button type="button" className="wf-primary" onClick={onOpenDebrief}>
            Open the debrief
          </button>
        }
      />
    );
  }

  return <Dock title="Waiting" hint="No action is available." error={error} />;
}

function Dock({
  title,
  hint,
  tone,
  error,
  actions,
  busy,
  isInert,
}: {
  title: string;
  hint: string;
  tone?: "active" | "done";
  error: string | null;
  actions?: React.ReactNode;
  busy?: boolean;
  isInert?: boolean;
}) {
  return (
    <div
      className="wf-dock"
      role="region"
      aria-label="Next step"
      aria-busy={busy === true}
      inert={isInert}
    >
      {busy === true && <span className="wf-spinner" aria-hidden="true" />}
      <div className="wf-dock__body" aria-live="polite" aria-atomic="true">
        <p className="wf-dock__title" data-tone={tone}>
          {title}
        </p>
        <p className="wf-dock__hint">{hint}</p>
      </div>
      {error !== null && (
        <p className="wf-error wf-dock__error" role="alert">
          {error}
        </p>
      )}
      {actions}
    </div>
  );
}

function Splash({
  message,
  action,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="wf">
      <div className="wf-centre">
        <div className="wf-sheet" role="status">
          <p className="wf-prose">{message}</p>
          {action && (
            <div className="wf-actions">
              <button
                type="button"
                className="wf-primary"
                onClick={action.onClick}
              >
                {action.label}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function resolvePanel(
  session: ExerciseSession | null,
  manual: OpenPanel,
  briefingOpen: boolean,
): OpenPanel {
  if (session === null || briefingOpen) {
    return null;
  }
  if (session.objective === null) {
    return "objective";
  }
  if (manual !== null) {
    return manual;
  }
  const allowed = new Set(session.allowedActions);
  if (allowed.has("apply-override")) {
    return "override";
  }
  if (allowed.has("approve-plan")) {
    return "approval";
  }
  return null;
}

const STEP_STATE_TEXT: Record<Step["state"], string> = {
  done: "Completed:",
  current: "Current step:",
  pending: "Not started:",
};

type Step = {
  key: string;
  ordinal: number;
  title: string;
  note: string;
  state: "done" | "current" | "pending";
};

function buildSteps(session: ExerciseSession, checkpointCount: number): Step[] {
  const steps: Step[] = [
    {
      key: "objective",
      ordinal: 1,
      title: "Choose an objective",
      note:
        session.objective === null
          ? "Not chosen yet"
          : humanize(session.objective),
      state: session.objective === null ? "current" : "done",
    },
  ];

  for (let index = 0; index < checkpointCount; index += 1) {
    const isCurrent =
      session.objective !== null && index === session.checkpointIndex;
    steps.push({
      key: `checkpoint-${index}`,
      ordinal: index + 2,
      title:
        index === session.checkpointIndex
          ? session.currentCheckpoint.title
          : checkpointTitle(index),
      note:
        index < session.checkpointIndex
          ? "Planned and passed"
          : isCurrent
            ? session.latestPlan === null
              ? "Plan not generated"
              : "Plan ready to review"
            : "Not reached",
      state:
        index < session.checkpointIndex
          ? "done"
          : isCurrent
            ? "current"
            : "pending",
    });
  }

  steps.push({
    key: "debrief",
    ordinal: checkpointCount + 2,
    title: "Sign off and debrief",
    note:
      session.status === "completed"
        ? "Recorded"
        : "Needs your name and a reason",
    state: session.status === "completed" ? "done" : "pending",
  });

  return steps;
}

// Titles for checkpoints the session has not served yet. The current one always
// uses the title the API sent.
function checkpointTitle(index: number): string {
  return ["Initial allocation", "Cascading disruption", "Shelter field report"][
    index
  ] ?? `Checkpoint ${index + 1}`;
}

function phaseLabel(session: ExerciseSession): string {
  if (session.status === "completed") {
    return "COMPLETE";
  }
  if (session.objective === null) {
    return "SITUATION";
  }
  const allowed = new Set(session.allowedActions);
  if (allowed.has("generate-plan")) {
    return "READY TO PLAN";
  }
  if (allowed.has("apply-override")) {
    return "FIELD REPORT";
  }
  if (allowed.has("approve-plan")) {
    return "AWAITING SIGN-OFF";
  }
  return "PLAN READY";
}

function phaseTone(session: ExerciseSession): "active" | "done" | undefined {
  if (session.status === "completed") {
    return "done";
  }
  return session.objective === null ? undefined : "active";
}

function coverageLine(plan: ExerciseSession["latestPlan"]): string {
  if (!plan) {
    return "Plan ready";
  }
  const total = plan.coveredTaskIds.length + plan.uncoveredTaskIds.length;
  return plan.uncoveredTaskIds.length === 0
    ? `Plan covers all ${total} tasks`
    : `Plan covers ${plan.coveredTaskIds.length} of ${total} tasks`;
}

function errorMessage(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null;
  }
  if (error instanceof ApiClientError) {
    return error.code === "exercise_version_conflict" ||
      error.code === "exercise_transition_invalid"
      ? `${error.message}. The workspace has been resynchronised — try again.`
      : error.message;
  }
  return "Something went wrong. Try again.";
}

function readString(
  source: Record<string, unknown> | undefined,
  key: string,
): string | null {
  const value = source?.[key];
  return typeof value === "string" ? value : null;
}

function readStoredSessionId(): string | null {
  try {
    return window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredSessionId(id: string): void {
  try {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    // A blocked storage API must not stop the exercise.
  }
}

function clearStoredSessionId(): void {
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Ignored for the same reason.
  }
}

export { SESSION_STORAGE_KEY };
