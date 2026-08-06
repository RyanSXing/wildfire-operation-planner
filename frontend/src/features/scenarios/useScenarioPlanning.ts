import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClientError } from "../../api/client";
import {
  useCreateScenarioMutation,
  useCreateScenarioVersionMutation,
  useDecisionContext,
  useGenerateRecommendationMutation,
  useRoadEdges,
} from "../../api/hooks";
import type {
  IncidentDetail,
  Recommendation,
  ScenarioVersion,
  ScenarioVersionCreateRequest,
} from "../../api/types";
import type { PlanningMapSelection } from "../map/planningOverlays";

export type ScenarioPlanningPanelProps = {
  incident: IncidentDetail;
  planningDisabled: boolean;
  freshnessToken: string;
  onPlanningMapSelection?: (
    selection: PlanningMapSelection | null,
    ownerIncidentId: string,
  ) => void;
};

/**
 * The scenario planning flow, with no presentation attached.
 *
 * This is a concurrency state machine, not view logic: it decides when a
 * planning session has gone stale, which in-flight result is still allowed to
 * settle, and which commands are legal right now. It was extracted verbatim
 * from ScenarioPlanningPanel so the presentation could be replaced without
 * putting any of that at risk — the behaviour is pinned by
 * ScenarioPlanningPanel.test.tsx, which was not changed.
 */
export function useScenarioPlanning({
  incident,
  planningDisabled,
  freshnessToken,
  onPlanningMapSelection,
}: ScenarioPlanningPanelProps) {
  const contextQuery = useDecisionContext(incident.id);
  const [graphChoice, setGraphChoice] = useState<string | null>(null);
  const [scenarioName, setScenarioName] = useState("");
  const [roadSearchDraft, setRoadSearchDraft] = useState("");
  const [roadSearch, setRoadSearch] = useState("");
  const [baselineVersion, setBaselineVersion] =
    useState<ScenarioVersion | null>(null);
  const selectedGraph =
    baselineVersion?.graphVersion ??
    graphForContext(graphChoice, contextQuery.data);
  const roadQuery = useRoadEdges(selectedGraph, {
    q: roadSearch || undefined,
    limit: 200,
  });
  const createScenario = useCreateScenarioMutation();
  const createVersion = useCreateScenarioVersionMutation();
  const generateRecommendation = useGenerateRecommendationMutation();
  const sessionGeneration = useRef(0);
  const mounted = useRef(false);
  const latestPolicy = useRef<PlanningPolicy>({
    incidentId: incident.id,
    snapshotId: incident.snapshotId,
    planningDisabled,
    freshnessToken,
  });

  const [baselineRecommendation, setBaselineRecommendation] =
    useState<Recommendation | null>(null);
  const [latestVersion, setLatestVersion] = useState<ScenarioVersion | null>(
    null,
  );
  const [lastSuccessful, setLastSuccessful] =
    useState<GeneratedRecommendation | null>(null);
  const [failedGenerationVersionId, setFailedGenerationVersionId] = useState<
    string | null
  >(null);
  const [commandError, setCommandError] = useState<unknown>(null);
  const [staleLatched, setStaleLatched] = useState(false);
  const [sessionFreshnessToken, setSessionFreshnessToken] = useState<
    string | null
  >(null);
  const [mapMode, setMapMode] = useState<"baseline" | "scenario">("baseline");
  const [decidedRecommendationId, setDecidedRecommendationId] = useState<
    string | null
  >(null);
  const resourceLabels = labelsForResources(incident.simulatedResources);

  useLayoutEffect(() => {
    latestPolicy.current = {
      incidentId: incident.id,
      snapshotId: incident.snapshotId,
      planningDisabled,
      freshnessToken,
    };
  }, [freshnessToken, incident.id, incident.snapshotId, planningDisabled]);

  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      sessionGeneration.current += 1;
    };
  }, []);

  const snapshotMismatch = planningSnapshotIds(
    baselineVersion,
    latestVersion,
    baselineRecommendation,
    lastSuccessful,
  ).some((snapshotId) => snapshotId !== incident.snapshotId);
  const freshnessMismatch =
    sessionFreshnessToken !== null &&
    sessionFreshnessToken !== freshnessToken;
  const sessionStale = snapshotMismatch || freshnessMismatch || staleLatched;

  useEffect(() => {
    if (snapshotMismatch || freshnessMismatch) {
      setStaleLatched(true);
    }
  }, [freshnessMismatch, snapshotMismatch]);

  const commandsDisabled = planningDisabled || sessionStale;
  const bootstrapPending =
    createScenario.isPending || generateRecommendation.isPending;
  const canBootstrap = selectedGraph.length > 0 && !commandsDisabled;
  const planningMapSelection = useMemo<PlanningMapSelection | null>(
    () =>
      mapMode === "scenario" && latestVersion
      ? {
          incidentId: incident.id,
          scenarioVersion: latestVersion,
          recommendation:
            lastSuccessful?.version.id === latestVersion.id &&
            lastSuccessful.recommendation.scenarioVersionId === latestVersion.id &&
            lastSuccessful.recommendation.graphVersion === latestVersion.graphVersion
              ? lastSuccessful.recommendation
              : null,
          freshness: sessionStale ? "stale" : "current",
        }
        : null,
    [incident.id, lastSuccessful, latestVersion, mapMode, sessionStale],
  );

  useLayoutEffect(() => {
    onPlanningMapSelection?.(planningMapSelection, incident.id);
  }, [incident.id, onPlanningMapSelection, planningMapSelection]);

  const isActiveSession = (generation: number): boolean =>
    mounted.current && generation === sessionGeneration.current;

  const canSettleForVersion = (
    version: ScenarioVersion,
    generation: number,
  ): boolean =>
    isActiveSession(generation) &&
    latestPolicy.current.incidentId === version.incidentId;

  const canStartGeneration = (
    version: ScenarioVersion,
    generation: number,
  ): boolean => {
    const policy = latestPolicy.current;
    return (
      canSettleForVersion(version, generation) &&
      !policy.planningDisabled &&
      policy.snapshotId === version.incidentSnapshotId
    );
  };

  const generateForVersion = async (
    version: ScenarioVersion,
    baseline: boolean,
    generation = sessionGeneration.current,
  ): Promise<void> => {
    if (
      !canStartGeneration(version, generation) ||
      createVersion.isPending ||
      generateRecommendation.isPending
    ) {
      return;
    }
    const generationFreshnessToken = latestPolicy.current.freshnessToken;
    setCommandError(null);
    try {
      const recommendation = await generateRecommendation.mutateAsync({
        versionId: version.id,
        body: recommendationRequest,
      });
      if (!canSettleForVersion(version, generation)) {
        return;
      }
      const successful = { version, recommendation };
      if (baseline) {
        setBaselineRecommendation(recommendation);
      }
      setLastSuccessful(successful);
      setFailedGenerationVersionId(null);
      if (
        version.incidentSnapshotId !== latestPolicy.current.snapshotId ||
        recommendation.incidentSnapshotId !== latestPolicy.current.snapshotId ||
        generationFreshnessToken !== latestPolicy.current.freshnessToken
      ) {
        setStaleLatched(true);
      }
    } catch (error) {
      if (!canSettleForVersion(version, generation)) {
        return;
      }
      setCommandError(error);
      setFailedGenerationVersionId(version.id);
      if (
        isScenarioStale(error) ||
        generationFreshnessToken !== latestPolicy.current.freshnessToken
      ) {
        setStaleLatched(true);
      }
    }
  };

  const bootstrap = async (): Promise<void> => {
    if (!canBootstrap || bootstrapPending) {
      return;
    }
    if (baselineVersion) {
      await generateForVersion(baselineVersion, true);
      return;
    }

    const generation = sessionGeneration.current;
    setCommandError(null);
    const trimmedName = scenarioName.trim();
    try {
      const version = await createScenario.mutateAsync({
        incidentId: incident.id,
        body: {
          graphVersion: selectedGraph,
          objective: "minimize-response-time",
          ...(trimmedName ? { name: trimmedName } : {}),
          algorithmConfigVersion: "scenario-v1",
        },
      });
      if (!isActiveSession(generation)) {
        return;
      }
      const policy = latestPolicy.current;
      if (policy.incidentId !== version.incidentId) {
        return;
      }
      setSessionFreshnessToken(policy.freshnessToken);
      setBaselineVersion(version);
      setLatestVersion(version);
      setFailedGenerationVersionId(null);
      if (version.incidentSnapshotId !== policy.snapshotId) {
        setStaleLatched(true);
        return;
      }
      if (policy.planningDisabled) {
        return;
      }
      await generateForVersion(version, true, generation);
    } catch (error) {
      if (!isActiveSession(generation)) {
        return;
      }
      setCommandError(error);
      if (isScenarioStale(error)) {
        setStaleLatched(true);
      }
    }
  };

  const saveVersion = async (
    request: ScenarioVersionCreateRequest,
  ): Promise<void> => {
    if (
      !latestVersion ||
      commandsDisabled ||
      createVersion.isPending ||
      generateRecommendation.isPending
    ) {
      return;
    }
    const generation = sessionGeneration.current;
    setCommandError(null);
    try {
      const version = await createVersion.mutateAsync({
        scenarioId: latestVersion.scenarioId,
        body: request,
      });
      if (!isActiveSession(generation)) {
        return;
      }
      setLatestVersion(version);
      setFailedGenerationVersionId(null);
    } catch (error) {
      if (!isActiveSession(generation)) {
        return;
      }
      setCommandError(error);
      if (isScenarioStale(error)) {
        setStaleLatched(true);
      }
    }
  };

  const resetPlanning = (): void => {
    sessionGeneration.current += 1;
    createScenario.reset();
    createVersion.reset();
    generateRecommendation.reset();
    setGraphChoice(null);
    setScenarioName("");
    setRoadSearchDraft("");
    setRoadSearch("");
    setBaselineVersion(null);
    setBaselineRecommendation(null);
    setLatestVersion(null);
    setLastSuccessful(null);
    setFailedGenerationVersionId(null);
    setCommandError(null);
    setStaleLatched(false);
    setSessionFreshnessToken(null);
    setMapMode("baseline");
    setDecidedRecommendationId(null);
  };


  return {
    baselineRecommendation,
    baselineVersion,
    bootstrap,
    bootstrapPending,
    canBootstrap,
    commandError,
    commandsDisabled,
    contextQuery,
    createScenario,
    createVersion,
    decidedRecommendationId,
    failedGenerationVersionId,
    generateForVersion,
    generateRecommendation,
    lastSuccessful,
    latestVersion,
    mapMode,
    resetPlanning,
    resourceLabels,
    roadQuery,
    roadSearchDraft,
    saveVersion,
    scenarioName,
    selectedGraph,
    sessionStale,
    setDecidedRecommendationId,
    setGraphChoice,
    setMapMode,
    setRoadSearch,
    setRoadSearchDraft,
    setScenarioName,
    setStaleLatched,
  };
}

type GeneratedRecommendation = {
  version: ScenarioVersion;
  recommendation: Recommendation;
};

type PlanningPolicy = {
  incidentId: string;
  snapshotId: string;
  planningDisabled: boolean;
  freshnessToken: string;
};

const recommendationRequest = {
  maxResponseMinutes: 30,
  maxSolverSeconds: 2,
} as const;

function labelsForResources(
  resources: readonly { resourceId: string; resourceType: string }[],
): Record<string, string> {
  const counts = new Map<string, number>();
  return Object.fromEntries(
    [...resources]
      .sort((left, right) => left.resourceId.localeCompare(right.resourceId))
      .map((resource) => {
        const ordinal = (counts.get(resource.resourceType) ?? 0) + 1;
        counts.set(resource.resourceType, ordinal);
        return [resource.resourceId, `${titleCase(resource.resourceType)} ${ordinal}`];
      }),
  );
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function graphForContext(
  choice: string | null,
  context: ReturnType<typeof useDecisionContext>["data"],
): string {
  if (!context || context.availableGraphs.length === 0) {
    return "";
  }
  const graphVersions = new Set(
    context.availableGraphs.map(({ graphVersion }) => graphVersion),
  );
  if (choice && graphVersions.has(choice)) {
    return choice;
  }
  if (
    context.defaultGraphVersion &&
    graphVersions.has(context.defaultGraphVersion)
  ) {
    return context.defaultGraphVersion;
  }
  return context.availableGraphs[0].graphVersion;
}

function planningSnapshotIds(
  baselineVersion: ScenarioVersion | null,
  latestVersion: ScenarioVersion | null,
  baselineRecommendation: Recommendation | null,
  lastSuccessful: GeneratedRecommendation | null,
): string[] {
  return [
    baselineVersion?.incidentSnapshotId,
    latestVersion?.incidentSnapshotId,
    baselineRecommendation?.incidentSnapshotId,
    lastSuccessful?.recommendation.incidentSnapshotId,
  ].filter((snapshotId): snapshotId is string => snapshotId !== undefined);
}

export function isScenarioStale(error: unknown): boolean {
  return error instanceof ApiClientError && error.code === "scenario_stale";
}
