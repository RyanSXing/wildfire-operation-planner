import { z } from "zod";

import { jsonObjectSchema, timestampSchema } from "./types";

export const exerciseObjectiveSchema = z.enum([
  "fastest-response",
  "protect-critical-services",
  "maximize-population-coverage",
]);

export const exerciseActionSchema = z.enum([
  "select-objective",
  "generate-plan",
  "advance",
  "apply-override",
  "approve-plan",
  "view-debrief",
  "start-new-exercise",
]);

const positionSchema = z.object({
  longitude: z.number(),
  latitude: z.number(),
});

export const exerciseAssetSchema = z
  .object({
    assetId: z.string(),
    assetKind: z.string(),
    name: z.string(),
    position: positionSchema,
    sourceName: z.string(),
    sourceVersion: z.string(),
    sourceRecordId: z.string(),
    citationUrl: z.string(),
    provenance: z.string(),
  });

export const exerciseResourceSchema = z
  .object({
    resourceId: z.string(),
    resourceType: z.string(),
    capabilities: z.array(z.string()),
    capacity: z.number(),
    available: z.boolean(),
    position: positionSchema,
    provenance: z.string(),
  });

export const exerciseTaskSchema = z
  .object({
    taskId: z.string(),
    incidentKey: z.string(),
    assetId: z.string(),
    taskType: z.string(),
    requiredCapability: z.string(),
    requiredCapacity: z.number(),
    deadlineMinutes: z.number(),
    affectedPopulation: z.number(),
    criticalService: z.boolean(),
    basePriority: z.number(),
    provenance: z.string(),
  });

export const exerciseIncidentSchema = z
  .object({
    incidentKey: z.string(),
    name: z.string(),
    provenance: z.string(),
    detectionIdentities: z.array(z.string()).default([]),
    simulatedPosition: positionSchema.nullish(),
  });

export const exerciseDisruptionSchema = z
  .object({
    windSpeedMps: z.number(),
    windDirectionDegrees: z.number(),
    closedEdgeIds: z.array(z.string()),
    provenance: z.string(),
  });

export const exerciseFieldReportSchema = z
  .object({
    reportId: z.string(),
    taskId: z.string(),
    message: z.string(),
    provenance: z.string(),
  });

export const exerciseCheckpointSchema = z
  .object({
    checkpointKey: z.string(),
    title: z.string(),
    situationSummary: z.string(),
    decisionPrompt: z.string(),
    referenceAt: z.string(),
    historicalWeatherIdentity: z.string(),
    incidents: z.array(exerciseIncidentSchema),
    tasks: z.array(exerciseTaskSchema),
    disruption: exerciseDisruptionSchema,
    fieldReports: z.array(exerciseFieldReportSchema).default([]),
  });

export const planRouteSchema = z
  .object({
    status: z.string(),
    edgeIds: z.array(z.string()),
    distanceMeters: z.number(),
    travelMinutes: z.number(),
  });

export const planAssignmentSchema = z
  .object({
    resourceId: z.string(),
    taskId: z.string(),
    incidentId: z.string(),
    assetId: z.string(),
    capacity: z.number(),
    travelMinutes: z.number(),
    route: planRouteSchema,
  });

export const planTaskCoverageSchema = z
  .object({
    taskId: z.string(),
    requiredCapacity: z.number(),
    suppliedCapacity: z.number(),
    covered: z.boolean(),
  });

export const planCandidateFactSchema = z
  .object({
    resourceId: z.string(),
    taskId: z.string(),
    capacity: z.number(),
    available: z.boolean(),
    capabilityCompatible: z.boolean(),
    routeReachable: z.boolean(),
    travelMinutes: z.number().nullish(),
    deadlineMinutes: z.number(),
    eligible: z.boolean(),
  });

export const planChangeSchema = z
  .object({
    code: z.string(),
    summary: z.string(),
    evidence: jsonObjectSchema,
  });

export const planObjectiveComponentsSchema = z
  .object({
    travelCost: z.number(),
    uncoveredTaskPenalty: z.number(),
    objectiveValue: z.number(),
  });

export const planOutputSchema = z
  .object({
    status: z.string(),
    assignments: z.array(planAssignmentSchema),
    uncoveredTaskIds: z.array(z.string()),
    coveredTaskIds: z.array(z.string()),
    taskCoverage: z.array(planTaskCoverageSchema),
    candidateFacts: z.array(planCandidateFactSchema),
    unassignedResourceIds: z.array(z.string()),
    objectiveComponents: planObjectiveComponentsSchema,
    bindingConstraints: z.array(z.string()),
    runtimeMilliseconds: z.number(),
    algorithmVersion: z.string(),
    explanation: z.object({ changes: z.array(planChangeSchema) }),
    versions: jsonObjectSchema,
  });

export const exerciseSessionSchema = z
  .object({
    id: z.string(),
    exerciseId: z.string(),
    definitionVersion: z.string(),
    definitionDigest: z.string(),
    callsign: z.string(),
    displayName: z.string().nullable(),
    checkpointIndex: z.number(),
    objective: exerciseObjectiveSchema.nullable(),
    status: z.string(),
    version: z.number(),
    consequences: jsonObjectSchema,
    expiresAt: timestampSchema,
    allowedActions: z.array(exerciseActionSchema.or(z.string())),
    currentCheckpoint: exerciseCheckpointSchema,
    latestPlan: planOutputSchema.nullable(),
  });

export const sandboxWindPresetSchema = z.object({
  key: z.string(),
  disruption: exerciseDisruptionSchema,
});

export const sandboxPriorityPresetSchema = z.object({
  key: z.enum(["standard", "elevated", "urgent"]),
  multiplier: z.number(),
});

/** The bounded inputs the sandbox endpoint accepts, as advertised by the API. */
export const sandboxOptionsSchema = z.object({
  checkpointKeys: z.array(z.string()),
  closureEdgeIds: z.array(z.string()),
  windPresets: z.array(sandboxWindPresetSchema),
  priorityPresets: z.array(sandboxPriorityPresetSchema),
});

export const exerciseMetadataSchema = z
  .object({
    exerciseId: z.string(),
    version: z.string(),
    name: z.string(),
    description: z.string(),
    checkpointCount: z.number(),
    objectives: z.array(z.string()),
    safetyStatement: z.string(),
    assets: z.array(exerciseAssetSchema),
    resources: z.array(exerciseResourceSchema),
    sandbox: sandboxOptionsSchema,
  });

export const exercisePlanSchema = z
  .object({
    id: z.string(),
    sessionId: z.string(),
    checkpointKey: z.string(),
    inputHash: z.string(),
    inputData: jsonObjectSchema,
    outputData: planOutputSchema,
    versions: jsonObjectSchema,
    createdAt: timestampSchema,
  });

export const exercisePlanCommandSchema = z
  .object({
    session: exerciseSessionSchema,
    plan: exercisePlanSchema,
  });

export const sandboxPlanSchema = z
  .object({
    sandbox: z.literal(true),
    sessionVersion: z.number(),
    inputHash: z.string(),
    input: jsonObjectSchema,
    output: planOutputSchema,
  });

export const exerciseEventSchema = z
  .object({
    id: z.string(),
    sessionId: z.string(),
    eventType: z.string(),
    actorCallsign: z.string(),
    displayName: z.string().nullable(),
    expectedSessionVersion: z.number(),
    resultingSessionVersion: z.number(),
    beforeState: jsonObjectSchema,
    afterState: jsonObjectSchema,
    inputs: jsonObjectSchema,
    note: z.string().nullable(),
    occurredAt: timestampSchema,
  });

export const exerciseAuditSchema = z.object({
  items: z.array(exerciseEventSchema),
});

export const exerciseDebriefSchema = z
  .object({
    session: jsonObjectSchema,
    plans: z.array(exercisePlanSchema),
    finalPlan: exercisePlanSchema,
    events: z.array(exerciseEventSchema),
  });

export type ExerciseObjective = z.infer<typeof exerciseObjectiveSchema>;
export type ExerciseAsset = z.infer<typeof exerciseAssetSchema>;
export type ExerciseResource = z.infer<typeof exerciseResourceSchema>;
export type ExerciseTask = z.infer<typeof exerciseTaskSchema>;
export type ExerciseIncident = z.infer<typeof exerciseIncidentSchema>;
export type ExerciseDisruption = z.infer<typeof exerciseDisruptionSchema>;
export type ExerciseFieldReport = z.infer<typeof exerciseFieldReportSchema>;
export type ExerciseCheckpoint = z.infer<typeof exerciseCheckpointSchema>;
export type ExerciseSession = z.infer<typeof exerciseSessionSchema>;
export type ExerciseMetadata = z.infer<typeof exerciseMetadataSchema>;
export type ExercisePlan = z.infer<typeof exercisePlanSchema>;
export type ExercisePlanCommand = z.infer<typeof exercisePlanCommandSchema>;
export type ExerciseEvent = z.infer<typeof exerciseEventSchema>;
export type ExerciseAudit = z.infer<typeof exerciseAuditSchema>;
export type ExerciseDebrief = z.infer<typeof exerciseDebriefSchema>;
export type PlanOutput = z.infer<typeof planOutputSchema>;
export type PlanAssignment = z.infer<typeof planAssignmentSchema>;
export type PlanChange = z.infer<typeof planChangeSchema>;
export type PlanCandidateFact = z.infer<typeof planCandidateFactSchema>;
export type SandboxPlan = z.infer<typeof sandboxPlanSchema>;
export type SandboxOptions = z.infer<typeof sandboxOptionsSchema>;
export type SandboxWindPreset = z.infer<typeof sandboxWindPresetSchema>;
export type SandboxPriorityPreset = z.infer<typeof sandboxPriorityPresetSchema>;

export type SandboxPlanRequest = {
  expectedVersion: number;
  checkpointKey: string;
  objective: ExerciseObjective;
  closedEdgeIds: readonly string[];
  windPreset: string;
  unavailableResourceIds: readonly string[];
  taskPriorityPresets: Record<string, SandboxPriorityPreset["key"]>;
  lockedAssignments: readonly { resourceId: string; taskId: string }[];
};
