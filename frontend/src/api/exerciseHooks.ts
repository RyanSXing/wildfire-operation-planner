import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiClientError, apiClient } from "./client";
import {
  ExerciseConflictError,
  exerciseApiClient,
  PARK_FIRE_EXERCISE_ID,
} from "./exerciseClient";
import type {
  ExerciseObjective,
  ExercisePlanCommand,
  ExerciseSession,
  SandboxPlanRequest,
} from "./exerciseTypes";
import { IdempotencyIntent } from "./idempotency";

const exerciseRoot = ["exercise"] as const;

export const exerciseQueryKeys = {
  root: exerciseRoot,
  metadata: (exerciseId: string) =>
    [...exerciseRoot, "metadata", exerciseId] as const,
  session: (sessionId: string) =>
    [...exerciseRoot, "session", sessionId] as const,
  audit: (sessionId: string) => [...exerciseRoot, "audit", sessionId] as const,
  debrief: (sessionId: string) =>
    [...exerciseRoot, "debrief", sessionId] as const,
} as const;

export function useExerciseMetadata(exerciseId = PARK_FIRE_EXERCISE_ID) {
  return useQuery({
    queryKey: exerciseQueryKeys.metadata(exerciseId),
    queryFn: ({ signal }) => exerciseApiClient.getMetadata(exerciseId, signal),
  });
}

export function useExerciseSession(sessionId: string | null) {
  return useQuery({
    queryKey: exerciseQueryKeys.session(sessionId ?? ""),
    queryFn: ({ signal }) => exerciseApiClient.getSession(sessionId!, signal),
    enabled: sessionId !== null && sessionId.length > 0,
  });
}

export function useExerciseAudit(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: exerciseQueryKeys.audit(sessionId ?? ""),
    queryFn: ({ signal }) => exerciseApiClient.getAudit(sessionId!, signal),
    enabled: enabled && sessionId !== null && sessionId.length > 0,
  });
}

export function useExerciseDebrief(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: exerciseQueryKeys.debrief(sessionId ?? ""),
    queryFn: ({ signal }) => exerciseApiClient.getDebrief(sessionId!, signal),
    enabled: enabled && sessionId !== null && sessionId.length > 0,
  });
}

export type ExerciseCommandName =
  | "create-session"
  | "select-objective"
  | "generate-plan"
  | "advance"
  | "apply-override"
  | "decide";

export type ExerciseCommand =
  | { name: "create-session" }
  | { name: "select-objective"; objective: ExerciseObjective }
  | { name: "generate-plan" }
  | { name: "advance" }
  | { name: "apply-override"; resourceId: string; taskId: string }
  | { name: "decide"; displayName: string | null; note: string };

/**
 * One mutation drives every guided-exercise write. The caller never supplies a
 * version: the hook reads it from the session it is holding, and when the server
 * rejects a stale version it adopts the authoritative session the 409 carries
 * back. That keeps the workflow deterministic under double-clicks and retries.
 */
export function useExerciseCommand(
  session: ExerciseSession | null,
  onSession: (session: ExerciseSession) => void,
) {
  const queryClient = useQueryClient();
  const [intent] = useState(() => new IdempotencyIntent());

  const mutation = useMutation<ExerciseSession, unknown, ExerciseCommand>({
    mutationFn: async (command) => {
      const expectedVersion = session?.version ?? 0;
      const sessionId = session?.id ?? "";
      const attempt = intent.begin(
        JSON.stringify([command, sessionId, expectedVersion]),
      );
      try {
        const result = await run(command, sessionId, expectedVersion, attempt.key);
        intent.settle(attempt, "consume");
        return result;
      } catch (error) {
        intent.settle(attempt, isRetryable(error) ? "retain" : "consume");
        if (error instanceof ExerciseConflictError && error.currentSession) {
          onSession(error.currentSession);
          queryClient.setQueryData(
            exerciseQueryKeys.session(error.currentSession.id),
            error.currentSession,
          );
        }
        throw error;
      }
    },
    onSuccess: (next) => {
      onSession(next);
      queryClient.setQueryData(exerciseQueryKeys.session(next.id), next);
      void queryClient.invalidateQueries({
        queryKey: exerciseQueryKeys.audit(next.id),
      });
    },
  });

  const reset = useCallback(() => {
    intent.discard();
    mutation.reset();
  }, [intent, mutation]);

  return { ...mutation, reset };
}

export function useSandboxPlan(sessionId: string | null) {
  return useMutation({
    mutationFn: (body: SandboxPlanRequest) =>
      exerciseApiClient.generateSandboxPlan(sessionId!, body),
  });
}

async function run(
  command: ExerciseCommand,
  sessionId: string,
  expectedVersion: number,
  key: string,
): Promise<ExerciseSession> {
  switch (command.name) {
    case "create-session":
      return exerciseApiClient.createSession(PARK_FIRE_EXERCISE_ID, key);
    case "select-objective":
      return exerciseApiClient.selectObjective(
        sessionId,
        { expectedVersion, objective: command.objective },
        key,
      );
    case "generate-plan":
      return unwrap(
        await exerciseApiClient.generatePlan(sessionId, { expectedVersion }, key),
      );
    case "advance":
      return exerciseApiClient.advance(sessionId, { expectedVersion }, key);
    case "apply-override":
      return unwrap(
        await exerciseApiClient.applyOverride(
          sessionId,
          {
            expectedVersion,
            resourceId: command.resourceId,
            taskId: command.taskId,
          },
          key,
        ),
      );
    case "decide":
      return exerciseApiClient.decide(
        sessionId,
        {
          expectedVersion,
          displayName: command.displayName,
          note: command.note,
        },
        key,
      );
  }
}

function unwrap(result: ExercisePlanCommand): ExerciseSession {
  return result.session;
}

function isRetryable(error: unknown): boolean {
  return (
    error instanceof ApiClientError &&
    (error.code === "network_error" ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500)
  );
}

/**
 * Resolves the satellite detections an exercise checkpoint cites as its
 * provenance.
 *
 * The join is by detection identity, not by incident name: the replay's
 * clustering can put the detection an exercise cites into an incident whose
 * generated name is not "Park Fire", and drawing the wrong fire would be worse
 * than drawing none.
 */
export function useCitedDetections(identities: readonly string[]) {
  const wanted = useMemo(
    () => [...new Set(identities)].sort(),
    [identities],
  );
  return useQuery({
    queryKey: [...exerciseRoot, "cited-detections", wanted] as const,
    enabled: wanted.length > 0,
    queryFn: async ({ signal }) => {
      const list = await apiClient.listIncidents(signal);
      const details = await Promise.all(
        list.items.map((item) => apiClient.getIncident(item.id, signal)),
      );
      return selectCitedDetections(details, wanted);
    },
  });
}

type DetectionSource = {
  readonly detections: readonly {
    readonly sourceName: string;
    readonly sourceRecordId: string;
  }[];
};

/**
 * Picks the detections belonging to whichever incidents contain the cited
 * identities.
 *
 * Matching on the incident *name* looks equivalent and is not: the replay's
 * clustering can place the detection an exercise cites inside an incident whose
 * generated name is nothing like the exercise's. Drawing that wrong cluster
 * would put the fire in the wrong place with no visible sign of the error.
 */
export function selectCitedDetections<T extends DetectionSource>(
  incidents: readonly T[],
  identities: readonly string[],
): T["detections"][number][] {
  const wanted = new Set(identities);
  return incidents
    .filter((incident) =>
      incident.detections.some((detection) =>
        wanted.has(`${detection.sourceName}:${detection.sourceRecordId}`),
      ),
    )
    .flatMap((incident) => [...incident.detections]);
}
