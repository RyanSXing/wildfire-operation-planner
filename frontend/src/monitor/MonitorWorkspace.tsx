import { lazy, Suspense, useMemo, useState } from "react";

import { useMonitorData, EMPTY_COLLECTION } from "../app/useMonitorData";
import type { IncidentSummary, ScenarioVersionCreateRequest } from "../api/types";
import { DecisionDialog } from "../features/decisions/DecisionDialog";
import { ReplayTimeline } from "../features/incidents/ReplayTimeline";
import { ScenarioEditor } from "../features/scenarios/ScenarioEditor";
import { useScenarioPlanning } from "../features/scenarios/useScenarioPlanning";
import { MonitorDrawer } from "./MonitorDrawer";
import type { MonitorTab } from "./monitorTabs";
import { coverageLine, labelFor } from "./language";
import "./monitor.css";

const OperationsMap = lazy(() =>
  import("../features/map/OperationsMap").then((module) => ({
    default: module.OperationsMap,
  })),
);

/**
 * The live command centre.
 *
 * It runs the same way the Park Fire walkthrough does: a rail showing where you
 * are, a map you work over, and a command bar that offers exactly one next
 * action derived from real state — never a form of controls to interpret.
 * Everything the monitor could always do is still here, said differently.
 */
export function MonitorWorkspace() {
  const data = useMonitorData();
  const [tab, setTab] = useState<MonitorTab>("plan");
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [selection, setSelection] = useState<string | null>(null);

  if (data.incidentsQuery.isPending) {
    return <Splash message="Loading incidents…" />;
  }
  if (data.incidentsQuery.isError) {
    return (
      <Splash
        message="Incident data could not be loaded."
        action={{
          label: "Retry incidents",
          onClick: () => void data.incidentsQuery.refetch(),
        }}
        tone="alert"
        label="Incident queue unavailable"
      />
    );
  }

  return (
    <div className="wf">
      <IncidentRail
        incidents={data.incidents}
        activeIncidentId={data.activeIncidentId}
        onSelect={(incidentId) => {
          if (incidentId !== data.activeIncidentId) {
            data.setPlanningSelection(null);
          }
          data.setSelectedIncidentId(incidentId);
          data.setPlaying(false);
          data.setReplayTime(null);
          setScenarioOpen(false);
        }}
      />

      {data.activeIncidentId === null ? (
        <main className="wf-main">
          <div className="wf-centre">
            <div className="wf-sheet" role="status">
              <p className="wf-prose">No active incidents are available.</p>
            </div>
          </div>
        </main>
      ) : data.incidentDetailLoading ? (
        <main className="wf-main">
          <div className="wf-centre">
            <p className="wf-prose" role="status">
              Loading incident details…
            </p>
          </div>
        </main>
      ) : data.incidentDetailFailed || !data.incident ? (
        <main className="wf-main">
          <div className="wf-centre">
            <div
              className="wf-sheet"
              role="alert"
              aria-label="Incident details unavailable"
            >
              <p className="wf-prose">Incident details could not be loaded.</p>
              <div className="wf-actions">
                <button
                  type="button"
                  className="wf-primary"
                  onClick={() => void data.incidentQuery.refetch()}
                >
                  Retry incident details
                </button>
              </div>
            </div>
          </div>
        </main>
      ) : (
        <PlanningWorkspace
          key={data.currentPanelKey}
          data={data}
          tab={tab}
          onTabChange={setTab}
          scenarioOpen={scenarioOpen}
          onScenarioOpenChange={setScenarioOpen}
          selection={selection}
          onSelectionChange={setSelection}
        />
      )}
    </div>
  );
}

type MonitorData = ReturnType<typeof useMonitorData>;

function PlanningWorkspace({
  data,
  tab,
  onTabChange,
  scenarioOpen,
  onScenarioOpenChange,
  selection,
  onSelectionChange,
}: {
  data: MonitorData;
  tab: MonitorTab;
  onTabChange: (tab: MonitorTab) => void;
  scenarioOpen: boolean;
  onScenarioOpenChange: (open: boolean) => void;
  selection: string | null;
  onSelectionChange: (id: string | null) => void;
}) {
  const incident = data.incident!;
  const planning = useScenarioPlanning({
    incident,
    planningDisabled: data.replaying,
    freshnessToken: data.planningFreshnessToken,
    onPlanningMapSelection: data.handlePlanningSelection,
  });

  const roadNames = useMemo(
    () =>
      new Map(
        (planning.roadQuery.data?.items ?? []).map((edge) => [
          edge.edgeId,
          edge.label,
        ]),
      ),
    [planning.roadQuery.data],
  );

  const recommendation = planning.lastSuccessful?.recommendation ?? null;
  const decided =
    recommendation !== null &&
    planning.decidedRecommendationId === recommendation.id;

  return (
    <>
      <main className="wf-main">
        <Suspense
          fallback={
            <div className="wf-map__fallback" role="status">
              Loading map…
            </div>
          }
        >
          <OperationsMap
            incidentData={data.mapData.incident}
            detectionsData={data.mapData.detections}
            exposedAssetsData={data.mapData.exposedAssets}
            simulatedResourcesData={data.mapData.simulatedResources}
            routesData={
              data.replaying ? EMPTY_COLLECTION : data.planningOverlays.routes
            }
            roadClosuresData={
              data.replaying ? EMPTY_COLLECTION : data.planningOverlays.closures
            }
            unavailableResourcesData={
              data.replaying
                ? EMPTY_COLLECTION
                : data.planningOverlays.unavailableResources
            }
            view={data.replaying ? "replay" : "current"}
          />
        </Suspense>

        <div className="wf-map__top">
          <span className="wf-phase" data-tone={phaseTone(data, planning, decided)}>
            {phaseLabel(data, planning, decided)}
          </span>
          <div className="wf-stats">
            <span className="wf-stat">
              <span>PRIORITY</span>
              {incident.risk.score.toFixed(1)}
            </span>
            <span className="wf-stat">
              <span>EXPOSED</span>
              {incident.exposedAssets.length}
            </span>
            <span className="wf-stat">
              <span>UNITS</span>
              {incident.simulatedResources.filter((r) => r.available).length}/
              {incident.simulatedResources.length}
            </span>
          </div>
        </div>

        <div className="wf-monitor__replay">
          <ReplayTimeline
            startTime={data.startTime}
            currentTime={data.replayTime ?? data.endTime}
            endTime={data.endTime}
            playing={data.playing}
            onSeek={(timestamp) => {
              data.setReplayTime(timestamp);
              data.setPlaying(false);
            }}
            onPlayChange={(nextPlaying) => {
              if (
                nextPlaying &&
                data.frameIndex >= data.frames.length - 1 &&
                data.frames.length > 0
              ) {
                data.setReplayTime(data.frames[0].referenceAt);
              }
              data.setPlaying(nextPlaying);
            }}
          />
        </div>

        {scenarioOpen && (
          <ScenarioPopover
            planning={planning}
            incident={incident}
            onClose={() => onScenarioOpenChange(false)}
            onSubmit={(request) => {
              onScenarioOpenChange(false);
              void planning.saveVersion(request);
            }}
          />
        )}

        {/* One panel at a time: adjusting the assumptions and recording a
            decision are different jobs and must not stack on each other. */}
        {recommendation && !decided && !planning.commandsDisabled && !scenarioOpen && (
          <section
            className="wf-panel wf-panel--above-dock"
            role="dialog"
            aria-label="Recommendation decision controls"
          >
            <div className="wf-panel__head">
              <h2 className="wf-panel__title">Record your decision</h2>
              <button
                type="button"
                className="wf-close"
                aria-label="Close decision controls"
                onClick={() => onTabChange("plan")}
              >
                ✕
              </button>
            </div>
            <DecisionDialog
              key={`decision:${recommendation.id}`}
              recommendation={recommendation}
              freshness={planning.sessionStale ? "stale" : "current"}
              planningDisabled={data.replaying}
              resources={incident.simulatedResources.map(({ resourceId }) => ({
                id: resourceId,
                label: labelFor(planning.resourceLabels, resourceId),
              }))}
              destinations={incident.exposedAssets.map(({ assetId, name }) => ({
                id: assetId,
                label: name,
              }))}
              onStale={() => planning.setStaleLatched(true)}
              onDecisionRecorded={() =>
                planning.setDecidedRecommendationId(recommendation.id)
              }
            />
          </section>
        )}

        <MonitorDock
          data={data}
          planning={planning}
          decided={decided}
          onOpenScenario={() => onScenarioOpenChange(true)}
          onViewAudit={() => onTabChange("audit")}
        />
      </main>

      <MonitorDrawer
        tab={tab}
        onTabChange={onTabChange}
        incident={incident}
        recommendation={recommendation}
        baselineOutcome={
          planning.baselineRecommendation &&
          planning.baselineVersion &&
          planning.lastSuccessful &&
          planning.lastSuccessful.version.id !== planning.baselineVersion.id
            ? planning.baselineRecommendation.outcome
            : null
        }
        version={planning.latestVersion}
        resourceLabels={planning.resourceLabels}
        roadNames={roadNames}
        sources={data.sourcesQuery.data?.items ?? []}
        selectedId={selection}
        onLocate={(_kind, id) => onSelectionChange(id)}
      />
    </>
  );
}

type Planning = ReturnType<typeof useScenarioPlanning>;

function MonitorDock({
  data,
  planning,
  decided,
  onOpenScenario,
  onViewAudit,
}: {
  data: MonitorData;
  planning: Planning;
  decided: boolean;
  onOpenScenario: () => void;
  onViewAudit: () => void;
}) {
  const busy =
    planning.bootstrapPending ||
    planning.createVersion.isPending ||
    planning.generateRecommendation.isPending;
  const error = planning.commandError
    ? "That request could not be completed."
    : null;

  // Replay and staleness are hard stops the operator has to clear first, so
  // they outrank every other state and say exactly how to clear them.
  if (data.replaying) {
    return (
      <Dock
        title="You are looking at a replay frame"
        hint="Planning is locked while the map shows the past. Return to the latest frame to plan."
        error={error}
        actions={
          <button
            type="button"
            className="wf-primary"
            onClick={() => {
              data.setPlaying(false);
              data.setReplayTime(data.endTime);
            }}
          >
            Return to current
          </button>
        }
      />
    );
  }

  if (planning.sessionStale) {
    return (
      <Dock
        title="This planning session is out of date"
        hint="The incident changed underneath it. Start over to plan against the current snapshot."
        tone="alert"
        error={error}
        label="Stale planning session"
        actions={
          <button
            type="button"
            className="wf-primary"
            onClick={planning.resetPlanning}
          >
            Start over
          </button>
        }
      />
    );
  }

  if (planning.contextQuery.isPending) {
    return <Dock title="Loading planning context…" hint="One moment." error={error} />;
  }

  if (
    !planning.contextQuery.data ||
    (!planning.baselineVersion &&
      planning.contextQuery.data.availableGraphs.length === 0)
  ) {
    return (
      <Dock
        title="No road graphs are available for planning"
        hint="Planning needs a road network to route units over."
        error={error}
      />
    );
  }

  if (!planning.baselineVersion) {
    return (
      <Dock
        title="Ready to plan"
        hint="The baseline allocates every available unit over the observed snapshot."
        error={error}
        busy={busy}
        actions={
          <button
            type="button"
            className="wf-primary"
            disabled={!planning.canBootstrap || busy}
            onClick={() => void planning.bootstrap()}
          >
            {busy ? "Planning…" : "Create the baseline plan"}
          </button>
        }
      />
    );
  }

  const recommendation = planning.lastSuccessful?.recommendation ?? null;

  // A saved branch is not planned until a recommendation exists for that exact
  // version; the previous result stays visible but must not be mistaken for it.
  const needsPlanForLatest =
    planning.latestVersion !== null &&
    planning.lastSuccessful?.version.id !== planning.latestVersion.id;

  if (needsPlanForLatest && planning.latestVersion) {
    const version = planning.latestVersion;
    const isBaseline = version.id === planning.baselineVersion?.id;
    return (
      <Dock
        title={
          recommendation
            ? "This branch has not been planned yet"
            : "The baseline is saved"
        }
        hint={
          recommendation
            ? "The result on the right is still the previous version's. Plan this one to compare them."
            : "Generate a recommendation for it, or adjust the assumptions first."
        }
        error={error}
        busy={busy}
        actions={
          <>
            <button
              type="button"
              className="wf-secondary"
              disabled={busy}
              onClick={onOpenScenario}
            >
              Adjust the scenario
            </button>
            <button
              type="button"
              className="wf-primary"
              disabled={busy}
              onClick={() =>
                void (isBaseline
                  ? planning.bootstrap()
                  : planning.generateForVersion(version, false))
              }
            >
              {busy ? "Planning…" : "Generate the plan"}
            </button>
          </>
        }
      />
    );
  }

  if (decided && recommendation) {
    return (
      <Dock
        title="Decision recorded"
        hint="It is in the audit trail with your note."
        tone="done"
        error={error}
        actions={
          <>
            <button type="button" className="wf-secondary" onClick={onViewAudit}>
              View audit
            </button>
            <button
              type="button"
              className="wf-secondary"
              onClick={onOpenScenario}
            >
              Adjust the scenario
            </button>
          </>
        }
      />
    );
  }

  if (recommendation) {
    return (
      <Dock
        title={coverageLine(recommendation)}
        hint="Read the plan on the right, then record a decision or change the assumptions and plan again."
        tone="active"
        error={error}
        busy={busy}
        actions={
          <button
            type="button"
            className="wf-secondary"
            disabled={busy}
            onClick={onOpenScenario}
          >
            Adjust the scenario
          </button>
        }
      />
    );
  }

  return (
    <Dock
      title="Waiting"
      hint="No action is available right now."
      error={error}
    />
  );
}

function Dock({
  title,
  hint,
  tone,
  error,
  actions,
  busy,
  label,
}: {
  title: string;
  hint: string;
  tone?: "active" | "done" | "alert";
  error: string | null;
  actions?: React.ReactNode;
  busy?: boolean;
  label?: string;
}) {
  return (
    <div
      className="wf-dock"
      role="region"
      aria-label="Next step"
      aria-busy={busy === true}
    >
      {busy === true && <span className="wf-spinner" aria-hidden="true" />}
      <div className="wf-dock__body" aria-live="polite" aria-atomic="true">
        <p className="wf-dock__title" data-tone={tone}>
          {title}
        </p>
        <p className="wf-dock__hint">{hint}</p>
      </div>
      {label !== undefined && (
        <p className="wf-visually-hidden" role="alert" aria-label={label}>
          {title}
        </p>
      )}
      {error !== null && (
        <p className="wf-error wf-dock__error" role="alert">
          {error}
        </p>
      )}
      {actions}
    </div>
  );
}

function ScenarioPopover({
  planning,
  incident,
  onClose,
  onSubmit,
}: {
  planning: Planning;
  incident: MonitorData["incident"] & {};
  onClose: () => void;
  onSubmit: (request: ScenarioVersionCreateRequest) => void;
}) {
  return (
    <section
      className="wf-panel wf-panel--above-dock"
      role="dialog"
      aria-label="Scenario assumptions"
    >
      <div className="wf-panel__head">
        <h2 className="wf-panel__title">Change the assumptions</h2>
        <button
          type="button"
          className="wf-close"
          aria-label="Close scenario assumptions"
          onClick={onClose}
        >
          ✕
        </button>
      </div>
      <p className="wf-dock__hint" style={{ marginBottom: 12 }}>
        Saving creates a new immutable scenario version. The baseline stays put
        so the two can be compared.
      </p>
      <ScenarioEditor
        roadEdges={planning.roadQuery.data?.items ?? []}
        resources={incident!.simulatedResources}
        version={planning.latestVersion}
        busy={planning.createVersion.isPending}
        disabled={
          planning.commandsDisabled || planning.generateRecommendation.isPending
        }
        onSubmit={onSubmit}
      />
    </section>
  );
}

function IncidentRail({
  incidents,
  activeIncidentId,
  onSelect,
}: {
  incidents: readonly IncidentSummary[];
  activeIncidentId: string | null;
  onSelect: (incidentId: string) => void;
}) {
  return (
    <nav className="wf-rail" aria-label="Incident queue">
      <div className="wf-brand">
        <span className="wf-brand__dot" />
        <span className="wf-brand__name">WildfireOps</span>
        <span className="wf-brand__chip">OPS</span>
      </div>
      <p className="wf-label">ACTIVE INCIDENTS</p>
      <ol className="wf-steps">
        {incidents.map((incident) => (
          <li key={incident.id}>
            <button
              type="button"
              className="wf-incident"
              aria-pressed={incident.id === activeIncidentId}
              data-state={incident.id === activeIncidentId ? "current" : undefined}
              onClick={() => onSelect(incident.id)}
            >
              <span className="wf-incident__head">
                <span className="wf-incident__name">{incident.name}</span>
                <span className="wf-incident__score">
                  {incident.risk.score.toFixed(1)}
                </span>
              </span>
              <span className="wf-incident__meta">
                {incident.exposedAssetCount} exposed · {incident.freshness}
              </span>
            </button>
          </li>
        ))}
        {incidents.length === 0 && (
          <li className="wf-step__note">No active incidents are available.</li>
        )}
      </ol>
      <div className="wf-rail__foot">
        <span className="wf-dot-good" />
        <span>
          Simulation only · <a href="/">Decision exercise</a>
        </span>
      </div>
    </nav>
  );
}

function Splash({
  message,
  action,
  tone,
  label,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
  tone?: "alert";
  label?: string;
}) {
  return (
    <div className="wf">
      <div className="wf-centre">
        <div
          className="wf-sheet"
          role={tone === "alert" ? "alert" : "status"}
          aria-label={label}
        >
          <p className="wf-prose">{message}</p>
          {action && (
            <div className="wf-actions">
              <button
                type="button"
                className="wf-primary"
                onClick={action.onClick}
              >
                {action.label}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function phaseLabel(
  data: MonitorData,
  planning: Planning,
  decided: boolean,
): string {
  if (data.replaying) return "REPLAY";
  if (planning.sessionStale) return "STALE";
  if (decided) return "DECIDED";
  if (planning.lastSuccessful) return "PLAN READY";
  if (planning.baselineVersion) return "BASELINE SAVED";
  return "OBSERVING";
}

function phaseTone(
  data: MonitorData,
  planning: Planning,
  decided: boolean,
): "active" | "done" | undefined {
  if (decided) return "done";
  if (data.replaying || planning.sessionStale) return undefined;
  return planning.baselineVersion ? "active" : undefined;
}
