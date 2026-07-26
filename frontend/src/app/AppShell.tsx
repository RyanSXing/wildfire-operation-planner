import { lazy, Suspense } from "react";

import type { SourceStatus } from "../api/types";
import { FreshnessBadge } from "../features/incidents/FreshnessBadge";
import { IncidentDetails } from "../features/incidents/IncidentDetails";
import { IncidentQueue } from "../features/incidents/IncidentQueue";
import { ReplayTimeline } from "../features/incidents/ReplayTimeline";
import type {
  PlanningMapSelection,
  PlanningOverlayResult,
} from "../features/map/planningOverlays";
import { ScenarioPlanningPanel } from "../features/scenarios/ScenarioPlanningPanel";
import { EMPTY_COLLECTION, useMonitorData } from "./useMonitorData";

const OperationsMap = lazy(() =>
  import("../features/map/OperationsMap").then((module) => ({
    default: module.OperationsMap,
  })),
);
export function AppShell() {
  const {
    incidentsQuery, sourcesQuery, incidents, activeIncidentId,
    setSelectedIncidentId, planningFreshnessToken, incidentQuery, incident,
    incidentDetailLoading, incidentDetailFailed, timelineQuery, frames,
    startTime, endTime, replayTime, setReplayTime, playing, setPlaying,
    frameIndex, activeFrame, replaying, mapData, ownedPlanningSelection,
    exactRoads, roadState, planningOverlays, handlePlanningSelection,
    currentPanelKey, setPlanningSelection,
  } = useMonitorData();

  return (
    <main className="operator-console">
      <header className="topbar">
        <div className="topbar__identity">
          <h1>WildfireOps</h1>
          <span className="mode-indicator">Observe + plan</span>
        </div>
        <SourceFreshness
          statuses={sourcesQuery.data?.items}
          loading={sourcesQuery.isPending}
          failed={sourcesQuery.isError}
          onRetry={() => void sourcesQuery.refetch()}
        />
      </header>

      <p className="safety-notice" role="note">
        Portfolio simulation only. Do not use for emergency or life-safety
        decisions.
      </p>

      {incidentsQuery.isPending ? (
        <p className="shell-state" role="status">
          Loading incidents…
        </p>
      ) : incidentsQuery.isError ? (
        <LocalFailure
          label="Incident queue unavailable"
          message="Incident data could not be loaded."
          actionLabel="Retry incidents"
          onRetry={() => void incidentsQuery.refetch()}
        />
      ) : (
        <div className="workspace">
          <IncidentQueue
            incidents={incidents}
            selectedIncidentId={activeIncidentId}
            onSelect={(incidentId) => {
              if (incidentId !== activeIncidentId) setPlanningSelection(null);
              setSelectedIncidentId(incidentId);
              setPlaying(false);
              setReplayTime(null);
            }}
          />

          {activeIncidentId ? (
            <>
              <section className="map-workspace" aria-label="Observation workspace">
                <Suspense
                  fallback={
                    <p className="map-loading" role="status">
                      Loading map…
                    </p>
                  }
                >
                  <OperationsMap
                    incidentData={mapData.incident}
                    detectionsData={mapData.detections}
                    exposedAssetsData={mapData.exposedAssets}
                    simulatedResourcesData={mapData.simulatedResources}
                    routesData={replaying ? EMPTY_COLLECTION : planningOverlays.routes}
                    roadClosuresData={replaying ? EMPTY_COLLECTION : planningOverlays.closures}
                    unavailableResourcesData={replaying ? EMPTY_COLLECTION : planningOverlays.unavailableResources}
                    view={replaying ? "replay" : "current"}
                  />
                </Suspense>
                <PlanningMapStatus
                  selection={ownedPlanningSelection}
                  overlays={planningOverlays}
                  roadState={roadState}
                  activeSnapshotId={incident?.snapshotId ?? ""}
                  onRetry={() => void exactRoads.query.refetch()}
                  replaying={replaying}
                />

                {timelineQuery.isPending ? (
                  <p className="replay-timeline replay-timeline__loading" role="status">
                    Loading replay…
                  </p>
                ) : timelineQuery.isError ? (
                  <LocalFailure
                    label="Replay timeline unavailable"
                    message="Replay data could not be loaded."
                    actionLabel="Retry replay"
                    onRetry={() => void timelineQuery.refetch()}
                  />
                ) : (
                  <ReplayTimeline
                    startTime={startTime}
                    currentTime={replayTime ?? endTime}
                    endTime={endTime}
                    playing={playing}
                    onSeek={(timestamp) => {
                      setReplayTime(timestamp);
                      setPlaying(false);
                    }}
                    onPlayChange={(nextPlaying) => {
                      if (
                        nextPlaying &&
                        frameIndex >= frames.length - 1 &&
                        frames.length > 0
                      ) {
                        setReplayTime(frames[0].referenceAt);
                      }
                      setPlaying(nextPlaying);
                    }}
                  />
                )}
              </section>

              {incidentDetailLoading ? (
                <p className="decision-workspace shell-state" role="status">
                  Loading incident details…
                </p>
              ) : incidentDetailFailed || !incident ? (
                <LocalFailure
                  className="decision-workspace"
                  label="Incident details unavailable"
                  message="Incident details could not be loaded."
                  actionLabel="Retry incident details"
                  onRetry={() => void incidentQuery.refetch()}
                />
              ) : (
                <IncidentDetails
                  incident={incident}
                  visualizedRisk={
                    replaying && activeFrame
                      ? activeFrame.risk
                      : incident.risk
                  }
                  riskContext={replaying ? "Replay frame" : "Current snapshot"}
                >
                  <ScenarioPlanningPanel
                    key={currentPanelKey}
                    incident={incident}
                    planningDisabled={replaying}
                    freshnessToken={planningFreshnessToken}
                    onPlanningMapSelection={handlePlanningSelection}
                  />
                </IncidentDetails>
              )}
            </>
          ) : null}
        </div>
      )}
    </main>
  );
}

function PlanningMapStatus({
  selection,
  overlays,
  roadState,
  activeSnapshotId,
  onRetry,
  replaying,
}: {
  selection: PlanningMapSelection | null;
  overlays: PlanningOverlayResult;
  roadState: "idle" | "loading" | "error" | "success";
  activeSnapshotId: string;
  onRetry: () => void;
  replaying: boolean;
}) {
  return (
    <section className="planning-map-status" aria-label="Scenario map status">
      {selection ? <>
        <p>Scenario version {selection.scenarioVersion.version}; scenario snapshot {selection.scenarioVersion.incidentSnapshotId}; active snapshot {activeSnapshotId}; {selection.freshness === "stale" ? "Stale" : "Current"}.</p>
        <OverlayMetadata label="Routes" metadata={overlays.metadata.routes} />
        <OverlayMetadata label="Road closures" metadata={overlays.metadata.closures} />
        <p>Unavailable resources: {listOrNone(overlays.metadata.unavailableResources.mapped)}. Missing resource geometry: {listOrNone(overlays.metadata.unavailableResources.missing)}.</p>
        {overlays.weather.overrides.map((weather) => <p key={weather.index}>Weather override {weather.index}: {weather.windSpeedMps} m/s, {weather.windDirectionDegrees}°.</p>)}
        {overlays.weather.overrides.length > 0 ? <p>{overlays.weather.explanation}</p> : null}
      </> : <p>Observed baseline selected; no scenario overlays.</p>}
      {roadState === "loading" ? <p role="status">Loading road geometry…</p> : null}
      {roadState === "error" ? <div role="alert"><p>Road geometry could not be loaded.</p><button type="button" onClick={onRetry}>Retry road geometry</button></div> : null}
      {replaying && selection ? <p>Current scenario overlays are hidden during replay and will restore on return to the current snapshot.</p> : null}
    </section>
  );
}

function OverlayMetadata({ label, metadata }: { label: string; metadata: PlanningOverlayResult["metadata"]["routes"] }) {
  return <p>{label}: mapped {listOrNone(metadata.mapped)}; null geometry {listOrNone(metadata.nullGeometry)}; missing {listOrNone(metadata.missing)}; omitted {listOrNone(metadata.omitted)}; unresolved {listOrNone(metadata.unresolved)}.</p>;
}

function listOrNone(ids: readonly string[]): string {
  return ids.length > 0 ? `${ids.length} (${ids.join(", ")})` : "0 (none)";
}

function SourceFreshness({
  statuses,
  loading,
  failed,
  onRetry,
}: {
  statuses: readonly SourceStatus[] | undefined;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  if (failed) {
    return (
      <LocalFailure
        className="source-summary source-summary--error"
        label="Source freshness unavailable"
        message="Source freshness could not be loaded."
        actionLabel="Retry sources"
        onRetry={onRetry}
      />
    );
  }

  if (loading || !statuses) {
    return (
      <p className="source-summary" role="status">
        Sources loading…
      </p>
    );
  }

  if (statuses.length === 0) {
    return (
      <section
        className="source-summary"
        aria-label="Source freshness"
        role="status"
      >
        <strong>Sources unavailable</strong>
        <span>No source status is available.</span>
      </section>
    );
  }

  const aggregate = statuses.some((source) => source.freshness === "unavailable")
    ? "unavailable"
    : statuses.some((source) => source.freshness === "stale")
      ? "stale"
      : "fresh";

  return (
    <section className="source-summary" aria-label="Source freshness">
      <strong>Sources {aggregate}</strong>
      <ul>
        {statuses.map((source) => (
          <li key={source.sourceName}>
            <span>{source.sourceName}</span>
            <FreshnessBadge freshness={source.freshness} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function LocalFailure({
  className,
  label,
  message,
  actionLabel,
  onRetry,
}: {
  className?: string;
  label: string;
  message: string;
  actionLabel: string;
  onRetry: () => void;
}) {
  return (
    <section
      className={["local-failure", className].filter(Boolean).join(" ")}
      role="alert"
      aria-label={label}
    >
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        {actionLabel}
      </button>
    </section>
  );
}
