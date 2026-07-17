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
});
