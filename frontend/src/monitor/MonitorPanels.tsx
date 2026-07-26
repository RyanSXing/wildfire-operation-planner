import { useEffect, useRef } from "react";

import type { IncidentSummary } from "../api/types";
import { STEP_STATE_TEXT, type MonitorStep } from "./monitorSteps";

/**
 * The surfaces the decision exercise established, applied to live incidents:
 * a safety gate before anything else, a progress rail, and a briefing that
 * makes a plan change something you acknowledge rather than something you have
 * to spot.
 */

export function MonitorSteps({ steps }: { steps: readonly MonitorStep[] }) {
  return (
    <>
      <p className="wf-label">YOUR PROGRESS</p>
      <ol className="wf-steps wf-steps--compact">
        {steps.map((step) => (
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
              <span className="wf-visually-hidden">
                {STEP_STATE_TEXT[step.state]}
              </span>
              <span className="wf-step__title">{step.title}</span>
              <span className="wf-step__note">{step.note}</span>
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}

export type MonitorIntroProps = {
  incidents: readonly IncidentSummary[];
  onStart: () => void;
};

/** The same disclosure the exercise makes, for live data rather than a replay. */
export function MonitorIntro({ incidents, onStart }: MonitorIntroProps) {
  return (
    <div className="wf-centre">
      <main className="wf-sheet" aria-labelledby="wf-monitor-intro-title">
        <p className="wf-sheet__eyebrow">
          PORTFOLIO SIMULATION · NOT AN OPERATIONAL SYSTEM
        </p>
        <h1 className="wf-sheet__title" id="wf-monitor-intro-title">
          Live command centre
        </h1>
        <p className="wf-sheet__lede">
          Plan a response against the incidents currently in the system: choose
          one, allocate the units, change the assumptions, and record a decision
          that goes into the audit trail.
        </p>

        <div className="wf-note" data-tone="alert" style={{ marginTop: 20 }}>
          <strong>Read this before you start</strong>
          Portfolio simulation only. Do not use for emergency or life-safety
          decisions.
        </div>

        <h2 className="wf-section" style={{ marginTop: 24 }}>
          WHERE THE DATA COMES FROM
        </h2>
        <dl className="wf-kv">
          <div>
            <dt>Real and observed</dt>
            <dd>
              Incident perimeters, satellite detections, weather, the road
              network, and the exposed places — all from the ingested feeds, with
              their freshness shown on every screen.
            </dd>
          </div>
          <div>
            <dt>Simulated</dt>
            <dd>
              Every response unit and its position. Resource locations are
              invented so a plan can be made; they are not real deployments.
            </dd>
          </div>
          <div>
            <dt>In the system now</dt>
            <dd>
              {incidents.length}{" "}
              {incidents.length === 1 ? "incident" : "incidents"}
              {incidents.length > 0
                ? `, highest priority ${incidents
                    .map((incident) => incident.name)
                    .slice(0, 1)
                    .join("")}`
                : ""}
              .
            </dd>
          </div>
        </dl>

        <div className="wf-actions">
          <button type="button" className="wf-primary" onClick={onStart}>
            I understand — open the command centre
          </button>
          <a className="wf-dock__hint" href="/">
            Open the decision exercise instead
          </a>
        </div>
      </main>
    </div>
  );
}

export type PlanChangeBriefingProps = {
  title: string;
  summary: string;
  changes: readonly { headline: string; detail: string; tone: string }[];
  onDismiss: () => void;
};

/** The exercise's change briefing, for a newly generated allocation. */
export function PlanChangeBriefing({
  title,
  summary,
  changes,
  onDismiss,
}: PlanChangeBriefingProps) {
  const dismissRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLElement>(null);

  useEffect(() => {
    dismissRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismiss();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = sheetRef.current?.querySelectorAll<HTMLElement>(
        "a[href], button:not(:disabled), input, select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      if (!focusable || focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !sheetRef.current?.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
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
        aria-labelledby="wf-monitor-brief-title"
        ref={sheetRef}
      >
        <p className="wf-brief__eyebrow">WHAT THIS PLAN CHANGED</p>
        <h2 className="wf-brief__title" id="wf-monitor-brief-title">
          {title}
        </h2>
        <p className="wf-brief__summary">{summary}</p>
        <div className="wf-brief__list">
          {changes.map((change, index) => (
            <article
              key={`${change.headline}-${index}`}
              className="wf-brief__item wf-note"
              data-tone={change.tone}
              style={{ animationDelay: `${0.12 + index * 0.09}s` }}
            >
              <strong>{change.headline}</strong>
              {change.detail}
            </article>
          ))}
        </div>
        <div className="wf-brief__foot">
          <p className="wf-brief__count">
            {changes.length} {changes.length === 1 ? "change" : "changes"} from
            the previous allocation
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
