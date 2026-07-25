import { useEffect, useId, useRef, useState } from "react";

import type {
  ExerciseCheckpoint,
  ExerciseFieldReport,
  ExerciseObjective,
  PlanOutput,
} from "../api/exerciseTypes";
import {
  OBJECTIVE_COPY,
  resourceLabel,
  taskLabel,
  type NameBook,
  type PlainChange,
} from "./language";

const OBJECTIVE_ORDER: ExerciseObjective[] = [
  "protect-critical-services",
  "fastest-response",
  "maximize-population-coverage",
];

export type ObjectivePanelProps = {
  current: ExerciseObjective | null;
  pending: boolean;
  replanning: boolean;
  onChoose: (objective: ExerciseObjective) => void;
  onClose: (() => void) | null;
};

/** Deliverable 3. Each option states what it optimises and what it gives up. */
export function ObjectivePanel({
  current,
  pending,
  replanning,
  onChoose,
  onClose,
}: ObjectivePanelProps) {
  return (
    <section
      className="wf-panel wf-panel--above-dock"
      role="dialog"
      aria-label="Choose an objective"
    >
      <div className="wf-panel__head">
        <h2 className="wf-panel__title">
          {replanning ? "Change the objective" : "Choose an objective"}
        </h2>
        {onClose !== null && (
          <button
            type="button"
            className="wf-close"
            onClick={onClose}
            aria-label="Close objective picker"
          >
            ✕
          </button>
        )}
      </div>
      <p className="wf-dock__hint" style={{ marginBottom: 12 }}>
        {replanning
          ? "Choosing a different objective discards this checkpoint's plan and lets you run it again."
          : "This is the rule the planner follows when two tasks want the same unit. You can change it later."}
      </p>
      <div className="wf-stack">
        {OBJECTIVE_ORDER.map((objective) => {
          const copy = OBJECTIVE_COPY[objective];
          return (
            <button
              key={objective}
              type="button"
              className="wf-choice"
              aria-pressed={current === objective}
              disabled={pending}
              onClick={() => onChoose(objective)}
            >
              <span className="wf-choice__title">{copy.title}</span>
              <span className="wf-choice__plain">{copy.plain}</span>
              <span className="wf-choice__tradeoff">
                Trade-off: {copy.tradeoff}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export type ChangeBriefingProps = {
  checkpoint: ExerciseCheckpoint;
  changes: readonly PlainChange[];
  index: number;
  total: number;
  onDismiss: () => void;
};

/**
 * The cinematic beat, kept restrained: the workspace dims, the checkpoint's
 * changes arrive one at a time, and the operator has to acknowledge them before
 * the plan is actionable. Reduced-motion users get the same content instantly.
 */
export function ChangeBriefing({
  checkpoint,
  changes,
  index,
  total,
  onDismiss,
}: ChangeBriefingProps) {
  const dismissRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    dismissRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismiss();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  return (
    <div className="wf-veil">
      <section
        className="wf-brief"
        role="dialog"
        aria-modal="true"
        aria-labelledby="wf-brief-title"
      >
        <p className="wf-brief__eyebrow">
          CHECKPOINT {index + 1} OF {total} ·{" "}
          {index === 0 ? "WHAT THE PLANNER FOUND" : "WHAT CHANGED"}
        </p>
        <h2 className="wf-brief__title" id="wf-brief-title">
          {checkpoint.title}
        </h2>
        <p className="wf-brief__summary">{checkpoint.situationSummary}</p>
        <div className="wf-brief__list">
          {changes.map((change, position) => (
            <article
              key={`${change.code}-${position}`}
              className="wf-brief__item wf-note"
              data-tone={change.tone}
              style={{ animationDelay: `${0.12 + position * 0.09}s` }}
            >
              <strong>{change.headline}</strong>
              {change.detail}
            </article>
          ))}
        </div>
        <div className="wf-brief__foot">
          <p className="wf-brief__count">
            {changes.length} {changes.length === 1 ? "point" : "points"}{" "}
            {index === 0 ? "to note" : "changed since the last plan"}
          </p>
          <button
            type="button"
            className="wf-primary"
            ref={dismissRef}
            onClick={onDismiss}
          >
            Review the plan
          </button>
        </div>
      </section>
    </div>
  );
}

export type OverridePanelProps = {
  report: ExerciseFieldReport;
  plan: PlanOutput | null;
  book: NameBook;
  pending: boolean;
  onApply: (resourceId: string, taskId: string) => void;
};

/**
 * Deliverable 7. The field report is a judgement the solver cannot see, so the
 * override is presented as exactly that: a considered exception, with its cost
 * shown before it is applied.
 */
export function OverridePanel({
  report,
  plan,
  book,
  pending,
  onApply,
}: OverridePanelProps) {
  const task = book.tasks.get(report.taskId);
  const candidates = (plan?.candidateFacts ?? []).filter(
    (fact) => fact.taskId === report.taskId && fact.eligible,
  );
  const [resourceId, setResourceId] = useState(
    () => candidates[0]?.resourceId ?? "",
  );
  const selectId = useId();

  const holding = plan?.assignments.find(
    (assignment) => assignment.resourceId === resourceId,
  );

  return (
    <section
      className="wf-panel wf-panel--above-dock"
      role="dialog"
      aria-label="Field report override"
    >
      <div className="wf-panel__head">
        <h2 className="wf-panel__title">Field report</h2>
      </div>
      <div className="wf-note" data-tone="caution" style={{ marginTop: 10 }}>
        <strong>{taskLabel(report.taskId, book)}</strong>
        {report.message}
      </div>
      <p className="wf-prose" style={{ marginTop: 12 }}>
        The planner left this task uncovered because it scored lower than the
        work it chose instead. A field report is information the planner does not
        have. If you accept it, pin a unit to the task and the plan will be
        rebuilt around that decision.
      </p>

      {candidates.length === 0 ? (
        <p className="wf-error" role="alert">
          No unit in this checkpoint can take{" "}
          {taskLabel(report.taskId, book)}
          {task ? ` — it needs ${task.requiredCapacity} units of ${task.requiredCapability.replace(/-/g, " ")}.` : "."}
        </p>
      ) : (
        <>
          <label className="wf-field" htmlFor={selectId}>
            <span className="wf-field__label">PIN A UNIT TO THIS TASK</span>
            <select
              id={selectId}
              className="wf-select"
              value={resourceId}
              onChange={(event) => setResourceId(event.target.value)}
              disabled={pending}
            >
              {candidates.map((candidate) => (
                <option key={candidate.resourceId} value={candidate.resourceId}>
                  {resourceLabel(candidate.resourceId, book)}
                </option>
              ))}
            </select>
          </label>
          {holding && (
            <p className="wf-field__hint">
              {resourceLabel(resourceId, book)} is currently on{" "}
              {taskLabel(holding.taskId, book)}. Pinning it here will take it off
              that task.
            </p>
          )}
          <div className="wf-actions">
            <button
              type="button"
              className="wf-primary"
              disabled={pending || resourceId === ""}
              onClick={() => onApply(resourceId, report.taskId)}
            >
              {pending ? "Replanning…" : "Apply the override and replan"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export type ApprovalPanelProps = {
  callsign: string;
  plan: PlanOutput | null;
  book: NameBook;
  pending: boolean;
  error: string | null;
  onApprove: (displayName: string, note: string) => void;
};

/** Deliverable 8. A name and a reason are both required to sign the plan off. */
export function ApprovalPanel({
  callsign,
  plan,
  book,
  pending,
  error,
  onApprove,
}: ApprovalPanelProps) {
  const [displayName, setDisplayName] = useState("");
  const [note, setNote] = useState("");
  const nameId = useId();
  const noteId = useId();

  const uncovered = plan?.uncoveredTaskIds ?? [];
  const ready = displayName.trim().length > 0 && note.trim().length > 0;

  return (
    <section
      className="wf-panel wf-panel--above-dock"
      role="dialog"
      aria-label="Approve the plan"
    >
      <div className="wf-panel__head">
        <h2 className="wf-panel__title">Sign off on this plan</h2>
      </div>
      <p className="wf-dock__hint" style={{ marginBottom: 4 }}>
        Recorded against callsign {callsign}. This closes the exercise.
      </p>

      {uncovered.length > 0 && (
        <div className="wf-note" data-tone="alert" style={{ marginTop: 12 }}>
          <strong>
            You are approving a plan that leaves{" "}
            {uncovered.length === 1 ? "one task" : `${uncovered.length} tasks`}{" "}
            uncovered
          </strong>
          {uncovered.map((taskId) => taskLabel(taskId, book)).join(" · ")}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !pending) {
            onApprove(displayName.trim(), note.trim());
          }
        }}
      >
        <label className="wf-field" htmlFor={nameId}>
          <span className="wf-field__label">YOUR NAME</span>
          <input
            id={nameId}
            className="wf-input"
            value={displayName}
            maxLength={120}
            onChange={(event) => setDisplayName(event.target.value)}
            disabled={pending}
            autoComplete="off"
          />
        </label>
        <label className="wf-field" htmlFor={noteId}>
          <span className="wf-field__label">WHY THIS PLAN</span>
          <textarea
            id={noteId}
            className="wf-textarea"
            value={note}
            maxLength={2000}
            onChange={(event) => setNote(event.target.value)}
            disabled={pending}
            placeholder="What you accepted, what you gave up, and why."
          />
          <span className="wf-field__hint">
            Written into the audit trail exactly as typed. {note.trim().length}{" "}
            of 2000 characters.
          </span>
        </label>
        {error !== null && (
          <p className="wf-error" role="alert">
            {error}
          </p>
        )}
        <div className="wf-actions wf-actions--end">
          <button
            type="submit"
            className="wf-primary"
            disabled={!ready || pending}
          >
            {pending ? "Recording…" : "Approve and record"}
          </button>
        </div>
      </form>
    </section>
  );
}

