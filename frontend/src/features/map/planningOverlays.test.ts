import { describe, expect, it } from "vitest";

import {
  incidentDetailSchema,
  recommendationSchema,
  roadEdgeListSchema,
  scenarioVersionSchema,
} from "../../api/types";
import { incidentDetailResponse } from "../../test/fixtures";
import { buildPlanningOverlays } from "./planningOverlays";

describe("buildPlanningOverlays", () => {
  it("keeps route and closure road accounting disjoint while preserving provenance", () => {
    const incident = incidentDetailSchema.parse(incidentDetailResponse);
    const version = scenarioVersionSchema.parse({
      id: "version-2",
      scenarioId: "scenario-1",
      incidentId: incident.id,
      incidentSnapshotId: incident.snapshotId,
      version: 2,
      graphVersion: "roads-v1",
      roadClosures: [{ edgeId: "edge-null" }, { edgeId: "edge-missing" }, { edgeId: "edge-omitted" }],
      weatherOverrides: [{ windSpeedMps: 12, windDirectionDegrees: 225 }],
      resourceOverrides: [{ resourceId: "engine-1", available: false }, { resourceId: "engine-missing", available: false }],
    });
    const recommendation = recommendationSchema.parse({
      id: "recommendation-2",
      scenarioVersionId: version.id,
      incidentSnapshotId: incident.snapshotId,
      assignments: [{
        resourceId: "engine-1", destinationId: "community-1", travelMinutes: 8, capacity: 4,
        route: { status: "reachable", edgeIds: ["edge-route", "edge-null", "edge-missing"], distanceMeters: 6400, travelMinutes: 8, graphVersion: "roads-v1", closureHash: "hash" },
      }],
      uncoveredDestinationIds: [], objectiveComponents: { travelCost: 8, uncoveredRiskPenalty: 0, objectiveValue: 8 }, solverStatus: "optimal", runtimeMilliseconds: 1,
      graphVersion: "roads-v1", riskVersion: "risk-v1", algorithmVersion: "solver-v1", inputVersion: "input-v1", sourceVersions: {}, explanation: {},
      outcome: { scenarioRisk: { score: 1, algorithmVersion: "risk-v1", contributions: [] }, weightedRiskCovered: 1, weightedRiskUncovered: 0, totalTravelMinutes: 8, unreachableDestinationIds: [], unavailableResourceIds: ["engine-1"] },
    });
    const roads = roadEdgeListSchema.parse({
      total: 2,
      items: [
        { edgeId: "edge-route", label: "Route", geometry: { type: "LineString", coordinates: [[-121.7, 39.7], [-121.6, 39.8]] }, travelMinutes: 8, distanceMeters: 6400 },
        { edgeId: "edge-null", label: "Null", geometry: null, travelMinutes: 1, distanceMeters: 1 },
      ],
      missingEdgeIds: ["edge-missing"],
    });

    const result = buildPlanningOverlays({
      incident,
      selection: { incidentId: incident.id, scenarioVersion: version, recommendation, freshness: "current" },
      roads,
      requestedEdgeIds: ["edge-route", "edge-null", "edge-missing", "edge-omitted"],
      queriedEdgeIds: ["edge-route", "edge-null", "edge-missing"],
      omittedEdgeIds: ["edge-omitted"],
      roadState: "success",
    });

    expect(result.routes.features[0]).toMatchObject({ properties: { sourceKind: "recommendation-route", recommendationId: "recommendation-2", resourceId: "engine-1", destinationId: "community-1", edgeId: "edge-route", graphVersion: "roads-v1", scenarioVersionId: "version-2", scenarioSnapshotId: incident.snapshotId, activeIncidentSnapshotId: incident.snapshotId, freshness: "current" } });
    expect(result.closures.features).toEqual([]);
    expect(result.metadata.routes).toEqual({ requested: ["edge-missing", "edge-null", "edge-route"], mapped: ["edge-route"], nullGeometry: ["edge-null"], missing: ["edge-missing"], omitted: [], unresolved: [] });
    expect(result.metadata.closures).toEqual({ requested: ["edge-missing", "edge-null", "edge-omitted"], mapped: [], nullGeometry: ["edge-null"], missing: ["edge-missing"], omitted: ["edge-omitted"], unresolved: [] });
    expect(result.unavailableResources.features).toHaveLength(1);
    expect(result.metadata.unavailableResources).toEqual({ all: ["engine-1", "engine-missing"], mapped: ["engine-1"], missing: ["engine-missing"] });
    expect(result.weather).toEqual({ overrides: [{ index: 1, windSpeedMps: 12, windDirectionDegrees: 225, scenarioVersionId: "version-2" }], explanation: "Scenario weather override; no location supplied, so it is not mapped." });
  });

  it("clears only road overlays after a geometry failure while retaining unavailable resources", () => {
    const incident = incidentDetailSchema.parse(incidentDetailResponse);
    const version = scenarioVersionSchema.parse({
      id: "version-1", scenarioId: "scenario-1", incidentId: incident.id, incidentSnapshotId: incident.snapshotId,
      version: 1, graphVersion: "roads-v1", roadClosures: [{ edgeId: "edge-1" }], weatherOverrides: [],
      resourceOverrides: [{ resourceId: "engine-1", available: false }],
    });
    const result = buildPlanningOverlays({
      incident,
      selection: { incidentId: incident.id, scenarioVersion: version, recommendation: null, freshness: "current" },
      roads: roadEdgeListSchema.parse({ items: [{ edgeId: "edge-1", label: "Road", geometry: { type: "LineString", coordinates: [[-121.7, 39.7], [-121.6, 39.8]] }, travelMinutes: 1, distanceMeters: 1 }], total: 1, missingEdgeIds: [] }),
      requestedEdgeIds: ["edge-1"], queriedEdgeIds: ["edge-1"], omittedEdgeIds: [], roadState: "error",
    });

    expect(result.closures.features).toEqual([]);
    expect(result.metadata.closures.unresolved).toEqual(["edge-1"]);
    expect(result.unavailableResources.features).toHaveLength(1);
  });

  it("uses explicit snapshot provenance and treats conflicting road accounting as unresolved", () => {
    const incident = incidentDetailSchema.parse({ ...incidentDetailResponse, snapshotId: "active-snapshot" });
    const version = scenarioVersionSchema.parse({
      id: "version-1", scenarioId: "scenario-1", incidentId: incident.id, incidentSnapshotId: "scenario-snapshot",
      version: 1, graphVersion: "roads-v1", roadClosures: [{ edgeId: "edge-conflict" }], weatherOverrides: [], resourceOverrides: [],
    });
    const recommendation = recommendationSchema.parse({
      id: "recommendation-1", scenarioVersionId: version.id, incidentSnapshotId: "recommendation-snapshot",
      assignments: [{ resourceId: "engine-1", destinationId: "community-1", travelMinutes: 1, capacity: 1, route: { status: "reachable", edgeIds: ["edge-route"], distanceMeters: 1, travelMinutes: 1, graphVersion: "roads-v1", closureHash: "hash" } }],
      uncoveredDestinationIds: [], objectiveComponents: { travelCost: 0, uncoveredRiskPenalty: 0, objectiveValue: 0 }, solverStatus: "optimal", runtimeMilliseconds: 1, graphVersion: "roads-v1", riskVersion: "risk-v1", algorithmVersion: "solver-v1", inputVersion: "input-v1", sourceVersions: {}, explanation: {}, outcome: { scenarioRisk: { score: 1, algorithmVersion: "risk-v1", contributions: [] }, weightedRiskCovered: 0, weightedRiskUncovered: 0, totalTravelMinutes: 0, unreachableDestinationIds: [], unavailableResourceIds: [] },
    });
    const result = buildPlanningOverlays({
      incident,
      selection: { incidentId: incident.id, scenarioVersion: version, recommendation, freshness: "stale" },
      roads: roadEdgeListSchema.parse({ items: [
        { edgeId: "edge-route", label: "Route", geometry: { type: "LineString", coordinates: [[-121.7, 39.7], [-121.6, 39.8]] }, travelMinutes: 1, distanceMeters: 1 },
        { edgeId: "edge-conflict", label: "Conflict", geometry: null, travelMinutes: 1, distanceMeters: 1 },
      ], total: 2, missingEdgeIds: ["edge-conflict"] }),
      requestedEdgeIds: ["edge-route", "edge-conflict"], queriedEdgeIds: ["edge-route", "edge-conflict"], omittedEdgeIds: [], roadState: "success",
    });

    expect(result.routes.features[0]?.properties).toMatchObject({
      incidentId: incident.id, scenarioSnapshotId: "scenario-snapshot", recommendationSnapshotId: "recommendation-snapshot", activeIncidentSnapshotId: "active-snapshot", recommendationId: recommendation.id, resourceId: "engine-1", destinationId: "community-1", edgeId: "edge-route", freshness: "stale",
    });
    expect(result.metadata.closures).toEqual({ requested: ["edge-conflict"], mapped: [], nullGeometry: [], missing: [], omitted: [], unresolved: ["edge-conflict"] });
  });
});
