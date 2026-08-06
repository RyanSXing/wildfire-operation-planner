import { useId } from "react";

import type {
  Recommendation,
  ScenarioVersion,
  ScenarioVersionCreateRequest,
  SimulatedResource,
} from "../api/types";
import type { RoadEdge } from "../api/types";
import {
  useDecisionForm,
  type DecisionOptionInput,
} from "../features/decisions/useDecisionForm";
import { useScenarioDraft } from "../features/scenarios/useScenarioDraft";
import { humanize, labelFor } from "./language";

/**
 * The monitor's own presentation for the two forms the old dashboard owned.
 *
 * Both render the exercise's language: choice rows that state what an option
 * means, and a sign-off that asks for a name and a reason rather than a bare
 * note. The behaviour underneath is untouched — these are renderers over
 * useScenarioDraft and useDecisionForm, whose suites still pin it.
 */

export type AssumptionsPanelProps = {
  roadEdges: readonly RoadEdge[];
  resources: readonly SimulatedResource[];
  version: ScenarioVersion | null;
  busy: boolean;
  disabled: boolean;
  roadNames: ReadonlyMap<string, string>;
  resourceLabels: Readonly<Record<string, string>>;
  onSubmit: (request: ScenarioVersionCreateRequest) => void;
};

export function AssumptionsPanel({
  roadEdges,
  resources,
  version,
  busy,
  disabled,
  roadNames,
  resourceLabels,
  onSubmit,
}: AssumptionsPanelProps) {
  const draft = useScenarioDraft({
    roadEdges,
    resources,
    version,
    busy,
    disabled,
    onSubmit,
  });
  const speedId = useId();
  const directionId = useId();

  return (
    <form
      aria-label="Scenario version editor"
      onSubmit={draft.submit}
      className="wf-form"
    >
      <h3 className="wf-section">ROADS</h3>
      {draft.roads.length === 0 ? (
        <p className="wf-prose wf-prose--muted">
          No road segments are available to close.
        </p>
      ) : (
        <fieldset className="wf-choices" aria-label="Road closures">
          {draft.roads.map((road) => (
            <label className="wf-choice" key={road.edgeId} data-on={road.closed}>
              <input
                type="checkbox"
                checked={road.closed}
                disabled={draft.fieldsDisabled}
                onChange={(event) =>
                  draft.toggleRoad(road.edgeId, event.currentTarget.checked)
                }
              />
              <span>
                <span className="wf-choice__title">
                  {roadNames.get(road.edgeId) ?? road.label ?? "Road segment"}
                </span>
                <span className="wf-choice__plain">
                  {road.closed
                    ? "Closed — units must route around it."
                    : "Open — units may route through it."}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      <h3 className="wf-section" style={{ marginTop: 18 }}>
        UNITS
      </h3>
      <fieldset className="wf-choices" aria-label="Resource availability">
        {draft.resourceDrafts.map((resource) => (
          <label
            className="wf-choice"
            key={resource.resourceId}
            data-on={!resource.available}
          >
            <input
              type="checkbox"
              checked={!resource.available}
              disabled={draft.fieldsDisabled}
              onChange={(event) =>
                draft.setResourceAvailable(
                  resource.resourceId,
                  !event.currentTarget.checked,
                )
              }
            />
            <span>
              <span className="wf-choice__title">
                {labelFor(resourceLabels, resource.resourceId)}
              </span>
              <span className="wf-choice__plain">
                {resource.available
                  ? `${humanize(resource.resourceType)} · available to assign`
                  : `${humanize(resource.resourceType)} · out of service, cannot be assigned`}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      <h3 className="wf-section" style={{ marginTop: 18 }}>
        WEATHER
      </h3>
      {draft.multipleWeather ? (
        <p className="wf-prose wf-prose--muted">
          This version carries several weather observations; they are kept as
          they are.
        </p>
      ) : (
        <fieldset aria-label="Weather override">
          <label className="wf-choice" data-on={draft.weatherMode === "preserve"}>
            <input
              type="radio"
              name="weather-mode"
              checked={draft.weatherMode === "preserve"}
              disabled={draft.fieldsDisabled}
              onChange={() => draft.setWeatherMode("preserve")}
            />
            <span>
              <span className="wf-choice__title">Keep the observed weather</span>
              <span className="wf-choice__plain">
                Plan against what the feeds actually reported.
              </span>
            </span>
          </label>
          <label className="wf-choice" data-on={draft.weatherMode === "replace"}>
            <input
              type="radio"
              name="weather-mode"
              checked={draft.weatherMode === "replace"}
              disabled={draft.fieldsDisabled}
              onChange={() => draft.setWeatherMode("replace")}
            />
            <span>
              <span className="wf-choice__title">Assume different wind</span>
              <span className="wf-choice__plain">
                Ask what the plan would be under conditions that have not been
                observed.
              </span>
            </span>
          </label>

          {draft.weatherMode === "replace" && (
            <div className="wf-grid-2" style={{ marginTop: 10 }}>
              <label className="wf-field" htmlFor={speedId}>
                <span className="wf-field__label">WIND SPEED (M/S)</span>
                <input
                  id={speedId}
                  className="wf-input"
                  value={draft.windSpeed}
                  disabled={draft.fieldsDisabled}
                  aria-describedby={
                    draft.weather.speedError ? draft.speedErrorId : undefined
                  }
                  aria-invalid={draft.weather.speedError ? true : undefined}
                  onChange={(event) => draft.setWindSpeed(event.currentTarget.value)}
                />
                {draft.weather.speedError && (
                  <span className="wf-error" id={draft.speedErrorId} role="alert">
                    {draft.weather.speedError}
                  </span>
                )}
              </label>
              <label className="wf-field" htmlFor={directionId}>
                <span className="wf-field__label">DIRECTION (DEGREES)</span>
                <input
                  id={directionId}
                  className="wf-input"
                  value={draft.windDirection}
                  disabled={draft.fieldsDisabled}
                  aria-describedby={
                    draft.weather.directionError
                      ? draft.directionErrorId
                      : undefined
                  }
                  aria-invalid={draft.weather.directionError ? true : undefined}
                  onChange={(event) =>
                    draft.setWindDirection(event.currentTarget.value)
                  }
                />
                {draft.weather.directionError && (
                  <span
                    className="wf-error"
                    id={draft.directionErrorId}
                    role="alert"
                  >
                    {draft.weather.directionError}
                  </span>
                )}
              </label>
            </div>
          )}
        </fieldset>
      )}

      <div className="wf-actions wf-actions--end">
        <button type="submit" className="wf-primary" disabled={draft.submitDisabled}>
          {busy ? "Saving…" : "Save scenario version"}
        </button>
      </div>
    </form>
  );
}

export type SignOffPanelProps = {
  recommendation: Recommendation;
  freshness: "current" | "stale";
  planningDisabled: boolean;
  resources: readonly DecisionOptionInput[];
  destinations: readonly DecisionOptionInput[];
  coverage: string;
  uncovered: readonly string[];
  onStale?: () => void;
  onDecisionRecorded?: () => void;
};

/** Sign-off in the exercise's terms: a name, a reason, and what you are accepting. */
export function SignOffPanel({
  recommendation,
  freshness,
  planningDisabled,
  resources,
  destinations,
  coverage,
  uncovered,
  onStale,
  onDecisionRecorded,
}: SignOffPanelProps) {
  const form = useDecisionForm({
    recommendation,
    freshness,
    planningDisabled,
    resources,
    destinations,
    onStale,
    onDecisionRecorded,
  });
  const noteId = useId();
  const hintId = useId();

  return (
    <>
      <p className="wf-dock__hint" style={{ marginBottom: 4 }}>
        {coverage}. This is recorded in the audit trail.
      </p>

      {uncovered.length > 0 && (
        <div className="wf-note" data-tone="alert" style={{ marginTop: 12 }}>
          <strong>
            You are deciding on a plan that leaves{" "}
            {uncovered.length === 1
              ? "one destination"
              : `${uncovered.length} destinations`}{" "}
            uncovered
          </strong>
          {uncovered.join(" · ")}
        </div>
      )}

      <fieldset className="wf-choices" style={{ marginTop: 12 }}>
        <legend className="wf-field__label">WHAT YOU ARE RECORDING</legend>
        {(
          [
            ["approve", "Approve", "Dispatch these units as planned."],
            ["reject", "Reject", "Record that this plan was not accepted."],
            ["edit", "Approve with changes", "Dispatch, but reassign some units first."],
          ] as const
        ).map(([action, title, plain]) => (
          <button
            key={action}
            type="button"
            className="wf-choice"
            aria-pressed={form.action === action}
            disabled={
              action === "reject" ? form.rejectDisabled : form.approveEditDisabled
            }
            onClick={() => form.open(action)}
          >
            <span className="wf-choice__title">{title}</span>
            <span className="wf-choice__plain">{plain}</span>
          </button>
        ))}
      </fieldset>

      {form.action !== null && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            form.submit();
          }}
        >
          {form.action === "edit" && (
            <fieldset className="wf-field" aria-label="Edited assignments">
              <legend className="wf-field__label">REASSIGN</legend>
              {form.assignments.map((assignment, index) => (
                <div className="wf-grid-2" key={index}>
                  <label className="wf-field">
                    <span className="wf-field__label">{`Resource ${index + 1}`}</span>
                    <select
                      className="wf-select"
                      value={assignment.resourceId}
                      disabled={form.activeFormDisabled}
                      onChange={(event) =>
                        form.setAssignmentResource(
                          index,
                          assignment,
                          event.currentTarget.value,
                        )
                      }
                    >
                      <option value="">Select resource</option>
                      {form.resourceOptions.map((resource) => (
                        <option value={resource.id} key={resource.id}>
                          {resource.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wf-field">
                    <span className="wf-field__label">{`Destination ${index + 1}`}</span>
                    <select
                      className="wf-select"
                      value={assignment.destinationId}
                      disabled={form.activeFormDisabled}
                      onChange={(event) =>
                        form.setAssignmentDestination(
                          index,
                          assignment,
                          event.currentTarget.value,
                        )
                      }
                    >
                      <option value="">Select destination</option>
                      {form.destinationOptions.map((destination) => (
                        <option value={destination.id} key={destination.id}>
                          {destination.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ))}
            </fieldset>
          )}

          <label className="wf-field" htmlFor={noteId}>
            <span className="wf-field__label">WHY THIS DECISION</span>
            <textarea
              id={noteId}
              className="wf-textarea"
              value={form.note}
              disabled={form.activeFormDisabled}
              aria-describedby={hintId}
              placeholder="What you accepted, what you gave up, and why."
              onChange={(event) => form.setNote(event.currentTarget.value)}
            />
          </label>
          <p className="wf-field__hint" id={hintId}>
            Written into the audit trail exactly as typed.
          </p>

          {form.validationError && (
            <p className="wf-error" role="alert">
              {form.validationError}
            </p>
          )}
          {form.requestError && (
            <p className="wf-error" role="alert">
              {form.requestError}
            </p>
          )}

          <div className="wf-actions wf-actions--end">
            <button
              type="button"
              className="wf-secondary"
              onClick={form.cancel}
              disabled={form.createDecision.isPending}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="wf-primary"
              disabled={form.activeFormDisabled}
            >
              {form.createDecision.isPending
                ? "Recording…"
                : `Submit ${form.action} decision`}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
