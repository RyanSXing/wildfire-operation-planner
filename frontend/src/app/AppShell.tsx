import type {
  Feature,
  FeatureCollection,
  Geometry as GeoJsonGeometry,
} from "geojson";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import {
  useIncident,
  useIncidentEvents,
  useIncidentTimeline,
  useIncidents,
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
  useIncidentEvents();

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
                    view={replaying ? "replay" : "current"}
                  />
                </Suspense>

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
                    key={incidentQuery.data.id}
                    incident={incidentQuery.data}
                    planningDisabled={replaying}
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
