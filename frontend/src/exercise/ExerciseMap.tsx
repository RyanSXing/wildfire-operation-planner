import type { Feature, FeatureCollection, LineString, Point } from "geojson";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import type {
  ExerciseAsset,
  ExerciseCheckpoint,
  ExerciseResource,
  PlanOutput,
} from "../api/exerciseTypes";
import type { Detection, RoadEdge } from "../api/types";
import { BASEMAP_STYLE_URL, INLINE_MAP_STYLE } from "../features/map/layers";

const SOURCES = {
  scrim: "wf-scrim",
  detections: "wf-detections",
  simulated: "wf-simulated",
  closures: "wf-closures",
  routes: "wf-routes",
} as const;

const RESOURCE_LETTERS: Record<string, string> = {
  engine: "E",
  "evacuation-bus": "B",
  "medical-team": "M",
  "road-crew": "R",
};

/** A world-covering polygon, used to darken whichever basemap resolved. */
const WORLD: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-180, -85],
            [180, -85],
            [180, 85],
            [-180, 85],
            [-180, -85],
          ],
        ],
      },
    },
  ],
};

export type ExerciseMapProps = {
  checkpoint: ExerciseCheckpoint;
  assets: readonly ExerciseAsset[];
  resources: readonly ExerciseResource[];
  plan: PlanOutput | null;
  detections: readonly Detection[];
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
  detections,
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

  const routesData = useMemo(() => toLineCollection(routeEdges), [routeEdges]);
  const closuresData = useMemo(() => toLineCollection(closedEdges), [closedEdges]);
  const detectionsData = useMemo(
    () => toDetectionCollection(detections),
    [detections],
  );
  // Incidents the exercise invents are drawn separately from observed
  // detections, so a simulated fire can never be read as a historical one.
  const simulatedData = useMemo(
    () => toSimulatedCollection(checkpoint),
    [checkpoint],
  );

  // Sources only exist once a style has loaded. Data usually arrives before
  // that, so the latest collections are held here and applied from the
  // style.load handler as well as from the effect below.
  const pendingRef = useRef({
    routes: routesData,
    closures: closuresData,
    detections: detectionsData,
    simulated: simulatedData,
  });
  pendingRef.current = {
    routes: routesData,
    closures: closuresData,
    detections: detectionsData,
    simulated: simulatedData,
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const map = new maplibregl.Map({
      container,
      style: BASEMAP_STYLE_URL,
      center: [-121.68, 39.9],
      zoom: 8.5,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-right",
    );
    map.on("click", () => onSelectRef.current(null));

    let fallbackAttempted = false;

    const initializeLayers = (): void => {
      if (loadedRef.current) {
        return;
      }
      const data = pendingRef.current;

      // Darken whichever basemap resolved, so daylight cartography sits behind
      // the operational overlay instead of competing with it.
      map.addSource(SOURCES.scrim, { type: "geojson", data: WORLD });
      map.addLayer({
        id: "wf-scrim",
        type: "fill",
        source: SOURCES.scrim,
        paint: { "fill-color": "#0b1016", "fill-opacity": 0.62 },
      });

      map.addSource(SOURCES.detections, {
        type: "geojson",
        data: data.detections,
      });
      map.addLayer({
        id: "wf-detections-glow",
        type: "circle",
        source: SOURCES.detections,
        paint: {
          "circle-color": "#ff6a3d",
          "circle-opacity": 0.16,
          "circle-blur": 1,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 9, 12, 28],
        },
      });
      map.addLayer({
        id: "wf-detections-core",
        type: "circle",
        source: SOURCES.detections,
        paint: {
          "circle-color": "#ff6a3d",
          "circle-opacity": [
            "interpolate",
            ["linear"],
            ["get", "confidence"],
            0,
            0.35,
            1,
            0.9,
          ],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 2, 12, 6],
          "circle-stroke-color": "#ffc7ad",
          "circle-stroke-width": 0.6,
          "circle-stroke-opacity": 0.55,
        },
      });

      map.addSource(SOURCES.simulated, { type: "geojson", data: data.simulated });
      map.addLayer({
        id: "wf-simulated-fire",
        type: "circle",
        source: SOURCES.simulated,
        paint: {
          "circle-color": "#f5b02e",
          "circle-opacity": 0.2,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 10, 12, 30],
          "circle-stroke-color": "#f5b02e",
          "circle-stroke-width": 1.5,
        },
      });

      map.addSource(SOURCES.closures, { type: "geojson", data: data.closures });
      map.addLayer({
        id: "wf-closures-line",
        type: "line",
        source: SOURCES.closures,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ff6a3d", "line-width": 4, "line-opacity": 0.75 },
      });

      map.addSource(SOURCES.routes, { type: "geojson", data: data.routes });
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

      loadedRef.current = true;
    };

    // Tiles are a convenience, not a dependency. If the style cannot load, the
    // plot falls back to a flat dark canvas and every overlay still renders.
    const handleStyleError = (): void => {
      if (loadedRef.current || fallbackAttempted) {
        return;
      }
      fallbackAttempted = true;
      map.setStyle(INLINE_MAP_STYLE);
    };

    map.on("style.load", initializeLayers);
    map.on("error", handleStyleError);

    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => map.resize());
    observer?.observe(container);

    const markers = markersRef.current;
    const closureMarkers = closureMarkersRef.current;

    return () => {
      observer?.disconnect();
      map.off("style.load", initializeLayers);
      map.off("error", handleStyleError);
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
      const uncovered = kind === "asset" && uncoveredAssetIds.has(id);
      // The dataset attributes drive CSS; ARIA has to carry the meaning, and
      // "uncovered" belongs in the name because the pulse that shows it is
      // both colour-only and removed under prefers-reduced-motion.
      element.setAttribute(
        "aria-label",
        uncovered
          ? `${labelFor(kind, id)} — uncovered by this plan`
          : labelFor(kind, id),
      );
      element.setAttribute("aria-pressed", String(selectedId === id));
      element.dataset.selected = String(selectedId === id);
      if (kind === "asset") {
        element.dataset.uncovered = String(uncovered);
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
    setData(map, SOURCES.detections, detectionsData);
    setData(map, SOURCES.simulated, simulatedData);
  }, [routesData, closuresData, detectionsData, simulatedData]);

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
      // MapLibre gives an unroled marker element role="button" and tabindex=0,
      // which would put a focusable control that does nothing into the tab
      // order. This marker is a graphic, so it says so before it is added.
      element.setAttribute("role", "img");
      element.setAttribute(
        "aria-label",
        label ? `${label} is closed` : "A road is closed",
      );
      closureMarkersRef.current.set(
        id,
        new maplibregl.Marker({ element }).setLngLat(lngLat).addTo(map),
      );
    }
  }, [closedEdges]);

  // Keep the fire and everything it threatens in frame together.
  useEffect(() => {
    const map = mapRef.current;
    const points: [number, number][] = [
      ...assets.map(
        (asset) =>
          [asset.position.longitude, asset.position.latitude] as [number, number],
      ),
      ...detectionsData.features.map(
        (feature) => feature.geometry.coordinates as [number, number],
      ),
      ...simulatedData.features.map(
        (feature) => feature.geometry.coordinates as [number, number],
      ),
    ];
    if (!map || points.length === 0) {
      return;
    }
    const bounds = points.reduce(
      (acc, point) => acc.extend(point),
      new maplibregl.LngLatBounds(points[0], points[0]),
    );
    // Extra padding at the bottom keeps the staged units clear of the command
    // dock and whichever panel is sitting above it.
    map.fitBounds(bounds, {
      padding: { top: 72, right: 48, bottom: 200, left: 48 },
      maxZoom: 11,
      duration: 600,
    });
  }, [assets, detectionsData, simulatedData]);

  return <div ref={containerRef} className="wf-map" data-testid="exercise-map" />;
}

function setData(
  map: maplibregl.Map,
  sourceId: string,
  data: FeatureCollection,
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

function toDetectionCollection(
  detections: readonly Detection[],
): FeatureCollection<Point> {
  const features = detections.flatMap((detection): Feature<Point>[] =>
    detection.geometry.type === "Point"
      ? [
          {
            type: "Feature",
            geometry: detection.geometry,
            properties: {
              confidence: detection.confidence,
              intensity: detection.intensity,
              observedAt: detection.observedAt,
            },
          },
        ]
      : [],
  );
  return { type: "FeatureCollection", features };
}

function toSimulatedCollection(
  checkpoint: ExerciseCheckpoint,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: checkpoint.incidents.flatMap((incident): Feature<Point>[] => {
      const position = incident.simulatedPosition;
      if (!position) {
        return [];
      }
      return [
        {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [position.longitude, position.latitude],
          },
          properties: { name: incident.name },
        },
      ];
    }),
  };
}

function midpoint(edge: RoadEdge): [number, number] | null {
  const coordinates = edge.geometry?.coordinates;
  if (!coordinates || coordinates.length === 0) {
    return null;
  }
  const point = coordinates[Math.floor(coordinates.length / 2)];
  return [point[0], point[1]];
}
