import type {
  Feature,
  FeatureCollection,
  Geometry as GeoJsonGeometry,
} from "geojson";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  TimelineFrame,
} from "../api/types";
import type { OperationsFeatureCollection } from "../features/map/OperationsMap";
import {
  buildPlanningOverlays,
  isRenderablePlanningSelection,
  planningRouteEdges,
  type PlanningMapSelection,
} from "../features/map/planningOverlays";

export const EMPTY_COLLECTION: OperationsFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};
const EMPTY_FRAMES: readonly TimelineFrame[] = [];
type MapProperties = Record<string, unknown>;

/**
 * Everything the live monitor knows, with no presentation attached.
 *
 * Incident selection and its fallback, the replay clock, map-data shaping and
 * planning-overlay derivation are not view concerns, and they are guarded by
 * AppShell.test.tsx. They move verbatim so the presentation can be replaced
 * without putting any of it at risk.
 */
export function useMonitorData() {
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
  const incident =
    incidentQuery.data?.id === activeIncidentId ? incidentQuery.data : undefined;
  const incidentDetailMismatched =
    incidentQuery.data !== undefined && incident === undefined;
  const incidentDetailLoading =
    incidentQuery.isPending ||
    (incidentDetailMismatched && incidentQuery.isFetching);
  const incidentDetailFailed =
    incidentQuery.isError ||
    (incidentDetailMismatched && !incidentQuery.isFetching) ||
    (!incident && !incidentDetailLoading);
  const timelineQuery = useIncidentTimeline(activeIncidentId ?? "");
  const frames = timelineQuery.data?.items ?? EMPTY_FRAMES;
  const startTime = frames[0]?.referenceAt ?? null;
  const endTime = frames.at(-1)?.referenceAt ?? null;
  const [replayTime, setReplayTime] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [planningSelection, setPlanningSelection] = useState<PlanningMapSelection | null>(null);
  const currentPanelKey = activeIncidentId ?? "";
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
    () => shapeMapData(incident, replaying ? activeFrame : undefined),
    [activeFrame, incident, replaying],
  );
  const ownedPlanningSelection =
    activeIncidentId === incident?.id &&
    isRenderablePlanningSelection(incident, planningSelection)
    ? planningSelection
    : null;
  const requestedPlanningEdgeIds = useMemo(
    () => {
      if (!ownedPlanningSelection) return [];
      const { scenarioVersion } = ownedPlanningSelection;
      return [
        ...scenarioVersion.roadClosures.map(({ edgeId }) => edgeId),
        ...planningRouteEdges(ownedPlanningSelection).requested,
      ];
    },
    [ownedPlanningSelection],
  );
  const exactRoads = useExactRoadEdges(
    ownedPlanningSelection?.scenarioVersion.graphVersion ?? "",
    requestedPlanningEdgeIds,
  );
  const roadState: "idle" | "success" | "error" | "loading" =
    exactRoads.queriedEdgeIds.length === 0
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
        incident,
        selection: ownedPlanningSelection,
        roads: exactRoads.query.data,
        requestedEdgeIds: exactRoads.requestedEdgeIds,
        queriedEdgeIds: exactRoads.queriedEdgeIds,
        omittedEdgeIds: exactRoads.omittedEdgeIds,
        roadState,
      }),
    [exactRoads.omittedEdgeIds, exactRoads.queriedEdgeIds, exactRoads.query.data, exactRoads.requestedEdgeIds, incident, ownedPlanningSelection, roadState],
  );
  const handlePlanningSelection = useCallback(
    (selection: PlanningMapSelection | null, ownerIncidentId: string) => {
      if (ownerIncidentId === currentPanelKeyRef.current) {
        setPlanningSelection(selection);
      }
    },
    [],
  );

  return {
    eventRevisions,
    incidentsQuery,
    sourcesQuery,
    incidents,
    activeIncidentId,
    setSelectedIncidentId,
    planningFreshnessToken,
    incidentQuery,
    incident,
    incidentDetailLoading,
    incidentDetailFailed,
    timelineQuery,
    frames,
    startTime,
    endTime,
    replayTime,
    setReplayTime,
    playing,
    setPlaying,
    frameIndex,
    activeFrame,
    replaying,
    mapData,
    ownedPlanningSelection,
    exactRoads,
    roadState,
    planningOverlays,
    handlePlanningSelection,
    currentPanelKey,
    setPlanningSelection,
  };
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

