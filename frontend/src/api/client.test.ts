import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  REDWOOD_ID,
  incidentDetailResponse,
  incidentListResponse,
} from "../test/fixtures";
import { server } from "../test/server";
import { ApiClient, ApiClientError } from "./client";

const client = new ApiClient();

const scenarioVersionResponse = {
  id: "version-1",
  scenarioId: "scenario-1",
  incidentId: "incident-1",
  incidentSnapshotId: "snapshot-1",
  version: 1,
  graphVersion: "roads-v1",
  roadClosures: [],
  weatherOverrides: [],
  resourceOverrides: [],
};

const recommendationResponse = {
  id: "recommendation-1",
  scenarioVersionId: "version-1",
  incidentSnapshotId: "snapshot-1",
  assignments: [],
  uncoveredDestinationIds: [],
  objectiveComponents: {
    travelCost: 0,
    uncoveredRiskPenalty: 0,
    objectiveValue: 0,
  },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 1,
  graphVersion: "roads-v1",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "input-hash",
  sourceVersions: { observation_inputs: "snapshot-1" },
  explanation: { solver_status: "OPTIMAL" },
  outcome: {
    scenarioRisk: {
      score: 10,
      algorithmVersion: "risk-v1",
      contributions: [],
    },
    weightedRiskCovered: 10,
    weightedRiskUncovered: 0,
    totalTravelMinutes: 0,
    unreachableDestinationIds: [],
    unavailableResourceIds: [],
  },
};

const decisionResponse = {
  id: "decision-1",
  recommendationId: "recommendation-1",
  action: "approve",
  note: "Dispatch",
  actorId: "operator-1",
  assignments: [],
  createdAt: "2026-07-17T14:30:00Z",
};

const auditEventResponse = {
  id: "event-1",
  decisionActionId: "decision-1",
  actorId: "operator-1",
  eventType: "recommendation.approved",
  aggregateType: "recommendation",
  aggregateId: "recommendation-1",
  scenarioVersionId: "version-1",
  incidentSnapshotId: "snapshot-1",
  recommendationId: "recommendation-1",
  algorithms: {},
  beforeState: {},
  afterState: {},
  inputs: {},
  note: "Dispatch",
  occurredAt: "2026-07-17T14:30:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

async function capturedError(promise: Promise<unknown>): Promise<ApiClientError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiClientError);
    return error as ApiClientError;
  }
  throw new Error("Expected ApiClientError");
}

describe("ApiClient", () => {
  it("uses a relative URL and parses structured risk evidence", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const response = await client.listIncidents();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/incidents",
      expect.objectContaining({ signal: undefined }),
    );
    expect(response.items).toHaveLength(2);
    expect(response.items[0].risk.contributions[0].rawValue).toEqual({
      exposed_population: 1184,
      nearest_distance_meters: 7200,
    });
    fetchSpy.mockRestore();
  });

  it("rejects malformed successful payloads without exposing response data", async () => {
    server.use(
      http.get("/api/incidents", () =>
        HttpResponse.json({
          ...incidentListResponse,
          items: [
            {
              ...incidentListResponse.items[0],
              name: "response-secret",
              risk: { ...incidentListResponse.items[0].risk, score: "critical" },
            },
          ],
        }),
      ),
    );

    const error = await capturedError(client.listIncidents());

    expect(error).toMatchObject({
      code: "invalid_response",
      message: "Server returned an invalid response",
      details: {},
      status: 200,
    });
    expect(String(error)).not.toContain("response-secret");
  });

  it("sanitizes schema failures for excessively nested response data", async () => {
    let rawValue: unknown = "response-secret-leaf";
    for (let index = 0; index < 5_000; index += 1) {
      rawValue = { child: rawValue };
    }
    const payload = {
      ...incidentListResponse,
      items: [
        {
          ...incidentListResponse.items[0],
          risk: {
            ...incidentListResponse.items[0].risk,
            contributions: [
              {
                ...incidentListResponse.items[0].risk.contributions[0],
                rawValue,
              },
            ],
          },
        },
      ],
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => payload,
    } as unknown as Response);

    let error: ApiClientError;
    try {
      error = await capturedError(client.listIncidents());
    } finally {
      fetchSpy.mockRestore();
    }

    expect(error).toMatchObject({
      code: "invalid_response",
      message: "Server returned an invalid response",
      details: {},
      status: 200,
    });
    expect(String(error)).not.toContain("response-secret");
  });

  it("rejects malformed GeoJSON before it reaches the map", async () => {
    server.use(
      http.get(`/api/incidents/${REDWOOD_ID}`, () =>
        HttpResponse.json({
          ...incidentDetailResponse,
          geometry: { type: "Banana", coordinates: [0] },
        }),
      ),
    );

    const error = await capturedError(client.getIncident(REDWOOD_ID));

    expect(error).toMatchObject({
      code: "invalid_response",
      message: "Server returned an invalid response",
      details: {},
      status: 200,
    });
  });

  it("maps the stable backend error envelope", async () => {
    server.use(
      http.get("/api/incidents", () =>
        HttpResponse.json(
          {
            error: {
              code: "incident_not_found",
              message: "Incident was not found",
              details: { incidentId: "missing-id" },
            },
          },
          { status: 404 },
        ),
      ),
    );

    const error = await capturedError(client.listIncidents());

    expect(error).toMatchObject({
      code: "incident_not_found",
      message: "Incident was not found",
      details: { incidentId: "missing-id" },
      status: 404,
    });
  });

  it("uses a safe fallback for malformed error responses", async () => {
    server.use(
      http.get(
        "/api/incidents",
        () => new HttpResponse("do-not-expose-response-secret", { status: 502 }),
      ),
    );

    const error = await capturedError(client.listIncidents());

    expect(error).toMatchObject({
      code: "http_error",
      message: "Request failed",
      details: {},
      status: 502,
    });
    expect(String(error)).not.toContain("response-secret");
  });

  it("distinguishes aborts from sanitized network failures", async () => {
    const controller = new AbortController();
    controller.abort();
    const aborted = await capturedError(client.listIncidents(controller.signal));
    expect(aborted).toMatchObject({
      code: "request_aborted",
      message: "Request was aborted",
      details: {},
      status: 0,
    });

    server.use(http.get("/api/incidents", () => HttpResponse.error()));
    const network = await capturedError(client.listIncidents());
    expect(network).toMatchObject({
      code: "network_error",
      message: "Network request failed",
      details: {},
      status: 0,
    });
  });

  it("preserves cancellation when the response body aborts after headers", async () => {
    const controller = new AbortController();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        controller.abort();
        throw new DOMException("Body read aborted", "AbortError");
      },
    } as unknown as Response);

    const error = await capturedError(client.listIncidents(controller.signal));

    expect(error).toMatchObject({
      code: "request_aborted",
      message: "Request was aborted",
      details: {},
      status: 0,
    });
    fetchSpy.mockRestore();
  });

  it("reads encoded decision context and bounded road-edge queries", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          incidentId: "incident/one",
          defaultGraphVersion: "roads/v1",
          availableGraphs: [{ graphVersion: "roads/v1", edgeCount: 1 }],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ items: [], total: 0, missingEdgeIds: ["edge/2"] }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ items: [], total: 0, missingEdgeIds: [] }),
      );

    await client.getDecisionContext("incident/one");
    await client.listRoadEdges("roads/v1", {
      q: "forest road",
      edgeIds: ["edge/1", "edge/2"],
      limit: 7,
    });
    await client.listRoadEdges("roads/v1", {});

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      "/api/incidents/incident%2Fone/decision-context",
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "/api/road-graphs/roads%2Fv1/edges?q=forest+road&edgeId=edge%2F1&edgeId=edge%2F2&limit=7",
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      "/api/road-graphs/roads%2Fv1/edges",
      expect.objectContaining({ signal: undefined }),
    );
    fetchSpy.mockRestore();
  });

  it("sends exact command bodies with caller-owned idempotency keys", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(scenarioVersionResponse, 201))
      .mockResolvedValueOnce(jsonResponse(scenarioVersionResponse, 201))
      .mockResolvedValueOnce(jsonResponse(recommendationResponse, 201))
      .mockResolvedValueOnce(jsonResponse(decisionResponse, 201));
    const createScenarioBody = {
      graphVersion: "roads-v1",
      objective: "minimize-response-time",
      name: "Wind shift",
    };
    const createVersionBody = {
      roadClosures: [{ edgeId: "edge-9" }],
      weatherOverrides: [],
      resourceOverrides: null,
    };
    const generateBody = { maxResponseMinutes: 30, maxSolverSeconds: 2 };
    const decisionBody = {
      action: "approve" as const,
      note: "Dispatch",
      editedAssignments: [],
    };

    await client.createScenario(
      "incident/one",
      createScenarioBody,
      "scenario-key",
    );
    await client.createScenarioVersion(
      "scenario/one",
      createVersionBody,
      "version-key",
    );
    await client.generateRecommendation(
      "version/one",
      generateBody,
      "recommendation-key",
    );
    await client.createDecision(
      "recommendation/one",
      decisionBody,
      "decision-key",
    );

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      "/api/incidents/incident%2Fone/scenarios",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "scenario-key",
        },
        body: JSON.stringify(createScenarioBody),
        signal: undefined,
      },
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "/api/scenarios/scenario%2Fone/versions",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "version-key",
        },
        body: JSON.stringify(createVersionBody),
        signal: undefined,
      },
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      "/api/scenario-versions/version%2Fone/recommendations",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "recommendation-key",
        },
        body: JSON.stringify(generateBody),
        signal: undefined,
      },
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      4,
      "/api/recommendations/recommendation%2Fone/decisions",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "decision-key",
        },
        body: JSON.stringify(decisionBody),
        signal: undefined,
      },
    );
    fetchSpy.mockRestore();
  });

  it("reads encoded audit list and detail URLs", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ items: [auditEventResponse] }))
      .mockResolvedValueOnce(jsonResponse(auditEventResponse))
      .mockResolvedValueOnce(jsonResponse({ items: [] }));

    await client.listAuditEvents("recommendation/one");
    await client.getAuditEvent("event/one");
    await client.listAuditEvents();

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      "/api/audit-events?recommendationId=recommendation%2Fone",
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "/api/audit-events/event%2Fone",
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      "/api/audit-events",
      expect.objectContaining({ signal: undefined }),
    );
    fetchSpy.mockRestore();
  });

  it("sanitizes malformed command responses without leaking response bodies", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          ...recommendationResponse,
          solverStatus: "response-secret",
          runtimeMilliseconds: -1,
        },
        201,
      ),
    );

    const error = await capturedError(
      client.generateRecommendation("version-1", {}, "request-key"),
    );

    expect(error).toMatchObject({
      code: "invalid_response",
      message: "Server returned an invalid response",
      details: {},
      status: 201,
    });
    expect(String(error)).not.toContain("response-secret");
    fetchSpy.mockRestore();
  });
});
