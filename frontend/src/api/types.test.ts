import { describe, expect, it } from "vitest";

import {
  auditEventListSchema,
  auditEventSchema,
  decisionContextSchema,
  decisionSchema,
  geometrySchema,
  jsonValueSchema,
  recommendationSchema,
  roadEdgeListSchema,
  scenarioVersionSchema,
  type DecisionCreateRequest,
  type RecommendationCreateRequest,
  type ScenarioCreateRequest,
  type ScenarioVersionCreateRequest,
} from "./types";

const risk = {
  score: 24,
  algorithmVersion: "risk-v1",
  contributions: [
    {
      name: "wind",
      rawValue: { wind_speed_mps: 12 },
      normalizedValue: 0.4,
      weight: 0.5,
      contribution: 0.2,
    },
  ],
};

const assignment = {
  resourceId: "crew-4",
  destinationId: "town-2",
  route: {
    status: "reachable",
    edgeIds: ["edge-9"],
    distanceMeters: 1_200,
    travelMinutes: 8,
    graphVersion: "roads-v3",
    closureHash: "closure-hash",
  },
  travelMinutes: 8,
  capacity: 4,
};

const recommendation = {
  id: "recommendation-1",
  scenarioVersionId: "version-2",
  incidentSnapshotId: "snapshot-7",
  assignments: [assignment],
  uncoveredDestinationIds: [],
  objectiveComponents: {
    travelCost: 8,
    uncoveredRiskPenalty: 0,
    objectiveValue: 8,
  },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 7,
  graphVersion: "roads-v3",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "input-hash",
  sourceVersions: { observation_inputs: { source_version: "2024-07" } },
  explanation: { solver_status: "OPTIMAL" },
  outcome: {
    scenarioRisk: risk,
    weightedRiskCovered: 24,
    weightedRiskUncovered: 0,
    totalTravelMinutes: 8,
    unreachableDestinationIds: [],
    unavailableResourceIds: [],
  },
};

const auditEvent = {
  id: "event-1",
  decisionActionId: "decision-1",
  actorId: "operator-1",
  eventType: "recommendation.approved",
  aggregateType: "recommendation",
  aggregateId: "recommendation-1",
  scenarioVersionId: "version-2",
  incidentSnapshotId: "snapshot-7",
  recommendationId: "recommendation-1",
  algorithms: { riskVersion: "risk-v1" },
  beforeState: { assignments: [] },
  afterState: { finalPairs: [{ resourceId: "crew-4" }] },
  inputs: { sourceVersions: { observationInputs: "2024-07" } },
  note: "Approved",
  occurredAt: "2026-07-17T10:30:00-04:00",
};

function nestedObject(depth: number): unknown {
  let value: unknown = "leaf";
  for (let index = 0; index < depth; index += 1) {
    value = { child: value };
  }
  return value;
}

function nestedGeometryCollection(depth: number): unknown {
  let geometry: unknown = {
    type: "Point",
    coordinates: [-121.6, 39.8],
  };
  for (let index = 0; index < depth; index += 1) {
    geometry = { type: "GeometryCollection", geometries: [geometry] };
  }
  return geometry;
}

describe("bounded JSON schemas", () => {
  it("rejects excessively nested JSON without throwing", () => {
    expect(() => jsonValueSchema.safeParse(nestedObject(80))).not.toThrow();
    expect(jsonValueSchema.safeParse(nestedObject(80)).success).toBe(false);
  });
});

describe("geometrySchema", () => {
  it("rejects unknown or structurally incomplete GeoJSON geometry", () => {
    expect(geometrySchema.safeParse({ type: "Point" }).success).toBe(false);
    expect(
      geometrySchema.safeParse({
        type: "Polygon",
        coordinates: [[[-121.6]]],
      }).success,
    ).toBe(false);
    expect(
      geometrySchema.safeParse({
        type: "FutureGeometry",
        coordinates: [-121.6, 39.8],
      }).success,
    ).toBe(false);
  });

  it("accepts standard geometry shapes and preserves forward-compatible members", () => {
    const result = geometrySchema.parse({
      type: "Point",
      coordinates: [-121.6, 39.8],
      bbox: [-121.6, 39.8, -121.6, 39.8],
      vendorMetadata: { quality: "reviewed" },
    });

    expect(result).toMatchObject({
      type: "Point",
      coordinates: [-121.6, 39.8],
      vendorMetadata: { quality: "reviewed" },
    });
  });

  it("validates nested standard GeometryCollection members", () => {
    const result = geometrySchema.parse({
      type: "GeometryCollection",
      geometries: [
        { type: "Point", coordinates: [-121.6, 39.8] },
        {
          type: "GeometryCollection",
          geometries: [
            {
              type: "LineString",
              coordinates: [
                [-121.6, 39.8],
                [-121.5, 39.9],
              ],
            },
          ],
        },
      ],
      vendorMetadata: { quality: "reviewed" },
    });

    expect(result.type).toBe("GeometryCollection");
    expect(result).toHaveProperty("vendorMetadata.quality", "reviewed");
    expect(
      geometrySchema.safeParse({
        type: "GeometryCollection",
        geometries: [{ type: "Banana", coordinates: [0] }],
      }).success,
    ).toBe(false);
  });

  it("rejects excessively nested GeometryCollections without throwing", () => {
    expect(() =>
      geometrySchema.safeParse(nestedGeometryCollection(80)),
    ).not.toThrow();
    expect(
      geometrySchema.safeParse(nestedGeometryCollection(80)).success,
    ).toBe(false);
  });
});

describe("decision transport schemas", () => {
  it("parses the reviewed decision-planning response boundaries", () => {
    expect(
      decisionContextSchema.parse({
        incidentId: "incident-1",
        defaultGraphVersion: "roads-v3",
        availableGraphs: [{ graphVersion: "roads-v3", edgeCount: 2 }],
      }),
    ).toMatchObject({ defaultGraphVersion: "roads-v3" });
    expect(
      roadEdgeListSchema.parse({
        items: [
          {
            edgeId: "edge-9",
            label: "Forest Road",
            geometry: {
              type: "LineString",
              coordinates: [
                [-121.6, 39.8],
                [-121.5, 39.9],
              ],
            },
            travelMinutes: 8,
            distanceMeters: 1_200,
          },
          {
            edgeId: "edge-10",
            label: "Unmapped road",
            geometry: null,
            travelMinutes: 4,
            distanceMeters: 600,
          },
        ],
        total: 2,
        missingEdgeIds: [],
      }).items,
    ).toHaveLength(2);
    expect(
      scenarioVersionSchema.parse({
        id: "version-2",
        scenarioId: "scenario-1",
        incidentId: "incident-1",
        incidentSnapshotId: "snapshot-7",
        version: 2,
        graphVersion: "roads-v3",
        roadClosures: [{ edgeId: "edge-9" }],
        weatherOverrides: [
          { windSpeedMps: 12, windDirectionDegrees: 220 },
        ],
        resourceOverrides: [{ resourceId: "crew-4", available: false }],
      }).version,
    ).toBe(2);
    expect(recommendationSchema.parse(recommendation).outcome).toMatchObject({
      weightedRiskCovered: 24,
    });
    expect(
      decisionSchema.parse({
        id: "decision-1",
        recommendationId: "recommendation-1",
        action: "approve",
        note: "Approved",
        actorId: "operator-1",
        assignments: [assignment],
        createdAt: "2026-07-17T14:30:00Z",
      }).action,
    ).toBe("approve");
    expect(auditEventSchema.parse(auditEvent).inputs).toEqual(
      auditEvent.inputs,
    );
    expect(auditEventListSchema.parse({ items: [auditEvent] }).items).toHaveLength(
      1,
    );
  });

  it("rejects invalid enums, integers, finite numbers, timestamps, and top-level casing", () => {
    expect(
      recommendationSchema.safeParse({
        ...recommendation,
        assignments: [
          {
            ...assignment,
            route: { ...assignment.route, status: "unknown" },
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      recommendationSchema.safeParse({
        ...recommendation,
        runtimeMilliseconds: -1,
      }).success,
    ).toBe(false);
    expect(
      recommendationSchema.safeParse({
        ...recommendation,
        assignments: [{ ...assignment, capacity: 0 }],
      }).success,
    ).toBe(false);
    expect(
      recommendationSchema.safeParse({
        ...recommendation,
        outcome: {
          ...recommendation.outcome,
          weightedRiskCovered: Number.POSITIVE_INFINITY,
        },
      }).success,
    ).toBe(false);
    expect(
      roadEdgeListSchema.safeParse({
        items: [
          {
            edgeId: "edge-9",
            label: "Forest Road",
            geometry: {
              type: "LineString",
              coordinates: [
                [-121.6, 39.8],
                [Number.NaN, 39.9],
              ],
            },
            travelMinutes: 8,
            distanceMeters: 1_200,
          },
        ],
        total: 1,
        missingEdgeIds: [],
      }).success,
    ).toBe(false);
    expect(
      decisionSchema.safeParse({
        id: "decision-1",
        recommendationId: "recommendation-1",
        action: "hold",
        note: "Wait",
        actorId: "operator-1",
        assignments: [],
        createdAt: "2026-07-17T14:30:00",
      }).success,
    ).toBe(false);
    expect(
      decisionContextSchema.safeParse({
        incident_id: "incident-1",
        defaultGraphVersion: null,
        availableGraphs: [],
      }).success,
    ).toBe(false);
  });

  it("keeps nested provenance keys unchanged and never exposes request inputs", () => {
    const parsed = recommendationSchema.parse({
      ...recommendation,
      requestInputs: { secret: "must-not-escape" },
    });

    expect(parsed.sourceVersions).toEqual(recommendation.sourceVersions);
    expect(parsed.explanation).toEqual(recommendation.explanation);
    expect(parsed).not.toHaveProperty("requestInputs");
  });

  it("exports command request types with replacement and edit semantics", () => {
    const scenario = {
      graphVersion: "roads-v3",
      objective: "minimize-response-time",
      name: "Wind shift",
      algorithmConfigVersion: "scenario-v1",
    } satisfies ScenarioCreateRequest;
    const replacement = {
      roadClosures: [],
      weatherOverrides: null,
      resourceOverrides: [{ resourceId: "crew-4", available: false }],
    } satisfies ScenarioVersionCreateRequest;
    const generate = {
      maxResponseMinutes: 30,
      maxSolverSeconds: 2,
    } satisfies RecommendationCreateRequest;
    const decision = {
      action: "edit",
      note: "Move crew",
      editedAssignments: [
        { resourceId: "crew-4", destinationId: "town-2" },
      ],
    } satisfies DecisionCreateRequest;

    expect({ scenario, replacement, generate, decision }).toBeDefined();
  });
});
