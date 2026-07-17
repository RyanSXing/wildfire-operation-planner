import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
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
import { DecisionDialog } from "../decisions/DecisionDialog";
import { AuditDrawer } from "../decisions/AuditDrawer";
import { RecommendationPanel } from "../decisions/RecommendationPanel";
import { ScenarioComparison } from "./ScenarioComparison";
import { ScenarioEditor } from "./ScenarioEditor";
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

const roadNumberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 3,
});

export function ScenarioPlanningPanel({
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
  };

  return (
    <section
      className="decision-workspace__section scenario-planning-panel"
      aria-label="Scenario planning"
    >
      <div className="decision-workspace__section-heading">
        <h3>Scenario planning</h3>
        <span className="snapshot-context">Current snapshot</span>
      </div>

      {planningDisabled ? (
        <p className="scenario-planning-panel__policy" role="status">
          Return to the current snapshot to plan.
        </p>
      ) : null}
      {sessionStale ? (
        <p role="alert" aria-label="Stale planning session">
          Planning state is stale. Start over with the current snapshot.
        </p>
      ) : null}

      {contextQuery.isPending ? (
        <p role="status" aria-label="Planning context status">
          Loading planning context…
        </p>
      ) : contextQuery.isError ? (
        <LocalReadFailure
          label="Planning context unavailable"
          message="Planning context could not be loaded."
          retryLabel="Retry planning context"
          onRetry={() => void contextQuery.refetch()}
        />
      ) : !contextQuery.data ||
        (!baselineVersion && contextQuery.data.availableGraphs.length === 0) ? (
        <p role="status">No road graphs are available for planning.</p>
      ) : (
        <>
          <div className="scenario-planning-panel__configuration">
            <label>
              Road graph
              <select
                value={selectedGraph}
                disabled={baselineVersion !== null}
                onChange={(event) => setGraphChoice(event.currentTarget.value)}
              >
                {baselineVersion &&
                !contextQuery.data.availableGraphs.some(
                  ({ graphVersion }) =>
                    graphVersion === baselineVersion.graphVersion,
                ) ? (
                  <option value={baselineVersion.graphVersion}>
                    {baselineVersion.graphVersion} (locked baseline)
                  </option>
                ) : null}
                {contextQuery.data.availableGraphs.map((graph) => (
                  <option value={graph.graphVersion} key={graph.graphVersion}>
                    {graph.graphVersion} ({graph.edgeCount} edges)
                  </option>
                ))}
              </select>
            </label>
            <label>
              Scenario name (optional)
              <input
                type="text"
                value={scenarioName}
                disabled={baselineVersion !== null}
                onChange={(event) => setScenarioName(event.currentTarget.value)}
              />
            </label>
          </div>

          <RoadCatalog
            roadQuery={roadQuery}
            searchDraft={roadSearchDraft}
            onSearchDraftChange={setRoadSearchDraft}
            onSearch={(event) => {
              event.preventDefault();
              setRoadSearch(roadSearchDraft.trim());
            }}
          />

          {latestVersion ? (
            <fieldset aria-label="Scenario map selection">
              <legend>Map overlays</legend>
              <label>
                <input
                  type="radio"
                  name={`scenario-map-${incident.id}`}
                  checked={mapMode === "baseline"}
                  onChange={() => setMapMode("baseline")}
                />
                Observed baseline (no scenario overlays)
              </label>
              <label>
                <input
                  type="radio"
                  name={`scenario-map-${incident.id}`}
                  checked={mapMode === "scenario"}
                  onChange={() => setMapMode("scenario")}
                />
                Scenario version {latestVersion.version}
              </label>
            </fieldset>
          ) : null}

          {!baselineRecommendation ? (
            <button
              type="button"
              disabled={!canBootstrap || bootstrapPending}
              onClick={() => void bootstrap()}
            >
              {bootstrapPending
                ? baselineVersion
                  ? "Generating baseline recommendation"
                  : "Creating baseline scenario"
                : baselineVersion
                  ? "Retry baseline recommendation"
                  : "Create baseline and generate recommendation"}
            </button>
          ) : null}

          {baselineRecommendation && latestVersion ? (
            <section
              className="scenario-planning-panel__editor"
              aria-label="Immutable scenario branch"
            >
              <h4>Immutable scenario branch</h4>
              <p>
                Active scenario version {latestVersion.version}. Saving creates
                a new immutable version.
              </p>
              <ScenarioEditor
                roadEdges={roadQuery.data?.items ?? []}
                resources={incident.simulatedResources}
                version={latestVersion}
                busy={createVersion.isPending}
                disabled={
                  commandsDisabled || generateRecommendation.isPending
                }
                errorMessage={null}
                onSubmit={(request) => void saveVersion(request)}
              />
            </section>
          ) : null}

          {baselineRecommendation &&
          latestVersion &&
          lastSuccessful?.version.id !== latestVersion.id ? (
            <p role="status" aria-live="polite">
              Active version {latestVersion.version} has no successful
              recommendation yet.
              {failedGenerationVersionId === latestVersion.id
                ? " The previous successful result remains visible."
                : ""}
            </p>
          ) : null}

          {baselineRecommendation &&
          latestVersion &&
          baselineVersion &&
          latestVersion.id !== baselineVersion.id ? (
            <button
              type="button"
              disabled={
                commandsDisabled ||
                generateRecommendation.isPending ||
                createVersion.isPending
              }
              onClick={() => void generateForVersion(latestVersion, false)}
            >
              {generateRecommendation.isPending
                ? `Generating recommendation for version ${latestVersion.version}`
                : `Generate recommendation for version ${latestVersion.version}`}
            </button>
          ) : null}
        </>
      )}

      {commandError && !sessionStale ? (
        <p role="alert" aria-label="Planning command error">
          {safeCommandError(commandError)}
        </p>
      ) : null}

      {lastSuccessful && baselineVersion ? (
        <>
          <RecommendationPanel
            recommendation={lastSuccessful.recommendation}
            freshness={sessionStale ? "stale" : "current"}
            versionLabel={recommendationLabel(
              lastSuccessful.version,
              latestVersion,
              baselineVersion,
            )}
          />
          <DecisionDialog
            key={`decision:${lastSuccessful.recommendation.id}`}
            recommendation={lastSuccessful.recommendation}
            freshness={sessionStale ? "stale" : "current"}
            planningDisabled={planningDisabled}
            resources={incident.simulatedResources.map(({ resourceId }) => resourceId)}
            destinations={incident.exposedAssets.map(({ assetId }) => assetId)}
            onStale={() => setStaleLatched(true)}
          />
          <AuditDrawer
            key={`audit:${lastSuccessful.recommendation.id}`}
            recommendationId={lastSuccessful.recommendation.id}
          />
        </>
      ) : null}

      {baselineRecommendation &&
      lastSuccessful &&
      baselineVersion &&
      lastSuccessful.version.id !== baselineVersion.id ? (
        <div className="scenario-planning-panel__table-overflow">
          <ScenarioComparison
            baseline={baselineRecommendation.outcome}
            scenario={lastSuccessful.recommendation.outcome}
          />
        </div>
      ) : null}

      {baselineVersion ||
      commandError ||
      sessionStale ||
      createScenario.isPending ||
      createVersion.isPending ||
      generateRecommendation.isPending ? (
        <button type="button" onClick={resetPlanning}>
          Start over
        </button>
      ) : null}
    </section>
  );
}

function RoadCatalog({
  roadQuery,
  searchDraft,
  onSearchDraftChange,
  onSearch,
}: {
  roadQuery: ReturnType<typeof useRoadEdges>;
  searchDraft: string;
  onSearchDraftChange: (value: string) => void;
  onSearch: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section aria-label="Road catalog">
      <h4>Road catalog</h4>
      <form aria-label="Road edge search" onSubmit={onSearch}>
        <label>
          Search road edges
          <input
            type="search"
            value={searchDraft}
            onChange={(event) => onSearchDraftChange(event.currentTarget.value)}
          />
        </label>
        <button type="submit">Search roads</button>
      </form>

      {roadQuery.isPending ? (
        <p role="status">Loading road catalog…</p>
      ) : roadQuery.isError ? (
        <LocalReadFailure
          label="Road catalog unavailable"
          message="Road catalog could not be loaded."
          retryLabel="Retry road catalog"
          onRetry={() => void roadQuery.refetch()}
        />
      ) : roadQuery.data ? (
        <>
          <p role="status" aria-live="polite">
            Showing {roadQuery.data.items.length} of {roadQuery.data.total} road
            edges.
          </p>
          {roadQuery.data.total > roadQuery.data.items.length ? (
            <p>Road catalog is a bounded subset of matching edges.</p>
          ) : null}
          {roadQuery.data.items.length === 0 ? (
            <p>No matching road edges are available.</p>
          ) : (
            <ul aria-label="Road edge metadata">
              {roadQuery.data.items.map((edge) => (
                <li key={edge.edgeId}>
                  {edge.label} ({edge.edgeId}): {edge.geometry
                    ? "Geometry available"
                    : "Geometry unavailable"}
                  ; {formatNumber(edge.distanceMeters)} m;{" "}
                  {formatNumber(edge.travelMinutes)} min
                </li>
              ))}
            </ul>
          )}
          {roadQuery.data.missingEdgeIds.length > 0 ? (
            <p>
              Missing road edge IDs: {roadQuery.data.missingEdgeIds.join(", ")}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function LocalReadFailure({
  label,
  message,
  retryLabel,
  onRetry,
}: {
  label: string;
  message: string;
  retryLabel: string;
  onRetry: () => void;
}) {
  return (
    <section role="alert" aria-label={label}>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        {retryLabel}
      </button>
    </section>
  );
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

function recommendationLabel(
  version: ScenarioVersion,
  latestVersion: ScenarioVersion | null,
  baselineVersion: ScenarioVersion,
): string {
  if (
    version.id === baselineVersion.id &&
    latestVersion?.id === baselineVersion.id
  ) {
    return `Baseline scenario version ${version.version}`;
  }
  if (version.id === latestVersion?.id) {
    return `Current scenario version ${version.version}`;
  }
  return `Previous successful scenario version ${version.version}`;
}

function safeCommandError(error: unknown): string {
  if (isScenarioStale(error)) {
    return "Planning state is stale. Start over with the current snapshot.";
  }
  if (
    error instanceof ApiClientError &&
    (error.code === "network_error" ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500)
  ) {
    return "Request failed. Retrying the unchanged request is safe.";
  }
  return "Request could not be completed.";
}

function isScenarioStale(error: unknown): boolean {
  return error instanceof ApiClientError && error.code === "scenario_stale";
}

function formatNumber(value: number): string {
  return roadNumberFormatter.format(value);
}
