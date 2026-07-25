import { useMemo, useState } from "react";

import type {
  ExerciseDebrief,
  ExerciseMetadata,
  ExerciseObjective,
  ExercisePlan,
  ExerciseSession,
  SandboxPlan,
  SandboxPlanRequest,
  SandboxPriorityPreset,
} from "../api/exerciseTypes";
import { AuditTimeline } from "./DetailDrawer";
import {
  describeChange,
  describeConstraint,
  formatMinutes,
  humanize,
  OBJECTIVE_COPY,
  resourceLabel,
  roadLabel,
  taskLabel,
  windLabel,
  type NameBook,
} from "./language";

export type DebriefPanelProps = {
  session: ExerciseSession;
  metadata: ExerciseMetadata;
  debrief: ExerciseDebrief;
  sandboxResult: SandboxPlan | null;
  sandboxPending: boolean;
  sandboxError: string | null;
  book: NameBook;
  onRunSandbox: (request: SandboxPlanRequest) => void;
  onRestart: () => void;
};

/** Deliverables 9 and 10 — the record of what happened, then room to explore it. */
export function DebriefPanel({
  session,
  metadata,
  debrief,
  sandboxResult,
  sandboxPending,
  sandboxError,
  book,
  onRunSandbox,
  onRestart,
}: DebriefPanelProps) {
  const [view, setView] = useState<"debrief" | "sandbox">("debrief");

  return (
    <div className="wf-centre">
      <main className="wf-sheet" aria-labelledby="wf-debrief-title">
        <p className="wf-sheet__eyebrow">EXERCISE COMPLETE · {session.callsign}</p>
        <h1 className="wf-sheet__title" id="wf-debrief-title">
          {view === "debrief" ? "Debrief" : "Planning sandbox"}
        </h1>

        <div className="wf-tabs" role="tablist" style={{ marginTop: 16 }}>
          <button
            type="button"
            role="tab"
            className="wf-tab"
            aria-selected={view === "debrief"}
            onClick={() => setView("debrief")}
          >
            What you decided
          </button>
          <button
            type="button"
            role="tab"
            className="wf-tab"
            aria-selected={view === "sandbox"}
            onClick={() => setView("sandbox")}
          >
            Planning sandbox
          </button>
        </div>

        <div style={{ marginTop: 18 }}>
          {view === "debrief" ? (
            <DebriefBody
              session={session}
              debrief={debrief}
              book={book}
              onRestart={onRestart}
            />
          ) : (
            <SandboxBody
              session={session}
              metadata={metadata}
              debrief={debrief}
              book={book}
              result={sandboxResult}
              pending={sandboxPending}
              error={sandboxError}
              onRun={onRunSandbox}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function DebriefBody({
  session,
  debrief,
  book,
  onRestart,
}: {
  session: ExerciseSession;
  debrief: ExerciseDebrief;
  book: NameBook;
  onRestart: () => void;
}) {
  const finalPlan = debrief.finalPlan.outputData;
  const approval = debrief.events.find(
    (event) => event.eventType === "exercise.plan-approved",
  );
  const objective = session.objective;

  return (
    <>
      <div className="wf-grid-2">
        <div className="wf-metric">
          <p className="wf-metric__value">
            {finalPlan.coveredTaskIds.length}/
            {finalPlan.coveredTaskIds.length + finalPlan.uncoveredTaskIds.length}
          </p>
          <p className="wf-metric__label">tasks covered in the plan you signed</p>
        </div>
        <div className="wf-metric">
          <p className="wf-metric__value">{debrief.plans.length}</p>
          <p className="wf-metric__label">plans generated across the exercise</p>
        </div>
      </div>

      {objective !== null && (
        <div className="wf-note" data-tone="neutral" style={{ marginTop: 12 }}>
          <strong>You planned for: {OBJECTIVE_COPY[objective].title}</strong>
          {OBJECTIVE_COPY[objective].plain} {OBJECTIVE_COPY[objective].tradeoff}
        </div>
      )}

      {finalPlan.uncoveredTaskIds.length > 0 && (
        <div className="wf-note" data-tone="alert" style={{ marginTop: 12 }}>
          <strong>What you left uncovered</strong>
          {finalPlan.uncoveredTaskIds
            .map((taskId) => taskLabel(taskId, book))
            .join(" · ")}
          . This was not a mistake — the exercise never gives you enough units.
          What matters is that the reason is on the record.
        </div>
      )}

      {approval?.note && (
        <>
          <h2 className="wf-section" style={{ marginTop: 22 }}>
            YOUR REASON, AS RECORDED
          </h2>
          <blockquote className="wf-timeline__note" style={{ margin: 0 }}>
            {approval.note}
            <footer className="wf-card__meta" style={{ marginTop: 6 }}>
              — {approval.displayName ?? approval.actorCallsign},{" "}
              {new Date(approval.occurredAt).toLocaleString("en-GB")}
            </footer>
          </blockquote>
        </>
      )}

      <h2 className="wf-section" style={{ marginTop: 22 }}>
        CHECKPOINT BY CHECKPOINT
      </h2>
      <div className="wf-stack">
        {debrief.plans.map((plan) => (
          <CheckpointSummary key={plan.id} plan={plan} book={book} />
        ))}
      </div>

      <h2 className="wf-section" style={{ marginTop: 22 }}>
        AUDIT TRAIL
      </h2>
      <AuditTimeline events={debrief.events} book={book} />

      <div className="wf-actions">
        <button type="button" className="wf-secondary" onClick={onRestart}>
          Run the exercise again
        </button>
        <a className="wf-dock__hint" href="/monitor">
          Open the Live Monitor
        </a>
      </div>
    </>
  );
}

function CheckpointSummary({
  plan,
  book,
}: {
  plan: ExercisePlan;
  book: NameBook;
}) {
  const output = plan.outputData;
  return (
    <article className="wf-card">
      <div className="wf-card__head">
        <span className="wf-card__name">{humanize(plan.checkpointKey)}</span>
        <span
          className="wf-card__eta"
          style={{
            color: output.uncoveredTaskIds.length === 0 ? "#5fd08a" : "#f5b02e",
          }}
        >
          {output.coveredTaskIds.length}/
          {output.coveredTaskIds.length + output.uncoveredTaskIds.length} covered
        </span>
      </div>
      <p className="wf-card__meta">
        {output.assignments
          .map(
            (assignment) =>
              `${resourceLabel(assignment.resourceId, book)} → ${taskLabel(
                assignment.taskId,
                book,
              )}`,
          )
          .join(" · ") || "No assignments"}
      </p>
      {output.uncoveredTaskIds.length > 0 && (
        <p className="wf-card__meta" style={{ color: "#f2b09a" }}>
          Left uncovered:{" "}
          {output.uncoveredTaskIds
            .map((taskId) => taskLabel(taskId, book))
            .join(", ")}
        </p>
      )}
    </article>
  );
}

function SandboxBody({
  session,
  metadata,
  debrief,
  book,
  result,
  pending,
  error,
  onRun,
}: {
  session: ExerciseSession;
  metadata: ExerciseMetadata;
  debrief: ExerciseDebrief;
  book: NameBook;
  result: SandboxPlan | null;
  pending: boolean;
  error: string | null;
  onRun: (request: SandboxPlanRequest) => void;
}) {
  // Every control below is bounded by what the API says it will accept.
  const { checkpointKeys, closureEdgeIds, windPresets, priorityPresets } =
    metadata.sandbox;

  const [checkpointKey, setCheckpointKey] = useState(
    () => checkpointKeys.at(-1) ?? "",
  );
  const [objective, setObjective] = useState<ExerciseObjective>(
    session.objective ?? "protect-critical-services",
  );
  const [windPreset, setWindPreset] = useState<string>(
    () => windPresets[0]?.key ?? "",
  );
  const [closed, setClosed] = useState<readonly string[]>([]);
  const [unavailable, setUnavailable] = useState<readonly string[]>([]);
  const [priorities, setPriorities] = useState<
    Record<string, SandboxPriorityPreset["key"]>
  >({});

  const tasksInCheckpoint = useMemo(
    () =>
      [
        ...new Set(
          debrief.plans
            .filter((plan) => plan.checkpointKey === checkpointKey)
            .flatMap((plan) =>
              plan.outputData.taskCoverage.map((entry) => entry.taskId),
            ),
        ),
      ],
    [debrief.plans, checkpointKey],
  );

  return (
    <>
      <p className="wf-prose wf-prose--muted">
        Nothing here is recorded. Re-run any checkpoint under different
        assumptions to see how the plan would have changed — your signed decision
        and its audit trail stay exactly as they are.
      </p>

      <div className="wf-grid-2" style={{ marginTop: 16 }}>
        <label className="wf-field" style={{ marginTop: 0 }}>
          <span className="wf-field__label">CHECKPOINT</span>
          <select
            className="wf-select"
            value={checkpointKey}
            onChange={(event) => setCheckpointKey(event.target.value)}
          >
            {checkpointKeys.map((key) => (
              <option key={key} value={key}>
                {humanize(key)}
              </option>
            ))}
          </select>
        </label>
        <label className="wf-field" style={{ marginTop: 0 }}>
          <span className="wf-field__label">OBJECTIVE</span>
          <select
            className="wf-select"
            value={objective}
            onChange={(event) =>
              setObjective(event.target.value as ExerciseObjective)
            }
          >
            {metadata.objectives.map((key) => (
              <option key={key} value={key}>
                {OBJECTIVE_COPY[key as ExerciseObjective]?.title ?? humanize(key)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="wf-field">
        <span className="wf-field__label">WEATHER ASSUMPTION</span>
        <select
          className="wf-select"
          value={windPreset}
          onChange={(event) => setWindPreset(event.target.value)}
        >
          {windPresets.map((preset) => (
            <option key={preset.key} value={preset.key}>
              {humanize(preset.key)} — {windLabel(preset.disruption)}
            </option>
          ))}
        </select>
      </label>

      {closureEdgeIds.length > 0 && (
        <fieldset
          className="wf-field"
          style={{ border: "none", padding: 0, margin: "12px 0 0" }}
        >
          <legend className="wf-field__label">ROAD CLOSURES</legend>
          {closureEdgeIds.map((edgeId) => (
            <label
              key={edgeId}
              className="wf-prose"
              style={{ display: "flex", gap: 8, alignItems: "center" }}
            >
              <input
                type="checkbox"
                checked={closed.includes(edgeId)}
                onChange={(event) =>
                  setClosed((previous) =>
                    event.target.checked
                      ? [...previous, edgeId]
                      : previous.filter((item) => item !== edgeId),
                  )
                }
              />
              Close {roadLabel(edgeId, book)}
            </label>
          ))}
        </fieldset>
      )}

      <fieldset
        className="wf-field"
        style={{ border: "none", padding: 0, margin: "12px 0 0" }}
      >
        <legend className="wf-field__label">TAKE A UNIT OUT OF SERVICE</legend>
        {metadata.resources.map((resource) => (
          <label
            key={resource.resourceId}
            className="wf-prose"
            style={{ display: "flex", gap: 8, alignItems: "center" }}
          >
            <input
              type="checkbox"
              checked={unavailable.includes(resource.resourceId)}
              onChange={(event) =>
                setUnavailable((previous) =>
                  event.target.checked
                    ? [...previous, resource.resourceId]
                    : previous.filter((item) => item !== resource.resourceId),
                )
              }
            />
            {resourceLabel(resource.resourceId, book)}
          </label>
        ))}
      </fieldset>

      {tasksInCheckpoint.length > 0 && (
        <fieldset
          className="wf-field"
          style={{ border: "none", padding: 0, margin: "12px 0 0" }}
        >
          <legend className="wf-field__label">RAISE A TASK'S PRIORITY</legend>
          <div className="wf-stack">
            {tasksInCheckpoint.map((taskId) => (
              <label
                key={taskId}
                className="wf-prose"
                style={{ display: "flex", gap: 8, alignItems: "center" }}
              >
                <span style={{ flex: 1 }}>{taskLabel(taskId, book)}</span>
                <select
                  className="wf-select"
                  style={{ width: 130 }}
                  value={priorities[taskId] ?? priorityPresets[0]?.key ?? "standard"}
                  onChange={(event) =>
                    setPriorities((previous) => ({
                      ...previous,
                      [taskId]: event.target
                        .value as SandboxPriorityPreset["key"],
                    }))
                  }
                >
                  {priorityPresets.map((preset) => (
                    <option key={preset.key} value={preset.key}>
                      {humanize(preset.key)} (×{preset.multiplier})
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {error !== null && (
        <p className="wf-error" role="alert">
          {error}
        </p>
      )}

      <div className="wf-actions">
        <button
          type="button"
          className="wf-primary"
          disabled={pending || checkpointKey === ""}
          onClick={() =>
            onRun({
              expectedVersion: session.version,
              checkpointKey,
              objective,
              closedEdgeIds: closed,
              windPreset,
              unavailableResourceIds: unavailable,
              // Only tasks that exist in the selected checkpoint; the server
              // rejects the whole request for any identifier it does not know.
              taskPriorityPresets: Object.fromEntries(
                Object.entries(priorities).filter(([taskId, preset]) =>
                  tasksInCheckpoint.includes(taskId) && preset !== "standard",
                ),
              ),
              lockedAssignments: [],
            })
          }
        >
          {pending ? "Planning…" : "Run this what-if"}
        </button>
      </div>

      {result && <SandboxResult result={result} book={book} />}
    </>
  );
}

function SandboxResult({
  result,
  book,
}: {
  result: SandboxPlan;
  book: NameBook;
}) {
  const output = result.output;
  const wind = windFromInput(result.input);
  return (
    <section style={{ marginTop: 22 }} aria-label="What-if result">
      <h2 className="wf-section">WHAT WOULD HAVE HAPPENED</h2>
      <div className="wf-grid-2" style={{ marginTop: 8 }}>
        <div className="wf-metric">
          <p className="wf-metric__value">
            {output.coveredTaskIds.length}/
            {output.coveredTaskIds.length + output.uncoveredTaskIds.length}
          </p>
          <p className="wf-metric__label">tasks covered</p>
        </div>
        <div className="wf-metric">
          <p className="wf-metric__value">
            {output.objectiveComponents.objectiveValue}
          </p>
          <p className="wf-metric__label">objective score — lower is better</p>
        </div>
      </div>
      {wind !== null && (
        <p className="wf-card__meta" style={{ marginTop: 8 }}>
          Planned against {wind}.
        </p>
      )}
      <div className="wf-stack" style={{ marginTop: 12 }}>
        {output.assignments.map((assignment) => (
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
          </article>
        ))}
      </div>
      {output.explanation.changes.length > 0 && (
        <div className="wf-stack" style={{ marginTop: 12 }}>
          {output.explanation.changes.map((change, index) => {
            const plain = describeChange(change, book);
            return (
              <div
                className="wf-note"
                data-tone={plain.tone}
                key={`${plain.code}-${index}`}
              >
                <strong>{plain.headline}</strong>
                {plain.detail}
              </div>
            );
          })}
        </div>
      )}
      {output.bindingConstraints.length > 0 && (
        <>
          <h3 className="wf-section" style={{ marginTop: 16 }}>
            WHAT BLOCKED IT
          </h3>
          <div className="wf-stack">
            {output.bindingConstraints.slice(0, 8).map((constraint) => (
              <div className="wf-note" data-tone="neutral" key={constraint}>
                {describeConstraint(constraint, book)}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}


function windFromInput(input: Record<string, unknown>): string | null {
  const wind = input.wind;
  if (typeof wind !== "object" || wind === null) {
    return null;
  }
  const record = wind as Record<string, unknown>;
  const speed = record.windSpeedMps ?? record.speedMps;
  const direction = record.windDirectionDegrees ?? record.directionDegrees;
  if (typeof speed !== "number" || typeof direction !== "number") {
    return null;
  }
  return windLabel({
    windSpeedMps: speed,
    windDirectionDegrees: direction,
    closedEdgeIds: [],
    provenance: "exercise",
  });
}

