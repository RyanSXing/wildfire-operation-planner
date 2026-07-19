import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiClientError } from "../../api/client";
import { queryKeys, useCreateDecisionMutation } from "../../api/hooks";
import type {
  Decision,
  DecisionAction,
  EditedAssignment,
  Recommendation,
} from "../../api/types";

export type DecisionDialogProps = {
  recommendation: Recommendation;
  freshness: "current" | "stale";
  planningDisabled: boolean;
  resources: readonly DecisionOptionInput[];
  destinations: readonly DecisionOptionInput[];
  onStale?: () => void;
  onDecisionRecorded?: () => void;
};

export function DecisionDialog({
  recommendation,
  freshness,
  planningDisabled,
  resources,
  destinations,
  onStale,
  onDecisionRecorded,
}: DecisionDialogProps) {
  const createDecision = useCreateDecisionMutation();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<DecisionAction | null>(null);
  const [note, setNote] = useState("");
  const [assignments, setAssignments] = useState<EditedAssignment[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [alreadyDecided, setAlreadyDecided] = useState(false);
  const submitting = useRef(false);
  const mounted = useRef(false);

  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const actionable =
    recommendation.solverStatus === "FEASIBLE" ||
    recommendation.solverStatus === "OPTIMAL";
  const terminal = decision !== null || alreadyDecided;
  const allDisabled = planningDisabled || createDecision.isPending || terminal;
  const approveEditDisabled = allDisabled || freshness === "stale" || !actionable;
  const rejectDisabled = allDisabled;
  const activeFormDisabled =
    action !== null &&
    (action === "reject" ? rejectDisabled : approveEditDisabled);
  const resourceOptions = optionsFor(resources, assignments.map(({ resourceId }) => resourceId));
  const destinationOptions = optionsFor(destinations, assignments.map(({ destinationId }) => destinationId));

  const open = (nextAction: DecisionAction): void => {
    if ((nextAction === "reject" ? rejectDisabled : approveEditDisabled)) {
      return;
    }
    createDecision.reset();
    setAction(nextAction);
    setNote("");
    setAssignments(
      nextAction === "edit"
        ? recommendation.assignments.map(({ resourceId, destinationId }) => ({
            resourceId,
            destinationId,
          }))
        : [],
    );
    setValidationError(null);
    setRequestError(null);
  };

  const cancel = (): void => {
    createDecision.reset();
    setAction(null);
    setNote("");
    setAssignments([]);
    setValidationError(null);
    setRequestError(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!action || activeFormDisabled || submitting.current) {
      return;
    }
    const trimmedNote = note.trim();
    const error = validate(action, trimmedNote, assignments);
    if (error) {
      setValidationError(error);
      return;
    }
    setValidationError(null);
    setRequestError(null);
    submitting.current = true;
    try {
      const result = await createDecision.mutateAsync({
        recommendationId: recommendation.id,
        body: {
          action,
          note: trimmedNote,
          ...(action === "edit" ? { editedAssignments: assignments } : {}),
        },
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.audit.root,
        refetchType: "active",
      });
      if (!mounted.current) {
        return;
      }
      setDecision(result);
      setAction(null);
      onDecisionRecorded?.();
    } catch (error) {
      if (
        error instanceof ApiClientError &&
        error.code === "recommendation_already_decided"
      ) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.audit.root,
          refetchType: "active",
        });
      }
      if (!mounted.current) {
        return;
      }
      const message = safeDecisionError(error);
      setRequestError(message);
      if (error instanceof ApiClientError && error.code === "recommendation_stale") {
        onStale?.();
        setAction(null);
      }
      if (error instanceof ApiClientError && error.code === "recommendation_already_decided") {
        setAlreadyDecided(true);
        setAction(null);
        onDecisionRecorded?.();
      }
    } finally {
      submitting.current = false;
    }
  };

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
          <form onSubmit={(event) => void submit(event)}>
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
                        onChange={(event) => {
                          const resourceId = event.currentTarget.value;
                          setAssignments((current) =>
                            replace(current, index, { ...assignment, resourceId }),
                          )
                        }}
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
                        onChange={(event) => {
                          const destinationId = event.currentTarget.value;
                          setAssignments((current) =>
                            replace(current, index, { ...assignment, destinationId }),
                          )
                        }}
                      >
                        <option value="">Select destination</option>
                        {destinationOptions.map((destination) => (
                          <option value={destination.id} key={destination.id}>{destination.label}</option>
                        ))}
                      </select>
                    </label>
                    <button type="button" onClick={() => setAssignments((current) => current.filter((_, row) => row !== index))}>
                      Remove assignment {index + 1}
                    </button>
                  </fieldset>
                ))}
                <button type="button" onClick={() => setAssignments((current) => [...current, { resourceId: "", destinationId: "" }])}>
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

function replace(
  rows: EditedAssignment[],
  index: number,
  value: EditedAssignment,
): EditedAssignment[] {
  return rows.map((row, current) => (current === index ? value : row));
}

type DecisionOption = {
  id: string;
  label: string;
};

type DecisionOptionInput = DecisionOption | string;

function optionsFor(options: readonly DecisionOptionInput[], historical: readonly string[]): DecisionOption[] {
  const all = new Map(
    options.map((option) => {
      const normalized = typeof option === "string" ? { id: option, label: option } : option;
      return [normalized.id, normalized];
    }),
  );
  for (const id of historical) {
    all.set(id, all.get(id) ?? { id, label: id });
  }
  return [...all.values()].sort((left, right) => left.label.localeCompare(right.label));
}

function validate(
  action: DecisionAction,
  note: string,
  assignments: readonly EditedAssignment[],
): string | null {
  if (!note) {
    return "A note is required.";
  }
  if (note.length > 2000) {
    return "Note must be 2,000 characters or fewer.";
  }
  if (action !== "edit") {
    return null;
  }
  if (assignments.length === 0) {
    return "Add at least one assignment.";
  }
  if (assignments.some(({ resourceId, destinationId }) => !resourceId.trim() || !destinationId.trim())) {
    return "Each assignment needs a resource and destination.";
  }
  if (new Set(assignments.map(({ resourceId }) => resourceId)).size !== assignments.length) {
    return "Each resource can have only one destination.";
  }
  return null;
}

function safeDecisionError(error: unknown): string {
  if (!(error instanceof ApiClientError)) {
    return "Decision could not be completed.";
  }
  switch (error.code) {
    case "recommendation_stale":
      return "Recommendation is stale. Regenerate before approving or editing.";
    case "recommendation_not_actionable":
      return "This solver result cannot be approved or edited.";
    case "recommendation_already_decided":
      return "This recommendation has already been decided.";
    case "resource_already_assigned":
      return "A selected resource was assigned elsewhere. Regenerate before dispatch.";
    case "decision_invalid":
      return "Decision could not be validated. Review the note and assignments.";
    default:
      if (error.status === 422) {
        return "Decision could not be validated. Review the note and assignments.";
      }
      if (error.code === "network_error" || error.status === 408 || error.status === 429 || error.status >= 500) {
        return "Decision request failed. Retrying this unchanged decision is safe.";
      }
      return "Decision could not be completed.";
  }
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
