import {
  decisionContextSchema,
  incidentListSchema,
  recommendationSchema,
  roadEdgeListSchema,
  scenarioVersionSchema,
} from "../api/types";

export const REDWOOD_ID = "00000000-0000-0000-0000-000000000801";
export const BEAR_ID = "00000000-0000-0000-0000-000000000802";

const redwoodContributions = [
  {
    name: "population_exposure",
    rawValue: {
      exposed_population: 1184,
      nearest_distance_meters: 7200,
    },
    normalizedValue: 0.92,
    weight: 0.3,
    contribution: 27.6,
  },
  {
    name: "wind_alignment",
    rawValue: { speed_mps: 12.4, bearing_delta_degrees: 18 },
    normalizedValue: 0.8,
    weight: 0.3,
    contribution: 24,
  },
];

const bearContributions = [
  {
    name: "proximity",
    rawValue: 0.61,
    normalizedValue: 0.61,
    weight: 0.3,
    contribution: 18.3,
  },
];

export const incidentListResponse = incidentListSchema.parse({
  items: [
    {
      id: REDWOOD_ID,
      name: "Redwood Creek",
      risk: {
        score: 82,
        algorithmVersion: "risk-v1",
        contributions: redwoodContributions,
      },
      exposedAssetCount: 3,
      lastObservedAt: "2024-07-24T18:18:00Z",
      freshness: "fresh" as const,
    },
    {
      id: BEAR_ID,
      name: "Bear Ridge",
      risk: {
        score: 61,
        algorithmVersion: "risk-v1",
        contributions: bearContributions,
      },
      exposedAssetCount: 1,
      lastObservedAt: "2024-07-24T11:30:00Z",
      freshness: "stale" as const,
    },
  ],
});

export const incidentDetailResponse = {
  id: REDWOOD_ID,
  name: "Redwood Creek",
  status: "active",
  snapshotId: "10000000-0000-0000-0000-000000000001",
  snapshotVersion: 2,
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-121.66, 39.75],
        [-121.54, 39.77],
        [-121.57, 39.87],
        [-121.68, 39.84],
        [-121.66, 39.75],
      ],
    ],
  },
  firstObservedAt: "2024-07-24T17:18:00Z",
  lastObservedAt: "2024-07-24T18:18:00Z",
  freshness: "fresh",
  risk: {
    score: 82,
    algorithmVersion: "risk-v1",
    configuration: {
      algorithm_version: "risk-v1",
      fire_freshness_seconds: 21600,
      weights: { population: 0.3, wind: 0.3 },
    },
    contributions: redwoodContributions,
  },
  detections: [
    {
      sourceName: "nasa_firms",
      sourceRecordId: "fire-801",
      observedAt: "2024-07-24T18:18:00Z",
      geometry: { type: "Point", coordinates: [-121.61, 39.81] },
      confidence: 0.91,
      intensity: 18.4,
    },
    {
      sourceName: "nasa_firms",
      sourceRecordId: "fire-802",
      observedAt: "2024-07-24T18:16:00Z",
      geometry: { type: "Point", coordinates: [-121.59, 39.79] },
      confidence: 0.87,
      intensity: null,
    },
  ],
  exposedAssets: [
    {
      assetId: "community-1",
      assetKind: "community",
      name: "Forest Ranch",
      population: 1184,
      capacity: null,
      sourceName: "census",
      sourceVersion: "2023-acs5",
      geometry: { type: "Point", coordinates: [-121.65, 39.86] },
      distanceMeters: 7200,
      bearingDegrees: 315,
    },
    {
      assetId: "hospital-1",
      assetKind: "hospital",
      name: "Pine Junction Clinic",
      population: null,
      capacity: 36,
      sourceName: "county_assets",
      sourceVersion: "2024-07",
      geometry: { type: "Point", coordinates: [-121.51, 39.8] },
      distanceMeters: 9100,
      bearingDegrees: 82,
    },
  ],
  simulatedResources: [
    {
      resourceId: "engine-1",
      resourceType: "engine",
      capabilities: ["medical", "water"],
      capacity: 4,
      available: true,
      status: "available",
      geometry: { type: "Point", coordinates: [-121.7, 39.7] },
      simulated: true,
      simulationLabel: "simulated",
    },
  ],
  sourceVersions: {
    observation_inputs: [
      {
        source_name: "nasa_firms",
        source_version: "viirs-2024-07-24",
        latest_observed_at: "2024-07-24T18:18:00Z",
      },
    ],
    asset_inputs: [
      { source_name: "census", source_version: "2023-acs5" },
    ],
  },
};

export const bearDetailResponse = {
  ...incidentDetailResponse,
  id: BEAR_ID,
  name: "Bear Ridge",
  snapshotId: "20000000-0000-0000-0000-000000000001",
  snapshotVersion: 1,
  geometry: { type: "Point", coordinates: [-121.22, 39.55] },
  firstObservedAt: "2024-07-24T10:30:00Z",
  lastObservedAt: "2024-07-24T11:30:00Z",
  freshness: "stale",
  risk: {
    ...incidentDetailResponse.risk,
    score: 61,
    contributions: bearContributions,
  },
  detections: [],
  exposedAssets: [],
  simulatedResources: [],
};

export const incidentTimelineResponse = {
  items: [
    {
      snapshotId: "10000000-0000-0000-0000-000000000000",
      snapshotVersion: 1,
      capturedAt: "2024-07-24T18:00:00Z",
      referenceAt: "2024-07-24T18:00:00Z",
      lastObservedAt: "2024-07-24T17:58:00Z",
      geometry: { type: "Point", coordinates: [-121.62, 39.8] },
      risk: {
        score: 70,
        algorithmVersion: "risk-v1",
        contributions: redwoodContributions,
      },
      detections: [incidentDetailResponse.detections[0]],
      exposedAssetCount: 2,
      freshness: "fresh",
    },
    {
      snapshotId: incidentDetailResponse.snapshotId,
      snapshotVersion: 2,
      capturedAt: "2024-07-24T18:30:00Z",
      referenceAt: "2024-07-24T18:30:00Z",
      lastObservedAt: incidentDetailResponse.lastObservedAt,
      geometry: incidentDetailResponse.geometry,
      risk: {
        score: 82,
        algorithmVersion: "risk-v1",
        contributions: redwoodContributions,
      },
      detections: incidentDetailResponse.detections,
      exposedAssetCount: 3,
      freshness: "fresh",
    },
  ],
};

export const bearTimelineResponse = {
  items: [
    {
      ...incidentTimelineResponse.items[0],
      snapshotId: bearDetailResponse.snapshotId,
      snapshotVersion: 1,
      capturedAt: "2024-07-24T11:30:00Z",
      referenceAt: "2024-07-24T11:30:00Z",
      lastObservedAt: bearDetailResponse.lastObservedAt,
      geometry: bearDetailResponse.geometry,
      risk: bearDetailResponse.risk,
      detections: [],
      exposedAssetCount: 1,
      freshness: "stale",
    },
  ],
};

export const sourceStatusResponse = {
  items: [
    {
      sourceName: "nasa_firms",
      lastAttemptedAt: "2024-07-24T18:25:00Z",
      lastSuccessAt: "2024-07-24T18:25:00Z",
      nextRetryAt: "2024-07-24T18:30:00Z",
      freshness: "fresh",
      acceptedCount: 8,
      deduplicatedCount: 2,
      quarantinedCount: 1,
      lastErrorCode: null,
    },
    {
      sourceName: "nws",
      lastAttemptedAt: "2024-07-24T18:28:00Z",
      lastSuccessAt: "2024-07-24T18:25:00Z",
      nextRetryAt: "2024-07-24T18:33:00Z",
      freshness: "stale",
      acceptedCount: 0,
      deduplicatedCount: 0,
      quarantinedCount: 0,
      lastErrorCode: "source_unavailable",
    },
  ],
};

export const incidentDetailsById: Record<string, object> = {
  [REDWOOD_ID]: incidentDetailResponse,
  [BEAR_ID]: bearDetailResponse,
};

export const incidentTimelinesById: Record<string, object> = {
  [REDWOOD_ID]: incidentTimelineResponse,
  [BEAR_ID]: bearTimelineResponse,
};

export const redwoodDecisionContextResponse = decisionContextSchema.parse({
  incidentId: REDWOOD_ID,
  defaultGraphVersion: "roads-v1",
  availableGraphs: [
    { graphVersion: "roads-v1", edgeCount: 205 },
    { graphVersion: "roads-v2", edgeCount: 1 },
  ],
});

export const bearDecisionContextResponse = decisionContextSchema.parse({
  incidentId: BEAR_ID,
  defaultGraphVersion: "roads-bear-v1",
  availableGraphs: [{ graphVersion: "roads-bear-v1", edgeCount: 0 }],
});

export const decisionContextsByIncidentId: Record<string, object> = {
  [REDWOOD_ID]: redwoodDecisionContextResponse,
  [BEAR_ID]: bearDecisionContextResponse,
};

export const redwoodRoadEdgesResponse = roadEdgeListSchema.parse({
  items: [
    {
      edgeId: "edge-1",
      label: "County Road 1",
      geometry: {
        type: "LineString",
        coordinates: [
          [-121.7, 39.7],
          [-121.63, 39.78],
        ],
      },
      travelMinutes: 8,
      distanceMeters: 6400,
    },
    {
      edgeId: "edge-2",
      label: "Alpha Road",
      geometry: null,
      travelMinutes: 12,
      distanceMeters: 9100,
    },
    {
      edgeId: "edge-3",
      label: "Pine Junction Route",
      geometry: {
        type: "LineString",
        coordinates: [
          [-121.63, 39.78],
          [-121.51, 39.8],
        ],
      },
      travelMinutes: 10,
      distanceMeters: 7900,
    },
  ],
  total: 205,
  missingEdgeIds: [],
});

export const roadEdgesByGraphVersion: Record<string, object> = {
  "roads-v1": redwoodRoadEdgesResponse,
  "roads-v2": roadEdgeListSchema.parse({
    items: [redwoodRoadEdgesResponse.items[0]],
    total: 1,
    missingEdgeIds: [],
  }),
  "roads-bear-v1": roadEdgeListSchema.parse({
    items: [],
    total: 0,
    missingEdgeIds: [],
  }),
};

export const baselineScenarioVersionResponse = scenarioVersionSchema.parse({
  id: "scenario-version-redwood-1",
  scenarioId: "scenario-redwood",
  incidentId: REDWOOD_ID,
  incidentSnapshotId: incidentDetailResponse.snapshotId,
  version: 1,
  graphVersion: "roads-v1",
  roadClosures: [],
  weatherOverrides: [],
  resourceOverrides: [],
});

export const scenarioVersionTwoResponse = scenarioVersionSchema.parse({
  ...baselineScenarioVersionResponse,
  id: "scenario-version-redwood-2",
  version: 2,
  roadClosures: [{ edgeId: "edge-2" }],
  weatherOverrides: [
    { windSpeedMps: 14.5, windDirectionDegrees: 225 },
  ],
  resourceOverrides: [{ resourceId: "engine-1", available: false }],
});

const baselineOutcome = {
  scenarioRisk: {
    score: 82,
    algorithmVersion: "risk-v1",
    contributions: redwoodContributions,
  },
  weightedRiskCovered: 75,
  weightedRiskUncovered: 7,
  totalTravelMinutes: 18,
  unreachableDestinationIds: [],
  unavailableResourceIds: [],
};

export const baselineRecommendationResponse = recommendationSchema.parse({
  id: "recommendation-redwood-1",
  scenarioVersionId: baselineScenarioVersionResponse.id,
  incidentSnapshotId: incidentDetailResponse.snapshotId,
  assignments: [
    {
      resourceId: "engine-1",
      destinationId: "community-1",
      route: {
        status: "reachable",
        edgeIds: ["edge-1", "edge-3"],
        distanceMeters: 14300,
        travelMinutes: 18,
        graphVersion: "roads-v1",
        closureHash: "closures-none",
      },
      travelMinutes: 18,
      capacity: 4,
    },
  ],
  uncoveredDestinationIds: [],
  objectiveComponents: {
    travelCost: 18,
    uncoveredRiskPenalty: 0,
    objectiveValue: 18,
  },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 34,
  graphVersion: "roads-v1",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "scenario-input-v1",
  sourceVersions: { road_graph: "roads-v1", risk: "risk-v1" },
  explanation: {
    binding_constraints: ["max_response_minutes"],
    unassigned_resource_ids: [],
  },
  outcome: baselineOutcome,
});

export const scenarioRecommendationResponse = recommendationSchema.parse({
  ...baselineRecommendationResponse,
  id: "recommendation-redwood-2",
  scenarioVersionId: scenarioVersionTwoResponse.id,
  assignments: [],
  uncoveredDestinationIds: ["community-1"],
  objectiveComponents: {
    travelCost: 0,
    uncoveredRiskPenalty: 76,
    objectiveValue: 76,
  },
  solverStatus: "FEASIBLE",
  runtimeMilliseconds: 41,
  explanation: {
    binding_constraints: ["road_closures"],
    unassigned_resource_ids: ["engine-1"],
  },
  outcome: {
    ...baselineOutcome,
    scenarioRisk: {
      ...baselineOutcome.scenarioRisk,
      score: 76,
    },
    weightedRiskCovered: 0,
    weightedRiskUncovered: 76,
    totalTravelMinutes: 0,
    unreachableDestinationIds: ["community-1"],
    unavailableResourceIds: ["engine-1"],
  },
});
