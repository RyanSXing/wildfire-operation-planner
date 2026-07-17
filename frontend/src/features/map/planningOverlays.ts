import type { Feature, FeatureCollection, Geometry as GeoJsonGeometry } from "geojson";

import type {
  IncidentDetail,
  Recommendation,
  RoadEdgeList,
  ScenarioVersion,
} from "../../api/types";

type OverlayProperties = Record<string, unknown>;
export type PlanningMapSelection = Readonly<{
  incidentId: string;
  scenarioVersion: ScenarioVersion;
  recommendation: Recommendation | null;
  freshness: "current" | "stale";
}>;

type EdgeMetadata = Readonly<{
  requested: readonly string[];
  mapped: readonly string[];
  nullGeometry: readonly string[];
  missing: readonly string[];
  omitted: readonly string[];
  unresolved: readonly string[];
}>;

export type PlanningOverlayResult = Readonly<{
  routes: FeatureCollection<GeoJsonGeometry, OverlayProperties>;
  closures: FeatureCollection<GeoJsonGeometry, OverlayProperties>;
  unavailableResources: FeatureCollection<GeoJsonGeometry, OverlayProperties>;
  metadata: Readonly<{
    routes: EdgeMetadata;
    closures: EdgeMetadata;
    unavailableResources: Readonly<{
      all: readonly string[];
      mapped: readonly string[];
      missing: readonly string[];
    }>;
  }>;
  weather: Readonly<{
    overrides: readonly Readonly<{
      index: number;
      windSpeedMps: number;
      windDirectionDegrees: number;
      scenarioVersionId: string;
    }>[];
    explanation: string;
  }>;
}>;

type BuildPlanningOverlaysInput = Readonly<{
  incident: IncidentDetail | undefined;
  selection: PlanningMapSelection | null;
  roads: RoadEdgeList | undefined;
  requestedEdgeIds: readonly string[];
  queriedEdgeIds: readonly string[];
  omittedEdgeIds: readonly string[];
  roadState: "idle" | "loading" | "error" | "success";
}>;

const empty = (): FeatureCollection<GeoJsonGeometry, OverlayProperties> => ({
  type: "FeatureCollection",
  features: [],
});

const sorted = (ids: readonly string[]): string[] =>
  [...new Set(ids.filter((id) => id.trim().length > 0))].sort();

export function buildPlanningOverlays({
  incident,
  selection,
  roads,
  requestedEdgeIds,
  queriedEdgeIds,
  omittedEdgeIds,
  roadState,
}: BuildPlanningOverlaysInput): PlanningOverlayResult {
  if (!incident || !isRenderablePlanningSelection(incident, selection)) {
    return emptyResult();
  }

  const version = selection.scenarioVersion;
  const recommendation = matchingPlanningRecommendation(selection);
  const routeEdges = planningRouteEdges(selection);
  const routeIds = routeEdges.requested;
  const closureIds = sorted(version.roadClosures.map(({ edgeId }) => edgeId));
  const exact = indexExactRoads(roads, queriedEdgeIds, roadState);
  const requested = new Set(requestedEdgeIds);
  const omitted = new Set(omittedEdgeIds);
  const routes = routeFeatures(recommendation, exact.mapped, incident, version, selection.freshness);
  const closures = closureFeatures(closureIds, exact.mapped, incident, version, selection.freshness);
  const unavailable = unavailableResourceFeatures(incident, version, selection.freshness);

  return {
    routes: collection(routes),
    closures: collection(closures),
    unavailableResources: collection(unavailable.features),
    metadata: {
      routes: edgeMetadata(routeIds, exact, requested, omitted, routeEdges.unresolved),
      closures: edgeMetadata(closureIds, exact, requested, omitted),
      unavailableResources: unavailable.metadata,
    },
    weather: {
      overrides: version.weatherOverrides.map((override, index) => ({
        index: index + 1,
        windSpeedMps: override.windSpeedMps,
        windDirectionDegrees: override.windDirectionDegrees,
        scenarioVersionId: version.id,
      })),
      explanation: "Scenario weather override; no location supplied, so it is not mapped.",
    },
  };
}

export function isRenderablePlanningSelection(
  incident: IncidentDetail | undefined,
  selection: PlanningMapSelection | null,
): selection is PlanningMapSelection {
  return Boolean(
    incident &&
      selection &&
      selection.incidentId === incident.id &&
      selection.scenarioVersion.incidentId === incident.id &&
      (selection.freshness === "stale" ||
        selection.scenarioVersion.incidentSnapshotId === incident.snapshotId),
  );
}

export function matchingPlanningRecommendation(selection: PlanningMapSelection): Recommendation | null {
  const recommendation = selection.recommendation;
  return recommendation &&
    recommendation.scenarioVersionId === selection.scenarioVersion.id &&
    recommendation.graphVersion === selection.scenarioVersion.graphVersion &&
    recommendation.incidentSnapshotId === selection.scenarioVersion.incidentSnapshotId
    ? recommendation
    : null;
}

export function planningRouteEdges(selection: PlanningMapSelection): Readonly<{
  requested: readonly string[];
  unresolved: readonly string[];
}> {
  const recommendation = matchingPlanningRecommendation(selection);
  if (!recommendation) return { requested: [], unresolved: [] };

  const graphVersion = selection.scenarioVersion.graphVersion;
  const unresolved = sorted(
    recommendation.assignments
      .filter((assignment) => assignment.route.graphVersion !== graphVersion)
      .flatMap((assignment) => assignment.route.edgeIds),
  );
  const unresolvedSet = new Set(unresolved);
  return {
    requested: sorted(
      recommendation.assignments
        .filter((assignment) => assignment.route.graphVersion === graphVersion)
        .flatMap((assignment) => assignment.route.edgeIds)
        .filter((edgeId) => !unresolvedSet.has(edgeId)),
    ),
    unresolved,
  };
}

function indexExactRoads(
  roads: RoadEdgeList | undefined,
  queriedIds: readonly string[],
  roadState: BuildPlanningOverlaysInput["roadState"],
) {
  const queried = new Set(queriedIds);
  const exactRoads = roadState === "success" ? roads : undefined;
  const itemsById = new Map<string, RoadEdgeList["items"]>();
  for (const edge of exactRoads?.items ?? []) {
    if (queried.has(edge.edgeId)) {
      itemsById.set(edge.edgeId, [...(itemsById.get(edge.edgeId) ?? []), edge]);
    }
  }
  const missingIds = new Set((exactRoads?.missingEdgeIds ?? []).filter((id) => queried.has(id)));
  const mapped = new Map<string, RoadEdgeList["items"][number]>();
  const nullGeometry = new Set<string>();
  const missing = new Set<string>();
  const unresolved = new Set<string>();
  for (const id of queried) {
    const items = itemsById.get(id) ?? [];
    if (roadState !== "success" || items.length > 1 || (items.length > 0 && missingIds.has(id))) {
      unresolved.add(id);
    } else if (items.length === 1 && items[0].geometry) {
      mapped.set(id, items[0]);
    } else if (items.length === 1) {
      nullGeometry.add(id);
    } else if (missingIds.has(id)) {
      missing.add(id);
    } else {
      unresolved.add(id);
    }
  }
  return { mapped, nullGeometry, missing, unresolved };
}

function edgeMetadata(
  ids: readonly string[],
  exact: ReturnType<typeof indexExactRoads>,
  requested: ReadonlySet<string>,
  omitted: ReadonlySet<string>,
  extraUnresolved: readonly string[] = [],
): EdgeMetadata {
  const requestedForKind = sorted(ids.filter((id) => requested.has(id)));
  const pick = (matches: (id: string) => boolean) => requestedForKind.filter(matches);
  const omittedIds = pick((id) => omitted.has(id));
  const mapped = pick((id) => !omitted.has(id) && exact.mapped.has(id));
  const nullGeometry = pick((id) => !omitted.has(id) && exact.nullGeometry.has(id));
  const missing = pick((id) => !omitted.has(id) && exact.missing.has(id));
  const unresolved = sorted([
    ...pick((id) => !omitted.has(id) && exact.unresolved.has(id)),
    ...extraUnresolved,
  ]);
  return { requested: requestedForKind, mapped, nullGeometry, missing, omitted: omittedIds, unresolved };
}

function routeFeatures(
  recommendation: Recommendation | null,
  roads: ReadonlyMap<string, RoadEdgeList["items"][number]>,
  incident: IncidentDetail,
  version: ScenarioVersion,
  freshness: PlanningMapSelection["freshness"],
): Feature<GeoJsonGeometry, OverlayProperties>[] {
  if (!recommendation) return [];
  const { requested } = planningRouteEdges({
    incidentId: incident.id,
    scenarioVersion: version,
    recommendation,
    freshness,
  });
  return recommendation.assignments
    .filter((assignment) => assignment.route.graphVersion === version.graphVersion)
    .flatMap((assignment) =>
    assignment.route.edgeIds.filter((edgeId) => requested.includes(edgeId)).flatMap((edgeId) => {
      const road = roads.get(edgeId);
      return road?.geometry ? [feature(road.geometry, {
        sourceKind: "recommendation-route", recommendationId: recommendation.id,
        resourceId: assignment.resourceId, destinationId: assignment.destinationId,
        edgeId, graphVersion: version.graphVersion, scenarioVersionId: version.id,
        incidentId: incident.id, scenarioSnapshotId: version.incidentSnapshotId,
        recommendationSnapshotId: recommendation.incidentSnapshotId,
        activeIncidentSnapshotId: incident.snapshotId, freshness,
      })] : [];
    }),
  );
}

function closureFeatures(
  closureIds: readonly string[],
  roads: ReadonlyMap<string, RoadEdgeList["items"][number]>,
  incident: IncidentDetail,
  version: ScenarioVersion,
  freshness: PlanningMapSelection["freshness"],
): Feature<GeoJsonGeometry, OverlayProperties>[] {
  return closureIds.flatMap((edgeId) => {
    const road = roads.get(edgeId);
    return road?.geometry ? [feature(road.geometry, {
      sourceKind: "scenario-road-closure", edgeId, graphVersion: version.graphVersion,
      scenarioVersionId: version.id,
      incidentId: incident.id, scenarioSnapshotId: version.incidentSnapshotId,
      activeIncidentSnapshotId: incident.snapshotId, freshness,
    })] : [];
  });
}

function unavailableResourceFeatures(
  incident: IncidentDetail,
  version: ScenarioVersion,
  freshness: PlanningMapSelection["freshness"],
) {
  const all = sorted(version.resourceOverrides.filter(({ available }) => !available).map(({ resourceId }) => resourceId));
  const resources = new Map(incident.simulatedResources.map((resource) => [resource.resourceId, resource]));
  const mapped = all.filter((id) => resources.has(id));
  return {
    features: mapped.flatMap((resourceId) => {
      const resource = resources.get(resourceId);
      return resource ? [feature(resource.geometry, {
        sourceKind: "scenario-unavailable-resource", resourceId,
        graphVersion: version.graphVersion, scenarioVersionId: version.id,
        incidentId: incident.id, scenarioSnapshotId: version.incidentSnapshotId,
        activeIncidentSnapshotId: incident.snapshotId, freshness,
      })] : [];
    }),
    metadata: { all, mapped, missing: all.filter((id) => !resources.has(id)) },
  };
}

function feature(
  geometry: IncidentDetail["geometry"],
  properties: OverlayProperties,
): Feature<GeoJsonGeometry, OverlayProperties> {
  return { type: "Feature", properties, geometry: geometry as unknown as GeoJsonGeometry };
}

function collection(
  features: Feature<GeoJsonGeometry, OverlayProperties>[],
): FeatureCollection<GeoJsonGeometry, OverlayProperties> {
  return { type: "FeatureCollection", features };
}

function emptyResult(): PlanningOverlayResult {
  const edges: EdgeMetadata = { requested: [], mapped: [], nullGeometry: [], missing: [], omitted: [], unresolved: [] };
  return {
    routes: empty(), closures: empty(), unavailableResources: empty(),
    metadata: { routes: edges, closures: edges, unavailableResources: { all: [], mapped: [], missing: [] } },
    weather: { overrides: [], explanation: "Scenario weather override; no location supplied, so it is not mapped." },
  };
}
