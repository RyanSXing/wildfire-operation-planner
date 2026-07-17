import type { ZodType } from "zod";

import {
  apiErrorEnvelopeSchema,
  incidentDetailSchema,
  incidentListSchema,
  incidentTimelineSchema,
  sourceStatusListSchema,
  type IncidentDetail,
  type IncidentList,
  type IncidentTimeline,
  type JsonObject,
  type SourceStatusList,
} from "./types";

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

  private async request<T>(
    path: string,
    schema: ZodType<T>,
    signal?: AbortSignal,
  ): Promise<T> {
    if (signal?.aborted) {
      throw new ApiClientError("request_aborted", "Request was aborted", {}, 0);
    }

    let response: Response;
    try {
      response = await fetch(path, { signal });
    } catch (error) {
      if (isAbort(error, signal)) {
        throw new ApiClientError("request_aborted", "Request was aborted", {}, 0);
      }
      throw new ApiClientError("network_error", "Network request failed", {}, 0);
    }

    if (!response.ok) {
      const errorPayload = await safeJson(response, signal);
      const parsedError = apiErrorEnvelopeSchema.safeParse(errorPayload);
      if (parsedError.success) {
        throw new ApiClientError(
          parsedError.data.error.code,
          parsedError.data.error.message,
          parsedError.data.error.details,
          response.status,
        );
      }
      throw new ApiClientError("http_error", "Request failed", {}, response.status);
    }

    const payload = await safeJson(response, signal);
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new ApiClientError(
        "invalid_response",
        "Server returned an invalid response",
        {},
        response.status,
      );
    }
    return parsed.data;
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
