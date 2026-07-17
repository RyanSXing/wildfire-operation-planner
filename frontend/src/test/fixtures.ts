import { incidentListSchema } from "../api/types";

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
