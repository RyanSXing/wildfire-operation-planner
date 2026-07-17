import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import {
  incidentDetailsById,
  incidentListResponse,
  incidentTimelinesById,
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
  http.get("/api/sources/status", () => HttpResponse.json(sourceStatusResponse)),
);
