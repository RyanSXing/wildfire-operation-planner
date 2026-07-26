import { useEffect, useRef } from "react";

import type { Decision } from "../../api/types";
import {
  optionsFor,
  useDecisionForm,
  type DecisionDialogProps,
  type DecisionOptionInput,
} from "./useDecisionForm";

export type { DecisionDialogProps };

export function DecisionDialog({
  recommendation,
  freshness,
  planningDisabled,
  resources,
  destinations,
  onStale,
  onDecisionRecorded,
}: DecisionDialogProps) {
  const {
    action, actionable, activeFormDisabled, addAssignment, approveEditDisabled,
    assignments, cancel, createDecision, decision, destinationOptions, note,
    open, rejectDisabled, removeAssignment, requestError, resourceOptions,
    setAssignmentDestination, setAssignmentResource, setNote, submit,
    validationError,
  } = useDecisionForm({
    recommendation,
    freshness,
    planningDisabled,
    resources,
    destinations,
    onStale,
    onDecisionRecorded,
  });

  return (
    <section aria-label="Recommendation decision controls">
      <h5>Decision</h5>
      {freshness === "stale" ? (
        <p>Recommendation is stale. Regenerate before approving or editing.</p>
      ) : !actionable ? (
        <p>This solver result cannot be approved or edited.</p>
      ) : null}
      {planningDisabled ? <p>Return to the current snapshot to decide.</p> : null}
      {requestError ? <p role="alert">{requestError}</p> : null}
      <p>
        <button type="button" disabled={approveEditDisabled} onClick={() => open("approve")}>
          Approve recommendation
        </button>{" "}
        <button type="button" disabled={rejectDisabled} onClick={() => open("reject")}>
          Reject recommendation
        </button>{" "}
        <button type="button" disabled={approveEditDisabled} onClick={() => open("edit")}>
          Edit recommendation
        </button>
      </p>

      {decision ? (
        <DecisionResult
          decision={decision}
          resources={resources}
          destinations={destinations}
        />
      ) : null}

      {action ? (
        <dialog open aria-labelledby="decision-dialog-title">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <h6 id="decision-dialog-title">{action} recommendation</h6>
            <label>
              Decision note
              <textarea
                aria-describedby={validationError ? "decision-validation" : undefined}
                maxLength={2000}
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
            </label>
            {action === "edit" ? (
              <fieldset>
                <legend>Edited assignments</legend>
                {assignments.map((assignment, index) => (
                  <fieldset key={index}>
                    <legend>Assignment {index + 1}</legend>
                    <label>
                      Resource {index + 1}
                      <select
                        value={assignment.resourceId}
                        onChange={(event) =>
                          setAssignmentResource(index, assignment, event.currentTarget.value)
                        }
                      >
                        <option value="">Select resource</option>
                        {resourceOptions.map((resource) => (
                          <option value={resource.id} key={resource.id}>{resource.label}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Destination {index + 1}
                      <select
                        value={assignment.destinationId}
                        onChange={(event) =>
                          setAssignmentDestination(index, assignment, event.currentTarget.value)
                        }
                      >
                        <option value="">Select destination</option>
                        {destinationOptions.map((destination) => (
                          <option value={destination.id} key={destination.id}>{destination.label}</option>
                        ))}
                      </select>
                    </label>
                    <button type="button" onClick={() => removeAssignment(index)}>
                      Remove assignment {index + 1}
                    </button>
                  </fieldset>
                ))}
                <button type="button" onClick={() => addAssignment()}>
                  Add assignment
                </button>
              </fieldset>
            ) : null}
            {validationError ? <p id="decision-validation" role="alert">{validationError}</p> : null}
            <button type="submit" disabled={activeFormDisabled}>
              {createDecision.isPending ? "Submitting decision" : `Submit ${action} decision`}
            </button>{" "}
            <button type="button" disabled={createDecision.isPending} onClick={cancel}>Cancel</button>
          </form>
        </dialog>
      ) : null}
    </section>
  );
}

function DecisionResult({
  decision,
  resources,
  destinations,
}: {
  decision: Decision;
  resources: readonly DecisionOptionInput[];
  destinations: readonly DecisionOptionInput[];
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section aria-label="Recorded decision">
      <h6 ref={heading} tabIndex={-1}>Decision recorded</h6>
      <p aria-label="Decision recorded" aria-live="polite" role="status">
        Decision recorded.
      </p>
      <dl>
        <dt>Action</dt><dd>{decision.action}</dd>
        <dt>Note</dt><dd>{decision.note}</dd>
        <dt>Actor</dt><dd>{decision.actorId}</dd>
        <dt>Timestamp</dt><dd>{decision.createdAt}</dd>
      </dl>
      <ul aria-label="Final assignments">
        {decision.assignments.map(({ resourceId, destinationId }) => (
          <li key={resourceId}>
            {recordedLabel(resources, resourceId, "Unavailable resource")} → {recordedLabel(destinations, destinationId, "Unavailable destination")}
          </li>
        ))}
      </ul>
    </section>
  );
}

function recordedLabel(
  options: readonly DecisionOptionInput[],
  id: string,
  fallback: string,
): string {
  return optionsFor(options, []).find((option) => option.id === id)?.label ?? fallback;
}
