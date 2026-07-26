import type { FeatureCollection } from "geojson";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { OperationsFeatureCollection } from "../features/map/OperationsMap";
import { BASEMAP_STYLE_URL, INLINE_MAP_STYLE } from "../features/map/layers";

/**
 * The live plot, drawn the same way the decision exercise draws its own.
 *
 * The exercise established the treatment — the product basemap darkened by a
 * scrim, fire as satellite detections, planned routes in cyan, closures in
 * orange — and the monitor uses it so the two surfaces read as one product
 * rather than two. The data is the monitor's own: everything here comes from
 * collections useMonitorData already shapes.
 */
const SOURCES = {
  scrim: "wf-scrim",
  incident: "wf-incident",
  detections: "wf-detections",
  closures: "wf-closures",
  routes: "wf-routes",
} as const;

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

export type MonitorMapProps = {
  incidentData: OperationsFeatureCollection;
  detectionsData: OperationsFeatureCollection;
  exposedAssetsData: OperationsFeatureCollection;
  simulatedResourcesData: OperationsFeatureCollection;
  routesData: OperationsFeatureCollection;
  roadClosuresData: OperationsFeatureCollection;
  unavailableResourcesData: OperationsFeatureCollection;
  view: "current" | "replay";
};

type MarkerSpec = {
  id: string;
  kind: "asset" | "resource";
  label: string;
  letter: string;
  lngLat: [number, number];
  unavailable?: boolean;
};

const RESOURCE_LETTERS: Record<string, string> = {
  engine: "E",
  crew: "C",
  dozer: "D",
  tender: "T",
  "evacuation-bus": "B",
  "medical-team": "M",
  "road-crew": "R",
};

function markerSpec(
  feature: OperationsFeatureCollection["features"][number],
  kind: "asset" | "resource",
): MarkerSpec | null {
  if (feature.geometry.type !== "Point") {
    return null;
  }
  const properties = (feature.properties ?? {}) as Record<string, unknown>;
  const id = String(
    properties.assetId ?? properties.resourceId ?? properties.id ?? "",
  );
  if (id === "") {
    return null;
  }
  const label = String(properties.name ?? properties.label ?? id);
  const type = String(properties.resourceType ?? "");
  return {
    id,
    kind,
    label,
    letter: RESOURCE_LETTERS[type] ?? type.slice(0, 1).toUpperCase() ?? "U",
    lngLat: feature.geometry.coordinates as [number, number],
  };
}

export function MonitorMap(props: MonitorMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const pendingRef = useRef(props);
  pendingRef.current = props;
  const markersRef = useRef(new Map<string, maplibregl.Marker>());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const map = new maplibregl.Map({
      container,
      style: BASEMAP_STYLE_URL,
      center: [-121.6, 39.9],
      zoom: 8.4,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-right",
    );

    let fallbackAttempted = false;

    const initializeLayers = (): void => {
      if (loadedRef.current) {
        return;
      }
      const data = pendingRef.current;

      map.addSource(SOURCES.scrim, { type: "geojson", data: WORLD });
      map.addLayer({
        id: "wf-scrim",
        type: "fill",
        source: SOURCES.scrim,
        paint: { "fill-color": "#0b1016", "fill-opacity": 0.62 },
      });

      map.addSource(SOURCES.incident, {
        type: "geojson",
        data: data.incidentData,
      });
      map.addLayer({
        id: "wf-incident-fill",
        type: "fill",
        source: SOURCES.incident,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#ff6a3d", "fill-opacity": 0.16 },
      });
      map.addLayer({
        id: "wf-incident-line",
        type: "line",
        source: SOURCES.incident,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "line-color": "#ff6a3d", "line-width": 2.2 },
      });

      map.addSource(SOURCES.detections, {
        type: "geojson",
        data: data.detectionsData,
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
          "circle-opacity": 0.85,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 2, 12, 6],
          "circle-stroke-color": "#ffc7ad",
          "circle-stroke-width": 0.6,
          "circle-stroke-opacity": 0.55,
        },
      });

      map.addSource(SOURCES.closures, {
        type: "geojson",
        data: data.roadClosuresData,
      });
      map.addLayer({
        id: "wf-closures-line",
        type: "line",
        source: SOURCES.closures,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ff6a3d", "line-width": 4, "line-opacity": 0.8 },
      });

      map.addSource(SOURCES.routes, { type: "geojson", data: data.routesData });
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

    // Tiles are a convenience, not a dependency: a style error swaps in the flat
    // plot and every overlay still renders.
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

    return () => {
      observer?.disconnect();
      for (const marker of markers.values()) {
        marker.remove();
      }
      markers.clear();
      map.off("style.load", initializeLayers);
      map.off("error", handleStyleError);
      loadedRef.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Units and places are markers, not layers, so they carry the same shapes and
  // accessible names the exercise gives them.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const wanted = new Map<string, MarkerSpec>();
    for (const feature of props.exposedAssetsData.features) {
      const spec = markerSpec(feature, "asset");
      if (spec) wanted.set(spec.id, spec);
    }
    for (const feature of props.simulatedResourcesData.features) {
      const spec = markerSpec(feature, "resource");
      if (spec) wanted.set(spec.id, spec);
    }
    for (const feature of props.unavailableResourcesData.features) {
      const spec = markerSpec(feature, "resource");
      if (spec) wanted.set(spec.id, { ...spec, unavailable: true });
    }

    for (const [id, marker] of markersRef.current) {
      if (!wanted.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    }
    for (const [id, spec] of wanted) {
      let marker = markersRef.current.get(id);
      if (!marker) {
        const element = document.createElement("div");
        element.className =
          spec.kind === "asset" ? "wf-marker wf-marker--asset" : "wf-marker";
        if (spec.kind === "asset") {
          const diamond = document.createElement("span");
          diamond.className = "wf-marker__diamond";
          element.append(diamond);
        } else {
          element.textContent = spec.letter;
        }
        element.setAttribute("role", "img");
        marker = new maplibregl.Marker({ element })
          .setLngLat(spec.lngLat)
          .addTo(map);
        markersRef.current.set(id, marker);
      } else {
        marker.setLngLat(spec.lngLat);
      }
      const element = marker.getElement();
      element.setAttribute(
        "aria-label",
        spec.unavailable ? `${spec.label} — out of service` : spec.label,
      );
      element.dataset.uncovered = String(spec.unavailable === true);
    }
  }, [
    props.exposedAssetsData,
    props.simulatedResourcesData,
    props.unavailableResourcesData,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) {
      return;
    }
    const set = (id: string, data: OperationsFeatureCollection) => {
      (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
    };
    set(SOURCES.incident, props.incidentData);
    set(SOURCES.detections, props.detectionsData);
    set(SOURCES.closures, props.roadClosuresData);
    set(SOURCES.routes, props.routesData);
  }, [props]);

  return (
    <div
      ref={containerRef}
      className="wf-map"
      data-testid="monitor-map"
      data-view={props.view}
      aria-label="Wildfire operations map"
      role="region"
    />
  );
}
