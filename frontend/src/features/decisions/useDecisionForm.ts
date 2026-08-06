import { useLayoutEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiClientError } from "../../api/client";
import { queryKeys, useCreateDecisionMutation } from "../../api/hooks";
import type {
  Decision,
  DecisionAction,
  EditedAssignment,
  Recommendation,
} from "../../api/types";

export type DecisionOption = {
  id: string;
  label: string;
};

export type DecisionOptionInput = DecisionOption | string;

export type DecisionDialogProps = {
  recommendation: Recommendation;
  freshness: "current" | "stale";
  planningDisabled: boolean;
  resources: readonly DecisionOptionInput[];
  destinations: readonly DecisionOptionInput[];
  onStale?: () => void;
  onDecisionRecorded?: () => void;
};

/**
 * The decision command flow, with no presentation attached.
 *
 * None of this is view logic: it decides which of approve/reject/edit is legal
 * right now, validates the note and the edited assignments before anything is
 * posted, and classifies every server failure into a message that never leaks
 * the untrusted server text — stale, already-decided, not-actionable, resource
 * conflicts, the 422 class, and the retryable class each land somewhere
 * different, and already-decided is terminal. It was extracted verbatim from
 * DecisionDialog so the presentation could be replaced without putting any of
 * that at risk — the behaviour is pinned by DecisionDialog.test.tsx, which was
 * not changed.
 */
export function useDecisionForm({
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

  const setAssignmentResource = (
    index: number,
    assignment: EditedAssignment,
    resourceId: string,
  ): void => {
    setAssignments((current) => replace(current, index, { ...assignment, resourceId }));
  };

  const setAssignmentDestination = (
    index: number,
    assignment: EditedAssignment,
    destinationId: string,
  ): void => {
    setAssignments((current) => replace(current, index, { ...assignment, destinationId }));
  };

  const removeAssignment = (index: number): void => {
    setAssignments((current) => current.filter((_, row) => row !== index));
  };

  const addAssignment = (): void => {
    setAssignments((current) => [...current, { resourceId: "", destinationId: "" }]);
  };

  const submit = async (): Promise<void> => {
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

  return {
    action,
    actionable,
    activeFormDisabled,
    addAssignment,
    approveEditDisabled,
    assignments,
    cancel,
    createDecision,
    decision,
    destinationOptions,
    note,
    open,
    rejectDisabled,
    removeAssignment,
    requestError,
    resourceOptions,
    setAssignmentDestination,
    setAssignmentResource,
    setNote,
    submit,
    validationError,
  };
}

function replace(
  rows: EditedAssignment[],
  index: number,
  value: EditedAssignment,
): EditedAssignment[] {
  return rows.map((row, current) => (current === index ? value : row));
}

export function optionsFor(options: readonly DecisionOptionInput[], historical: readonly string[]): DecisionOption[] {
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
