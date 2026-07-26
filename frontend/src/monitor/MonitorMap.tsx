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
  assets: "wf-assets",
  resources: "wf-resources",
  unavailable: "wf-unavailable",
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

export function MonitorMap(props: MonitorMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const pendingRef = useRef(props);
  pendingRef.current = props;

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

      map.addSource(SOURCES.assets, {
        type: "geojson",
        data: data.exposedAssetsData,
      });
      map.addLayer({
        id: "wf-assets",
        type: "circle",
        source: SOURCES.assets,
        paint: {
          "circle-color": "rgba(245,176,46,0.25)",
          "circle-radius": 7,
          "circle-stroke-color": "#f5b02e",
          "circle-stroke-width": 2,
        },
      });

      map.addSource(SOURCES.resources, {
        type: "geojson",
        data: data.simulatedResourcesData,
      });
      map.addLayer({
        id: "wf-resources",
        type: "circle",
        source: SOURCES.resources,
        paint: {
          "circle-color": "#1e232b",
          "circle-radius": 7,
          "circle-stroke-color": "rgba(255,255,255,0.75)",
          "circle-stroke-width": 2,
        },
      });

      // A unit taken out of service is struck through in the fire colour, so it
      // reads as unavailable rather than merely unassigned.
      map.addSource(SOURCES.unavailable, {
        type: "geojson",
        data: data.unavailableResourcesData,
      });
      map.addLayer({
        id: "wf-unavailable",
        type: "circle",
        source: SOURCES.unavailable,
        paint: {
          "circle-color": "rgba(255,106,61,0.2)",
          "circle-radius": 9,
          "circle-stroke-color": "#ff6a3d",
          "circle-stroke-width": 2,
        },
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

    return () => {
      observer?.disconnect();
      map.off("style.load", initializeLayers);
      map.off("error", handleStyleError);
      loadedRef.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, []);

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
    set(SOURCES.assets, props.exposedAssetsData);
    set(SOURCES.resources, props.simulatedResourcesData);
    set(SOURCES.unavailable, props.unavailableResourcesData);
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
