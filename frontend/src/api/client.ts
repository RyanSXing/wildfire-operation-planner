import type { ZodType } from "zod";

import {
  auditEventListSchema,
  auditEventSchema,
  apiErrorEnvelopeSchema,
  decisionContextSchema,
  decisionSchema,
  incidentDetailSchema,
  incidentListSchema,
  incidentTimelineSchema,
  recommendationSchema,
  roadEdgeListSchema,
  scenarioVersionSchema,
  sourceStatusListSchema,
  type AuditEvent,
  type AuditEventList,
  type Decision,
  type DecisionContext,
  type DecisionCreateRequest,
  type IncidentDetail,
  type IncidentList,
  type IncidentTimeline,
  type JsonObject,
  type Recommendation,
  type RecommendationCreateRequest,
  type RoadEdgeList,
  type ScenarioCreateRequest,
  type ScenarioVersion,
  type ScenarioVersionCreateRequest,
  type SourceStatusList,
} from "./types";

export type RoadEdgeQuery = {
  q?: string;
  edgeIds?: readonly string[];
  limit?: number;
};

export class ApiClientError extends Error {
  readonly code: string;
  readonly details: JsonObject;
  readonly status: number;

  constructor(code: string, message: string, details: JsonObject, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

export class ApiClient {
  listIncidents(signal?: AbortSignal): Promise<IncidentList> {
    return this.request("/api/incidents", incidentListSchema, signal);
  }

  getIncident(incidentId: string, signal?: AbortSignal): Promise<IncidentDetail> {
    return this.request(
      `/api/incidents/${encodeURIComponent(incidentId)}`,
      incidentDetailSchema,
      signal,
    );
  }

  getIncidentTimeline(
    incidentId: string,
    signal?: AbortSignal,
  ): Promise<IncidentTimeline> {
    return this.request(
      `/api/incidents/${encodeURIComponent(incidentId)}/timeline`,
      incidentTimelineSchema,
      signal,
    );
  }

  listSourceStatuses(signal?: AbortSignal): Promise<SourceStatusList> {
    return this.request("/api/sources/status", sourceStatusListSchema, signal);
  }

  getDecisionContext(
    incidentId: string,
    signal?: AbortSignal,
  ): Promise<DecisionContext> {
    return this.request(
      `/api/incidents/${encodeURIComponent(incidentId)}/decision-context`,
      decisionContextSchema,
      signal,
    );
  }

  listRoadEdges(
    graphVersion: string,
    query: RoadEdgeQuery,
    signal?: AbortSignal,
  ): Promise<RoadEdgeList> {
    const params = new URLSearchParams();
    if (query.q !== undefined) {
      params.set("q", query.q);
    }
    for (const edgeId of query.edgeIds ?? []) {
      params.append("edgeId", edgeId);
    }
    if (query.limit !== undefined) {
      params.set("limit", String(query.limit));
    }
    const suffix = params.size === 0 ? "" : `?${params.toString()}`;
    return this.request(
      `/api/road-graphs/${encodeURIComponent(graphVersion)}/edges${suffix}`,
      roadEdgeListSchema,
      signal,
    );
  }

  createScenario(
    incidentId: string,
    body: ScenarioCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ScenarioVersion> {
    return this.command(
      `/api/incidents/${encodeURIComponent(incidentId)}/scenarios`,
      scenarioVersionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  createScenarioVersion(
    scenarioId: string,
    body: ScenarioVersionCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ScenarioVersion> {
    return this.command(
      `/api/scenarios/${encodeURIComponent(scenarioId)}/versions`,
      scenarioVersionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  generateRecommendation(
    versionId: string,
    body: RecommendationCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<Recommendation> {
    return this.command(
      `/api/scenario-versions/${encodeURIComponent(versionId)}/recommendations`,
      recommendationSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  createDecision(
    recommendationId: string,
    body: DecisionCreateRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<Decision> {
    return this.command(
      `/api/recommendations/${encodeURIComponent(recommendationId)}/decisions`,
      decisionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  listAuditEvents(
    recommendationId?: string,
    signal?: AbortSignal,
  ): Promise<AuditEventList> {
    const params = new URLSearchParams();
    if (recommendationId !== undefined) {
      params.set("recommendationId", recommendationId);
    }
    const suffix = params.size === 0 ? "" : `?${params.toString()}`;
    return this.request(
      `/api/audit-events${suffix}`,
      auditEventListSchema,
      signal,
    );
  }

  getAuditEvent(eventId: string, signal?: AbortSignal): Promise<AuditEvent> {
    return this.request(
      `/api/audit-events/${encodeURIComponent(eventId)}`,
      auditEventSchema,
      signal,
    );
  }

  private command<T>(
    path: string,
    schema: ZodType<T>,
    body: object,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<T> {
    return this.request(path, schema, signal, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(body),
    });
  }

  private async request<T>(
    path: string,
    schema: ZodType<T>,
    signal?: AbortSignal,
    init?: RequestInit,
  ): Promise<T> {
    if (signal?.aborted) {
      throw new ApiClientError("request_aborted", "Request was aborted", {}, 0);
    }

    let response: Response;
    try {
      response = await fetch(path, { ...init, signal });
    } catch (error) {
      if (isAbort(error, signal)) {
        throw new ApiClientError("request_aborted", "Request was aborted", {}, 0);
      }
      throw new ApiClientError("network_error", "Network request failed", {}, 0);
    }

    if (!response.ok) {
      const errorPayload = await safeJson(response, signal);
      try {
        const parsedError = apiErrorEnvelopeSchema.safeParse(errorPayload);
        if (parsedError.success) {
          throw new ApiClientError(
            parsedError.data.error.code,
            parsedError.data.error.message,
            parsedError.data.error.details,
            response.status,
          );
        }
      } catch (error) {
        if (error instanceof ApiClientError) {
          throw error;
        }
      }
      throw new ApiClientError("http_error", "Request failed", {}, response.status);
    }

    const payload = await safeJson(response, signal);
    try {
      const parsed = schema.safeParse(payload);
      if (parsed.success) {
        return parsed.data;
      }
    } catch {
      // Schema evaluation failures use the same sanitized invalid-response path.
    }
    throw new ApiClientError(
      "invalid_response",
      "Server returned an invalid response",
      {},
      response.status,
    );
  }
}

async function safeJson(
  response: Response,
  signal?: AbortSignal,
): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (isAbort(error, signal)) {
      throw new ApiClientError("request_aborted", "Request was aborted", {}, 0);
    }
    return undefined;
  }
}

function isAbort(error: unknown, signal?: AbortSignal): boolean {
  return (
    signal?.aborted === true ||
    (error instanceof DOMException && error.name === "AbortError")
  );
}

export const apiClient = new ApiClient();
