import type { Feature, FeatureCollection, LineString } from "geojson";
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import type {
  ExerciseAsset,
  ExerciseCheckpoint,
  ExerciseResource,
  PlanOutput,
} from "../api/exerciseTypes";
import type { RoadEdge } from "../api/types";

/**
 * A schematic operations plot rather than a basemap view: the exercise runs
 * against a fixed replay package, so the map is drawn only from geometry the
 * API returned (asset positions, staging points, real road-graph route
 * segments). No third-party tiles means the view is identical on every run,
 * which is what the exercise promises.
 */
const PLOT_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "wf-backdrop",
      type: "background",
      paint: { "background-color": "#10161d" },
    },
  ],
};

const SOURCES = {
  routes: "wf-routes",
  closures: "wf-closures",
} as const;

const RESOURCE_LETTERS: Record<string, string> = {
  engine: "E",
  "evacuation-bus": "B",
  "medical-team": "M",
  "road-crew": "R",
};

export type ExerciseMapProps = {
  checkpoint: ExerciseCheckpoint;
  assets: readonly ExerciseAsset[];
  resources: readonly ExerciseResource[];
  plan: PlanOutput | null;
  routeEdges: readonly RoadEdge[];
  closedEdges: readonly RoadEdge[];
  selectedId: string | null;
  onSelect: (selection: { kind: "asset" | "resource"; id: string } | null) => void;
  labelFor: (kind: "asset" | "resource", id: string) => string;
};

export function ExerciseMap({
  checkpoint,
  assets,
  resources,
  plan,
  routeEdges,
  closedEdges,
  selectedId,
  onSelect,
  labelFor,
}: ExerciseMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const markersRef = useRef(new Map<string, maplibregl.Marker>());
  const closureMarkersRef = useRef(new Map<string, maplibregl.Marker>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const uncoveredAssetIds = useMemo(() => {
    if (!plan) {
      return new Set<string>();
    }
    const byTask = new Map(checkpoint.tasks.map((task) => [task.taskId, task.assetId]));
    return new Set(
      plan.uncoveredTaskIds
        .map((taskId) => byTask.get(taskId))
        .filter((assetId): assetId is string => assetId !== undefined),
    );
  }, [plan, checkpoint.tasks]);

  const routesData = useMemo(
    () => toLineCollection(routeEdges),
    [routeEdges],
  );
  const closuresData = useMemo(
    () => toLineCollection(closedEdges),
    [closedEdges],
  );

  // Sources only exist once the style has loaded. Route geometry usually
  // arrives before that, so the latest collections are held here and applied
  // from the load handler as well as from the effect below.
  const pendingRef = useRef({ routes: routesData, closures: closuresData });
  pendingRef.current = { routes: routesData, closures: closuresData };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const map = new maplibregl.Map({
      container,
      style: PLOT_STYLE,
      center: [-121.68, 39.83],
      zoom: 9.4,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.on("error", () => {
      // A style or source error must not take the workflow down with it.
    });
    map.on("click", () => onSelectRef.current(null));
    map.on("load", () => {
      loadedRef.current = true;
      map.addSource(SOURCES.closures, {
        type: "geojson",
        data: pendingRef.current.closures,
      });
      map.addSource(SOURCES.routes, {
        type: "geojson",
        data: pendingRef.current.routes,
      });
      map.addLayer({
        id: "wf-closures-line",
        type: "line",
        source: SOURCES.closures,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ff6a3d", "line-width": 4, "line-opacity": 0.75 },
      });
      map.addLayer({
        id: "wf-routes-glow",
        type: "line",
        source: SOURCES.routes,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#3fd6ef", "line-width": 8, "line-opacity": 0.22 },
      });
      map.addLayer({
        id: "wf-routes-core",
        type: "line",
        source: SOURCES.routes,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#3fd6ef", "line-width": 2.6 },
      });
    });

    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => map.resize());
    observer?.observe(container);

    const markers = markersRef.current;
    const closureMarkers = closureMarkersRef.current;

    return () => {
      observer?.disconnect();
      for (const marker of markers.values()) {
        marker.remove();
      }
      markers.clear();
      for (const marker of closureMarkers.values()) {
        marker.remove();
      }
      closureMarkers.clear();
      loadedRef.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Markers are real buttons so the plot is reachable by keyboard, and every
  // one of them has a plain-language accessible name.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const wanted = new Map<
      string,
      { kind: "asset" | "resource"; lngLat: [number, number] }
    >();
    for (const asset of assets) {
      wanted.set(asset.assetId, {
        kind: "asset",
        lngLat: [asset.position.longitude, asset.position.latitude],
      });
    }
    for (const resource of resources) {
      wanted.set(resource.resourceId, {
        kind: "resource",
        lngLat: [resource.position.longitude, resource.position.latitude],
      });
    }

    for (const [id, marker] of markersRef.current) {
      if (!wanted.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    }

    for (const [id, { kind, lngLat }] of wanted) {
      let marker = markersRef.current.get(id);
      if (!marker) {
        const element = document.createElement("button");
        element.type = "button";
        element.className =
          kind === "asset" ? "wf-marker wf-marker--asset" : "wf-marker";
        if (kind === "resource") {
          const resource = resources.find((item) => item.resourceId === id);
          element.textContent =
            RESOURCE_LETTERS[resource?.resourceType ?? ""] ?? "U";
        } else {
          // The diamond is drawn by an inner element. Rotating the marker
          // itself would compose with the `transform` MapLibre writes on every
          // frame and throw the marker away from its coordinates.
          const diamond = document.createElement("span");
          diamond.className = "wf-marker__diamond";
          element.append(diamond);
        }
        element.addEventListener("click", (event) => {
          event.stopPropagation();
          onSelectRef.current({ kind, id });
        });
        marker = new maplibregl.Marker({ element }).setLngLat(lngLat).addTo(map);
        markersRef.current.set(id, marker);
      } else {
        marker.setLngLat(lngLat);
      }
      const element = marker.getElement();
      element.setAttribute("aria-label", labelFor(kind, id));
      element.dataset.selected = String(selectedId === id);
      if (kind === "asset") {
        element.dataset.uncovered = String(uncoveredAssetIds.has(id));
      }
    }
  }, [assets, resources, selectedId, uncoveredAssetIds, labelFor]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) {
      return;
    }
    setData(map, SOURCES.routes, routesData);
    setData(map, SOURCES.closures, closuresData);
  }, [routesData, closuresData]);

  // Closed corridors get a ✕ at their midpoint so the reason a unit is taking
  // the long way round is visible without reading the plan text.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const wanted = new Map(
      closedEdges
        .map((edge) => [edge.edgeId, midpoint(edge)] as const)
        .filter((entry): entry is [string, [number, number]] => entry[1] !== null),
    );
    for (const [id, marker] of closureMarkersRef.current) {
      if (!wanted.has(id)) {
        marker.remove();
        closureMarkersRef.current.delete(id);
      }
    }
    for (const [id, lngLat] of wanted) {
      if (closureMarkersRef.current.has(id)) {
        continue;
      }
      const element = document.createElement("div");
      element.className = "wf-marker wf-marker--closed";
      element.textContent = "✕";
      const label = closedEdges.find((edge) => edge.edgeId === id)?.label;
      element.title = label ? `${label} — closed` : "Road closed";
      closureMarkersRef.current.set(
        id,
        new maplibregl.Marker({ element }).setLngLat(lngLat).addTo(map),
      );
    }
  }, [closedEdges]);

  // Keep every asset in frame as checkpoints add and remove them.
  useEffect(() => {
    const map = mapRef.current;
    const points = assets.map(
      (asset) => [asset.position.longitude, asset.position.latitude] as [number, number],
    );
    if (!map || points.length === 0) {
      return;
    }
    const bounds = points.reduce(
      (acc, point) => acc.extend(point),
      new maplibregl.LngLatBounds(points[0], points[0]),
    );
    // Extra padding at the bottom keeps the cluster of staged units clear of
    // the command dock and whichever panel is sitting above it.
    map.fitBounds(bounds, {
      padding: { top: 72, right: 48, bottom: 200, left: 48 },
      maxZoom: 10.5,
      duration: 600,
    });
  }, [assets]);

  return <div ref={containerRef} className="wf-map" data-testid="exercise-map" />;
}

function setData(
  map: maplibregl.Map,
  sourceId: string,
  data: FeatureCollection<LineString>,
): void {
  const source = map.getSource(sourceId) as GeoJSONSource | undefined;
  source?.setData(data);
}

function toLineCollection(
  edges: readonly RoadEdge[],
): FeatureCollection<LineString> {
  const features = edges.flatMap((edge): Feature<LineString>[] =>
    edge.geometry === null
      ? []
      : [
          {
            type: "Feature",
            geometry: edge.geometry as LineString,
            properties: { edgeId: edge.edgeId, label: edge.label },
          },
        ],
  );
  return { type: "FeatureCollection", features };
}

function midpoint(edge: RoadEdge): [number, number] | null {
  const coordinates = edge.geometry?.coordinates;
  if (!coordinates || coordinates.length === 0) {
    return null;
  }
  const point = coordinates[Math.floor(coordinates.length / 2)];
  return [point[0], point[1]];
}
