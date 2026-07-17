import { z } from "zod";

export const freshnessSchema = z.enum(["fresh", "stale", "unavailable"]);
const MAX_NESTING_DEPTH = 64;

type JsonValueShape =
  | null
  | boolean
  | number
  | string
  | JsonValueShape[]
  | { [key: string]: JsonValueShape };

export const jsonValueSchema = z.custom<JsonValueShape>(isBoundedJsonValue, {
  error: "Expected a bounded JSON value",
});
export const jsonObjectSchema = z.record(z.string(), jsonValueSchema);
export const timestampSchema = z.iso.datetime({ offset: true });
const positionSchema = z.tuple([z.number(), z.number()]).rest(z.number());
const lineStringCoordinatesSchema = z.array(positionSchema).min(2);
const linearRingSchema = z.array(positionSchema).min(4);
const polygonCoordinatesSchema = z.array(linearRingSchema).min(1);

const coordinateGeometrySchema = z.discriminatedUnion("type", [
  z
    .object({ type: z.literal("Point"), coordinates: positionSchema })
    .passthrough(),
  z
    .object({
      type: z.literal("MultiPoint"),
      coordinates: z.array(positionSchema).min(1),
    })
    .passthrough(),
  z
    .object({
      type: z.literal("LineString"),
      coordinates: lineStringCoordinatesSchema,
    })
    .passthrough(),
  z
    .object({
      type: z.literal("MultiLineString"),
      coordinates: z.array(lineStringCoordinatesSchema).min(1),
    })
    .passthrough(),
  z
    .object({
      type: z.literal("Polygon"),
      coordinates: polygonCoordinatesSchema,
    })
    .passthrough(),
  z
    .object({
      type: z.literal("MultiPolygon"),
      coordinates: z.array(polygonCoordinatesSchema).min(1),
    })
    .passthrough(),
]);

type GeometryValue =
  | z.infer<typeof coordinateGeometrySchema>
  | {
      type: "GeometryCollection";
      geometries: GeometryValue[];
      [key: string]: unknown;
    };

export const geometrySchema = z.custom<GeometryValue>(isBoundedGeometry, {
  error: "Expected bounded GeoJSON geometry",
});

function isBoundedJsonValue(value: unknown): value is JsonValueShape {
  const pending: Array<{ value: unknown; depth: number }> = [
    { value, depth: 0 },
  ];
  const visited = new WeakSet<object>();

  while (pending.length > 0) {
    const current = pending.pop();
    if (!current) {
      break;
    }

    if (
      current.value === null ||
      typeof current.value === "string" ||
      typeof current.value === "boolean"
    ) {
      continue;
    }
    if (typeof current.value === "number") {
      if (!Number.isFinite(current.value)) {
        return false;
      }
      continue;
    }
    if (
      current.depth >= MAX_NESTING_DEPTH ||
      typeof current.value !== "object" ||
      visited.has(current.value)
    ) {
      return false;
    }

    visited.add(current.value);
    if (Array.isArray(current.value)) {
      for (const item of current.value) {
        pending.push({ value: item, depth: current.depth + 1 });
      }
      continue;
    }
    if (!isPlainRecord(current.value)) {
      return false;
    }
    for (const item of Object.values(current.value)) {
      pending.push({ value: item, depth: current.depth + 1 });
    }
  }

  return true;
}

function isBoundedGeometry(value: unknown): value is GeometryValue {
  const pending: Array<{ value: unknown; depth: number }> = [
    { value, depth: 0 },
  ];

  while (pending.length > 0) {
    const current = pending.pop();
    if (!current || !isPlainRecord(current.value)) {
      return false;
    }

    if (current.value.type === "GeometryCollection") {
      if (
        current.depth >= MAX_NESTING_DEPTH ||
        !Array.isArray(current.value.geometries)
      ) {
        return false;
      }
      for (const geometry of current.value.geometries) {
        pending.push({ value: geometry, depth: current.depth + 1 });
      }
      continue;
    }

    try {
      if (!coordinateGeometrySchema.safeParse(current.value).success) {
        return false;
      }
    } catch {
      return false;
    }
  }

  return true;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export const riskContributionSchema = z.object({
  name: z.string().min(1),
  rawValue: jsonValueSchema,
  normalizedValue: z.number(),
  weight: z.number(),
  contribution: z.number(),
});

export const riskSchema = z.object({
  score: z.number(),
  algorithmVersion: z.string().min(1),
  contributions: z.array(riskContributionSchema),
});

export const detailedRiskSchema = riskSchema.extend({
  configuration: jsonObjectSchema,
});

export const incidentSummarySchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  risk: riskSchema,
  exposedAssetCount: z.number().int().nonnegative(),
  lastObservedAt: timestampSchema,
  freshness: freshnessSchema,
});

export const incidentListSchema = z.object({
  items: z.array(incidentSummarySchema),
});

export const detectionSchema = z.object({
  sourceName: z.string().min(1),
  sourceRecordId: z.string().min(1),
  observedAt: timestampSchema,
  geometry: geometrySchema,
  confidence: z.number(),
  intensity: z.number().nullable(),
});

export const exposedAssetSchema = z.object({
  assetId: z.string().min(1),
  assetKind: z.string().min(1),
  name: z.string().min(1),
  population: z.number().int().nonnegative().nullable(),
  capacity: z.number().int().nonnegative().nullable(),
  sourceName: z.string().nullable(),
  sourceVersion: z.string().nullable(),
  geometry: geometrySchema,
  distanceMeters: z.number().nonnegative(),
  bearingDegrees: z.number().nullable(),
});

export const simulatedResourceSchema = z.object({
  resourceId: z.string().min(1),
  resourceType: z.string().min(1),
  capabilities: z.array(z.string()),
  capacity: z.number().int().nonnegative(),
  available: z.boolean(),
  status: z.string().min(1),
  geometry: geometrySchema,
  simulated: z.literal(true),
  simulationLabel: z.literal("simulated"),
});

export const incidentDetailSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  status: z.string().min(1),
  snapshotId: z.string().min(1),
  snapshotVersion: z.number().int().positive(),
  geometry: geometrySchema,
  firstObservedAt: timestampSchema,
  lastObservedAt: timestampSchema,
  freshness: freshnessSchema,
  risk: detailedRiskSchema,
  detections: z.array(detectionSchema),
  exposedAssets: z.array(exposedAssetSchema),
  simulatedResources: z.array(simulatedResourceSchema),
  sourceVersions: jsonObjectSchema,
});

export const timelineFrameSchema = z.object({
  snapshotId: z.string().min(1),
  snapshotVersion: z.number().int().positive(),
  capturedAt: timestampSchema,
  referenceAt: timestampSchema,
  lastObservedAt: timestampSchema,
  geometry: geometrySchema,
  risk: riskSchema,
  detections: z.array(detectionSchema),
  exposedAssetCount: z.number().int().nonnegative(),
  freshness: freshnessSchema,
});

export const incidentTimelineSchema = z.object({
  items: z.array(timelineFrameSchema),
});

export const sourceStatusSchema = z.object({
  sourceName: z.string().min(1),
  lastAttemptedAt: timestampSchema,
  lastSuccessAt: timestampSchema.nullable(),
  nextRetryAt: timestampSchema.nullable(),
  freshness: freshnessSchema,
  acceptedCount: z.number().int().nonnegative(),
  deduplicatedCount: z.number().int().nonnegative(),
  quarantinedCount: z.number().int().nonnegative(),
  lastErrorCode: z.string().nullable(),
});

export const sourceStatusListSchema = z.object({
  items: z.array(sourceStatusSchema),
});

export const apiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    details: jsonObjectSchema,
  }),
});

export type Freshness = z.infer<typeof freshnessSchema>;
export type JsonValue = z.infer<typeof jsonValueSchema>;
export type JsonObject = z.infer<typeof jsonObjectSchema>;
export type Geometry = z.infer<typeof geometrySchema>;
export type RiskContribution = z.infer<typeof riskContributionSchema>;
export type Risk = z.infer<typeof riskSchema>;
export type DetailedRisk = z.infer<typeof detailedRiskSchema>;
export type IncidentSummary = z.infer<typeof incidentSummarySchema>;
export type IncidentList = z.infer<typeof incidentListSchema>;
export type Detection = z.infer<typeof detectionSchema>;
export type ExposedAsset = z.infer<typeof exposedAssetSchema>;
export type SimulatedResource = z.infer<typeof simulatedResourceSchema>;
export type IncidentDetail = z.infer<typeof incidentDetailSchema>;
export type TimelineFrame = z.infer<typeof timelineFrameSchema>;
export type IncidentTimeline = z.infer<typeof incidentTimelineSchema>;
export type SourceStatus = z.infer<typeof sourceStatusSchema>;
export type SourceStatusList = z.infer<typeof sourceStatusListSchema>;
