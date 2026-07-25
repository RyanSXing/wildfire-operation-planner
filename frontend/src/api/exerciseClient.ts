import type { ZodType } from "zod";

import { ApiClientError } from "./client";
import {
  exerciseAuditSchema,
  exerciseDebriefSchema,
  exerciseMetadataSchema,
  exercisePlanCommandSchema,
  exerciseSessionSchema,
  sandboxPlanSchema,
  type ExerciseAudit,
  type ExerciseDebrief,
  type ExerciseMetadata,
  type ExerciseObjective,
  type ExercisePlanCommand,
  type ExerciseSession,
  type SandboxPlan,
  type SandboxPlanRequest,
} from "./exerciseTypes";
import { apiErrorEnvelopeSchema } from "./types";

export const PARK_FIRE_EXERCISE_ID = "park-fire-decision";

/**
 * Every write is guarded by `expectedVersion`. When the server rejects a stale
 * version it answers 409 and returns the authoritative session inside
 * `details.currentSession`, so callers can resynchronise without guessing.
 */
export class ExerciseConflictError extends ApiClientError {
  readonly currentSession: ExerciseSession | undefined;

  constructor(error: ApiClientError) {
    super(error.code, error.message, error.details, error.status);
    this.name = "ExerciseConflictError";
    const parsed = exerciseSessionSchema.safeParse(error.details.currentSession);
    this.currentSession = parsed.success ? parsed.data : undefined;
  }
}

export class ExerciseApiClient {
  getMetadata(
    exerciseId: string,
    signal?: AbortSignal,
  ): Promise<ExerciseMetadata> {
    return this.request(
      `/api/exercises/${encodeURIComponent(exerciseId)}`,
      exerciseMetadataSchema,
      signal,
    );
  }

  createSession(
    exerciseId: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExerciseSession> {
    return this.command(
      `/api/exercises/${encodeURIComponent(exerciseId)}/sessions`,
      exerciseSessionSchema,
      {},
      idempotencyKey,
      signal,
    );
  }

  getSession(sessionId: string, signal?: AbortSignal): Promise<ExerciseSession> {
    return this.request(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}`,
      exerciseSessionSchema,
      signal,
    );
  }

  selectObjective(
    sessionId: string,
    body: { expectedVersion: number; objective: ExerciseObjective },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExerciseSession> {
    return this.command(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/objective`,
      exerciseSessionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  generatePlan(
    sessionId: string,
    body: { expectedVersion: number },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExercisePlanCommand> {
    return this.command(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/plans`,
      exercisePlanCommandSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  advance(
    sessionId: string,
    body: { expectedVersion: number },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExerciseSession> {
    return this.command(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/advance`,
      exerciseSessionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  applyOverride(
    sessionId: string,
    body: { expectedVersion: number; resourceId: string; taskId: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExercisePlanCommand> {
    return this.command(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/overrides`,
      exercisePlanCommandSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  decide(
    sessionId: string,
    body: { expectedVersion: number; displayName: string | null; note: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ExerciseSession> {
    return this.command(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/decisions`,
      exerciseSessionSchema,
      body,
      idempotencyKey,
      signal,
    );
  }

  generateSandboxPlan(
    sessionId: string,
    body: SandboxPlanRequest,
    signal?: AbortSignal,
  ): Promise<SandboxPlan> {
    return this.request(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/sandbox-plans`,
      sandboxPlanSchema,
      signal,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
  }

  getAudit(sessionId: string, signal?: AbortSignal): Promise<ExerciseAudit> {
    return this.request(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/audit`,
      exerciseAuditSchema,
      signal,
    );
  }

  getDebrief(sessionId: string, signal?: AbortSignal): Promise<ExerciseDebrief> {
    return this.request(
      `/api/exercise-sessions/${encodeURIComponent(sessionId)}/debrief`,
      exerciseDebriefSchema,
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
      throw await readError(response, signal);
    }

    const payload = await safeJson(response, signal);
    const parsed = schema.safeParse(payload);
    if (parsed.success) {
      return parsed.data;
    }
    throw new ApiClientError(
      "invalid_response",
      "Server returned an invalid response",
      {},
      response.status,
    );
  }
}

async function readError(
  response: Response,
  signal?: AbortSignal,
): Promise<ApiClientError> {
  const payload = await safeJson(response, signal);
  const parsed = apiErrorEnvelopeSchema.safeParse(payload);
  if (!parsed.success) {
    return new ApiClientError("http_error", "Request failed", {}, response.status);
  }
  const error = new ApiClientError(
    parsed.data.error.code,
    parsed.data.error.message,
    parsed.data.error.details,
    response.status,
  );
  return response.status === 409 ? new ExerciseConflictError(error) : error;
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

export const exerciseApiClient = new ExerciseApiClient();
