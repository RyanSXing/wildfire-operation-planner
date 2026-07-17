import { useEffect, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { z } from "zod";

import { ApiClientError, apiClient, type RoadEdgeQuery } from "./client";
import { IdempotencyIntent } from "./idempotency";
import type {
  Recommendation,
  RecommendationCreateRequest,
  Decision,
  DecisionCreateRequest,
  ScenarioCreateRequest,
  ScenarioVersion,
  ScenarioVersionCreateRequest,
} from "./types";

const incidentRoot = ["incidents"] as const;
const sourceRoot = ["sources"] as const;
const roadGraphRoot = ["road-graphs"] as const;
const auditRoot = ["audit-events"] as const;

export const queryKeys = {
  incidents: {
    root: incidentRoot,
    list: () => [...incidentRoot, "list"] as const,
    detail: (incidentId: string) =>
      [...incidentRoot, "detail", incidentId] as const,
    timeline: (incidentId: string) =>
      [...incidentRoot, "timeline", incidentId] as const,
    decisionContext: (incidentId: string) =>
      [...incidentRoot, "decision-context", incidentId] as const,
  },
  sources: {
    root: sourceRoot,
    status: () => [...sourceRoot, "status"] as const,
  },
  roadGraphs: {
    root: roadGraphRoot,
    edges: (graphVersion: string, query: RoadEdgeQuery) =>
      [
        ...roadGraphRoot,
        "edges",
        graphVersion,
        query.q ?? null,
        [...(query.edgeIds ?? [])],
        query.limit ?? null,
      ] as const,
  },
  audit: {
    root: auditRoot,
    list: (recommendationId: string) =>
      [...auditRoot, "list", recommendationId] as const,
    detail: (eventId: string) => [...auditRoot, "detail", eventId] as const,
  },
} as const;

export type CreateScenarioVariables = {
  incidentId: string;
  body: ScenarioCreateRequest;
};

export type CreateScenarioVersionVariables = {
  scenarioId: string;
  body: ScenarioVersionCreateRequest;
};

export type GenerateRecommendationVariables = {
  versionId: string;
  body: RecommendationCreateRequest;
};

export type CreateDecisionVariables = {
  recommendationId: string;
  body: DecisionCreateRequest;
};

const incidentUpdatedSchema = z.object({
  incidentId: z.string().min(1),
});

const sourceStatusUpdatedSchema = z.object({
  sourceName: z.string().min(1),
});

const resyncRequiredSchema = z.object({}).strict();

export type IncidentEventRevisions = Readonly<{
  globalRevision: number;
  incidentRevisions: Readonly<Record<string, number>>;
}>;

export function useIncidents() {
  return useQuery({
    queryKey: queryKeys.incidents.list(),
    queryFn: ({ signal }) => apiClient.listIncidents(signal),
  });
}

export function useIncident(incidentId: string) {
  return useQuery({
    queryKey: queryKeys.incidents.detail(incidentId),
    queryFn: ({ signal }) => apiClient.getIncident(incidentId, signal),
    enabled: incidentId.length > 0,
  });
}

export function useIncidentTimeline(incidentId: string) {
  return useQuery({
    queryKey: queryKeys.incidents.timeline(incidentId),
    queryFn: ({ signal }) => apiClient.getIncidentTimeline(incidentId, signal),
    enabled: incidentId.length > 0,
  });
}

export function useSourceStatus() {
  return useQuery({
    queryKey: queryKeys.sources.status(),
    queryFn: ({ signal }) => apiClient.listSourceStatuses(signal),
  });
}

export function useDecisionContext(incidentId: string) {
  return useQuery({
    queryKey: queryKeys.incidents.decisionContext(incidentId),
    queryFn: ({ signal }) => apiClient.getDecisionContext(incidentId, signal),
    enabled: incidentId.length > 0,
  });
}

export function useRoadEdges(graphVersion: string, query: RoadEdgeQuery) {
  return useQuery({
    queryKey: queryKeys.roadGraphs.edges(graphVersion, query),
    queryFn: ({ signal }) =>
      apiClient.listRoadEdges(graphVersion, query, signal),
    enabled: graphVersion.length > 0,
  });
}

export function useAuditEvents(recommendationId: string, enabled: boolean) {
  const id = recommendationId.trim();
  return useQuery({
    queryKey: queryKeys.audit.list(id),
    queryFn: ({ signal }) => apiClient.listAuditEvents(id, signal),
    enabled: enabled && id.length > 0,
  });
}

export function useAuditEvent(eventId: string, enabled: boolean) {
  const id = eventId.trim();
  return useQuery({
    queryKey: queryKeys.audit.detail(id),
    queryFn: ({ signal }) => apiClient.getAuditEvent(id, signal),
    enabled: enabled && id.length > 0,
  });
}

export function useCreateScenarioMutation() {
  return useIdempotentCommand<CreateScenarioVariables, ScenarioVersion>(
    ({ incidentId, body }) =>
      JSON.stringify(["create-scenario", incidentId, JSON.stringify(body)]),
    ({ incidentId, body }, key) =>
      apiClient.createScenario(incidentId, body, key),
  );
}

export function useCreateScenarioVersionMutation() {
  return useIdempotentCommand<
    CreateScenarioVersionVariables,
    ScenarioVersion
  >(
    ({ scenarioId, body }) =>
      JSON.stringify([
        "create-scenario-version",
        scenarioId,
        JSON.stringify(body),
      ]),
    ({ scenarioId, body }, key) =>
      apiClient.createScenarioVersion(scenarioId, body, key),
  );
}

export function useGenerateRecommendationMutation() {
  return useIdempotentCommand<GenerateRecommendationVariables, Recommendation>(
    ({ versionId, body }) =>
      JSON.stringify([
        "generate-recommendation",
        versionId,
        JSON.stringify(body),
      ]),
    ({ versionId, body }, key) =>
      apiClient.generateRecommendation(versionId, body, key),
  );
}

export function useCreateDecisionMutation() {
  return useIdempotentCommand<CreateDecisionVariables, Decision>(
    (variables) => JSON.stringify(["create-decision", variables.recommendationId, canonicalDecision(variables.body)]),
    ({ recommendationId, body }, key) =>
      apiClient.createDecision(recommendationId, canonicalDecision(body), key),
  );
}

export function useIncidentEvents(): IncidentEventRevisions {
  const queryClient = useQueryClient();
  const [revisions, setRevisions] = useState<IncidentEventRevisions>(() => ({
    globalRevision: 0,
    incidentRevisions: {},
  }));

  useEffect(() => {
    const eventSource = new EventSource("/api/events");
    let opened = false;

    const invalidate = (queryKey: QueryKey): void => {
      void queryClient.invalidateQueries({ queryKey, refetchType: "active" });
    };

    const reconcile = (): void => {
      invalidate(queryKeys.incidents.root);
      invalidate(queryKeys.sources.root);
    };

    const reviseGlobal = (): void => {
      setRevisions((current) => ({
        ...current,
        globalRevision: current.globalRevision + 1,
      }));
    };

    const handleOpen = (): void => {
      reconcile();
      if (opened) {
        reviseGlobal();
      } else {
        opened = true;
      }
    };

    const handleResyncRequired = (event: Event): void => {
      if (!parseEvent(event, resyncRequiredSchema)) {
        return;
      }
      reconcile();
      reviseGlobal();
    };

    const handleIncidentUpdated = (event: Event): void => {
      const payload = parseEvent(event, incidentUpdatedSchema);
      if (!payload) {
        return;
      }

      invalidate(queryKeys.incidents.list());
      invalidate(queryKeys.incidents.detail(payload.incidentId));
      invalidate(queryKeys.incidents.timeline(payload.incidentId));
      setRevisions((current) => ({
        ...current,
        incidentRevisions: {
          ...current.incidentRevisions,
          [payload.incidentId]:
            (current.incidentRevisions[payload.incidentId] ?? 0) + 1,
        },
      }));
    };

    const handleSourceStatusUpdated = (event: Event): void => {
      const payload = parseEvent(event, sourceStatusUpdatedSchema);
      if (!payload) {
        return;
      }

      invalidate(queryKeys.sources.status());
    };

    eventSource.addEventListener("open", handleOpen);
    eventSource.addEventListener("resync-required", handleResyncRequired);
    eventSource.addEventListener("incident-updated", handleIncidentUpdated);
    eventSource.addEventListener(
      "source-status-updated",
      handleSourceStatusUpdated,
    );

    return () => {
      eventSource.removeEventListener("open", handleOpen);
      eventSource.removeEventListener(
        "resync-required",
        handleResyncRequired,
      );
      eventSource.removeEventListener("incident-updated", handleIncidentUpdated);
      eventSource.removeEventListener(
        "source-status-updated",
        handleSourceStatusUpdated,
      );
      eventSource.close();
    };
  }, [queryClient]);

  return revisions;
}

function parseEvent<T>(event: Event, schema: z.ZodType<T>): T | undefined {
  if (!("data" in event) || typeof event.data !== "string") {
    return undefined;
  }

  try {
    const parsed = schema.safeParse(JSON.parse(event.data));
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}

function useIdempotentCommand<TVariables, TData>(
  signature: (variables: TVariables) => string,
  command: (variables: TVariables, key: string) => Promise<TData>,
) {
  const [intent] = useState(() => new IdempotencyIntent());
  const mutation = useMutation<TData, unknown, TVariables>({
    mutationFn: async (variables) => {
      const attempt = intent.begin(signature(variables));
      try {
        const result = await command(variables, attempt.key);
        intent.settle(attempt, "consume");
        return result;
      } catch (error) {
        intent.settle(
          attempt,
          isRetryableCommandError(error) ? "retain" : "consume",
        );
        throw error;
      }
    },
  });

  return {
    ...mutation,
    reset: () => {
      intent.discard();
      mutation.reset();
    },
  };
}

function isRetryableCommandError(error: unknown): boolean {
  return (
    error instanceof ApiClientError &&
    (error.code === "network_error" ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500)
  );
}

function canonicalDecision(body: DecisionCreateRequest): DecisionCreateRequest {
  const note = body.note.trim();
  if (body.action !== "edit") {
    return { action: body.action, note };
  }
  return {
    action: body.action,
    note,
    editedAssignments: [...(body.editedAssignments ?? [])]
      .map(({ resourceId, destinationId }) => ({
        resourceId: resourceId.trim(),
        destinationId: destinationId.trim(),
      }))
      .sort(
        (left, right) =>
          left.resourceId.localeCompare(right.resourceId) ||
          left.destinationId.localeCompare(right.destinationId),
      ),
  };
}
