import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import { roadEdgeListSchema } from "../api/types";
import {
  decisionContextsByIncidentId,
  incidentDetailsById,
  incidentListResponse,
  incidentTimelinesById,
  roadEdgesByGraphVersion,
  sourceStatusResponse,
} from "./fixtures";

const incidentNotFound = (incidentId: string) =>
  HttpResponse.json(
    {
      error: {
        code: "incident_not_found",
        message: "Incident was not found",
        details: { incidentId },
      },
    },
    { status: 404 },
  );

export const server = setupServer(
  http.get("/api/incidents", () => HttpResponse.json(incidentListResponse)),
  http.get("/api/incidents/:incidentId/decision-context", ({ params }) => {
    const incidentId = String(params.incidentId);
    const context = decisionContextsByIncidentId[incidentId];
    return context ? HttpResponse.json(context) : incidentNotFound(incidentId);
  }),
  http.get("/api/incidents/:incidentId/timeline", ({ params }) => {
    const incidentId = String(params.incidentId);
    const timeline = incidentTimelinesById[incidentId];
    return timeline ? HttpResponse.json(timeline) : incidentNotFound(incidentId);
  }),
  http.get("/api/incidents/:incidentId", ({ params }) => {
    const incidentId = String(params.incidentId);
    const detail = incidentDetailsById[incidentId];
    return detail ? HttpResponse.json(detail) : incidentNotFound(incidentId);
  }),
  http.get("/api/road-graphs/:graphVersion/edges", ({ params, request }) => {
    const graphVersion = String(params.graphVersion);
    const response = roadEdgesByGraphVersion[graphVersion];
    if (!response) {
      return HttpResponse.json(
        {
          error: {
            code: "road_graph_not_found",
            message: "Road graph was not found",
            details: { graphVersion },
          },
        },
        { status: 404 },
      );
    }

    const parsed = roadEdgeListSchema.parse(response);
    const url = new URL(request.url);
    const query = url.searchParams.get("q")?.trim().toLowerCase();
    const requestedEdgeIds = url.searchParams.getAll("edgeId");
    let items = parsed.items;
    if (query) {
      items = items.filter(
        ({ edgeId, label }) =>
          edgeId.toLowerCase().includes(query) ||
          label.toLowerCase().includes(query),
      );
    }
    if (requestedEdgeIds.length > 0) {
      const requested = new Set(requestedEdgeIds);
      items = items.filter(({ edgeId }) => requested.has(edgeId));
    }
    const limit = Number(url.searchParams.get("limit") ?? items.length);
    const returned = items.slice(0, Number.isFinite(limit) ? limit : items.length);
    const knownIds = new Set(parsed.items.map(({ edgeId }) => edgeId));

    return HttpResponse.json({
      items: returned,
      total: query || requestedEdgeIds.length > 0 ? items.length : parsed.total,
      missingEdgeIds: requestedEdgeIds.filter((edgeId) => !knownIds.has(edgeId)),
    });
  }),
  http.get("/api/sources/status", () => HttpResponse.json(sourceStatusResponse)),
);
