import type {
  Feature,
  FeatureCollection,
  Geometry as GeoJsonGeometry,
} from "geojson";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  useIncident,
  useIncidentEvents,
  useIncidentTimeline,
  useIncidents,
  useExactRoadEdges,
  useSourceStatus,
} from "../api/hooks";
import type {
  Detection,
  ExposedAsset,
  Geometry,
  IncidentDetail,
  SimulatedResource,
  SourceStatus,
  TimelineFrame,
} from "../api/types";
import { FreshnessBadge } from "../features/incidents/FreshnessBadge";
import { IncidentDetails } from "../features/incidents/IncidentDetails";
import { IncidentQueue } from "../features/incidents/IncidentQueue";
import { ReplayTimeline } from "../features/incidents/ReplayTimeline";
import type { OperationsFeatureCollection } from "../features/map/OperationsMap";
import {
  buildPlanningOverlays,
  type PlanningMapSelection,
  type PlanningOverlayResult,
} from "../features/map/planningOverlays";
import { ScenarioPlanningPanel } from "../features/scenarios/ScenarioPlanningPanel";

const OperationsMap = lazy(() =>
  import("../features/map/OperationsMap").then((module) => ({
    default: module.OperationsMap,
  })),
);

const EMPTY_COLLECTION: OperationsFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
const EMPTY_FRAMES: readonly TimelineFrame[] = [];
type MapProperties = Record<string, unknown>;

export function AppShell() {
  const eventRevisions = useIncidentEvents();

  const incidentsQuery = useIncidents();
  const sourcesQuery = useSourceStatus();
  const incidents = incidentsQuery.data?.items ?? [];
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(
    null,
  );
  const activeIncidentId =
    incidents.find((incident) => incident.id === selectedIncidentId)?.id ??
    incidents[0]?.id ??
    null;
  const planningFreshnessToken = `${eventRevisions.globalRevision}:${
    activeIncidentId
      ? (eventRevisions.incidentRevisions[activeIncidentId] ?? 0)
      : 0
  }`;

  useEffect(() => {
    if (selectedIncidentId !== activeIncidentId) {
      setSelectedIncidentId(activeIncidentId);
    }
  }, [activeIncidentId, selectedIncidentId]);

  const incidentQuery = useIncident(activeIncidentId ?? "");
  const timelineQuery = useIncidentTimeline(activeIncidentId ?? "");
  const frames = timelineQuery.data?.items ?? EMPTY_FRAMES;
  const startTime = frames[0]?.referenceAt ?? null;
  const endTime = frames.at(-1)?.referenceAt ?? null;
  const [replayTime, setReplayTime] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [planningSelection, setPlanningSelection] = useState<PlanningMapSelection | null>(null);
  const currentPanelKey = incidentQuery.data?.id ?? "";
  const currentPanelKeyRef = useRef(currentPanelKey);
  currentPanelKeyRef.current = currentPanelKey;

  useEffect(() => {
    setReplayTime(endTime);
    setPlaying(false);
  }, [activeIncidentId, endTime]);

  const frameIndex = nearestFrameIndex(frames, replayTime);
  const activeFrame = frameIndex >= 0 ? frames[frameIndex] : undefined;
  const replaying = activeFrame !== undefined && frameIndex < frames.length - 1;

  useEffect(() => {
    if (!playing || frameIndex < 0 || frameIndex >= frames.length - 1) {
      if (playing && frameIndex >= frames.length - 1) {
        setPlaying(false);
      }
      return;
    }

    const timer = window.setTimeout(() => {
      setReplayTime(frames[frameIndex + 1].referenceAt);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [frameIndex, frames, playing]);

  const mapData = useMemo(
    () => shapeMapData(incidentQuery.data, replaying ? activeFrame : undefined),
    [activeFrame, incidentQuery.data, replaying],
  );
  const ownedPlanningSelection =
    planningSelection?.incidentId === activeIncidentId &&
    planningSelection.incidentId === incidentQuery.data?.id
      ? planningSelection
      : null;
  const requestedPlanningEdgeIds = useMemo(
    () => {
      if (!ownedPlanningSelection) return [];
      const { scenarioVersion, recommendation } = ownedPlanningSelection;
      const matchingRecommendation =
        recommendation?.scenarioVersionId === scenarioVersion.id &&
        recommendation.graphVersion === scenarioVersion.graphVersion
          ? recommendation
          : null;
      return [
        ...scenarioVersion.roadClosures.map(({ edgeId }) => edgeId),
        ...(matchingRecommendation?.assignments.flatMap((assignment) => assignment.route.edgeIds) ?? []),
      ];
    },
    [ownedPlanningSelection],
  );
  const exactRoads = useExactRoadEdges(
    ownedPlanningSelection?.scenarioVersion.graphVersion ?? "",
    requestedPlanningEdgeIds,
  );
  const roadState = exactRoads.queriedEdgeIds.length === 0
    ? "idle"
    : exactRoads.query.isSuccess
    ? "success"
    : exactRoads.query.isError
      ? "error"
      : exactRoads.query.isPending
        ? "loading"
        : "idle";
  const planningOverlays = useMemo(
    () =>
      buildPlanningOverlays({
        incident: incidentQuery.data,
        selection: ownedPlanningSelection,
        roads: exactRoads.query.data,
        requestedEdgeIds: exactRoads.requestedEdgeIds,
        queriedEdgeIds: exactRoads.queriedEdgeIds,
        omittedEdgeIds: exactRoads.omittedEdgeIds,
        roadState,
      }),
    [exactRoads.omittedEdgeIds, exactRoads.queriedEdgeIds, exactRoads.query.data, exactRoads.requestedEdgeIds, incidentQuery.data, ownedPlanningSelection, roadState],
  );
  const handlePlanningSelection = useCallback(
    (selection: PlanningMapSelection | null, ownerIncidentId: string) => {
      if (ownerIncidentId === currentPanelKeyRef.current) {
        setPlanningSelection(selection);
      }
    },
    [],
  );

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
                  activeSnapshotId={incidentQuery.data?.snapshotId ?? ""}
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

              {incidentQuery.isPending ? (
                <p className="decision-workspace shell-state" role="status">
                  Loading incident details…
                </p>
              ) : incidentQuery.isError || !incidentQuery.data ? (
                <LocalFailure
                  className="decision-workspace"
                  label="Incident details unavailable"
                  message="Incident details could not be loaded."
                  actionLabel="Retry incident details"
                  onRetry={() => void incidentQuery.refetch()}
                />
              ) : (
                <IncidentDetails
                  incident={incidentQuery.data}
                  visualizedRisk={
                    replaying && activeFrame
                      ? activeFrame.risk
                      : incidentQuery.data.risk
                  }
                  riskContext={replaying ? "Replay frame" : "Current snapshot"}
                >
                  <ScenarioPlanningPanel
                    key={currentPanelKey}
                    incident={incidentQuery.data}
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
    <section aria-label="Scenario map status">
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

function shapeMapData(
  incident: IncidentDetail | undefined,
  replayFrame: TimelineFrame | undefined,
): {
  incident: OperationsFeatureCollection;
  detections: OperationsFeatureCollection;
  exposedAssets: OperationsFeatureCollection;
  simulatedResources: OperationsFeatureCollection;
} {
  if (!incident) {
    return {
      incident: EMPTY_COLLECTION,
      detections: EMPTY_COLLECTION,
      exposedAssets: EMPTY_COLLECTION,
      simulatedResources: EMPTY_COLLECTION,
    };
  }

  const observedGeometry = replayFrame?.geometry ?? incident.geometry;
  const detections = replayFrame?.detections ?? incident.detections;
  return {
    incident: collection([
      feature(observedGeometry, { incidentId: incident.id, name: incident.name }),
    ]),
    detections: collection(
      detections.map((detection) => detectionFeature(detection, incident.id)),
    ),
    exposedAssets: collection(
      incident.exposedAssets.map((asset) => assetFeature(asset, incident.id)),
    ),
    simulatedResources: collection(
      incident.simulatedResources.map((resource) =>
        resourceFeature(resource, incident.id),
      ),
    ),
  };
}

function detectionFeature(
  detection: Detection,
  incidentId: string,
): Feature<GeoJsonGeometry, MapProperties> {
  return feature(detection.geometry, {
    incidentId,
    sourceName: detection.sourceName,
    sourceRecordId: detection.sourceRecordId,
  });
}

function assetFeature(
  asset: ExposedAsset,
  incidentId: string,
): Feature<GeoJsonGeometry, MapProperties> {
  return feature(asset.geometry, {
    incidentId,
    assetId: asset.assetId,
    assetKind: asset.assetKind,
    name: asset.name,
  });
}

function resourceFeature(
  resource: SimulatedResource,
  incidentId: string,
): Feature<GeoJsonGeometry, MapProperties> {
  return feature(resource.geometry, {
    incidentId,
    resourceId: resource.resourceId,
    resourceType: resource.resourceType,
    simulated: true,
  });
}

function feature(
  geometry: Geometry,
  properties: MapProperties,
): Feature<GeoJsonGeometry, MapProperties> {
  return {
    type: "Feature",
    properties,
    geometry: geometry as unknown as GeoJsonGeometry,
  };
}

function collection(
  features: Array<Feature<GeoJsonGeometry, MapProperties>>,
): FeatureCollection<GeoJsonGeometry, MapProperties> {
  return { type: "FeatureCollection", features };
}

function nearestFrameIndex(
  frames: readonly TimelineFrame[],
  timestamp: string | null,
): number {
  if (frames.length === 0) {
    return -1;
  }
  if (!timestamp) {
    return frames.length - 1;
  }

  const target = Date.parse(timestamp);
  if (!Number.isFinite(target)) {
    return frames.length - 1;
  }

  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  frames.forEach((frame, index) => {
    const distance = Math.abs(Date.parse(frame.referenceAt) - target);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  return nearestIndex;
}
