import type { FeatureCollection, Geometry } from "geojson";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef } from "react";

import {
  BASEMAP_STYLE_URL,
  INLINE_MAP_STYLE,
  MAP_IMAGES,
  MAP_LAYERS,
  MAP_SOURCE_IDS,
} from "./layers";

export type OperationsFeatureCollection = FeatureCollection<
  Geometry,
  Record<string, unknown>
>;

export type OperationsMapProps = {
  incidentData: OperationsFeatureCollection;
  detectionsData: OperationsFeatureCollection;
  exposedAssetsData: OperationsFeatureCollection;
  simulatedResourcesData: OperationsFeatureCollection;
  routesData: OperationsFeatureCollection;
  roadClosuresData: OperationsFeatureCollection;
  unavailableResourcesData: OperationsFeatureCollection;
  view: "current" | "replay";
};

type DynamicMapData = Pick<
  OperationsMapProps,
  | "incidentData"
  | "detectionsData"
  | "exposedAssetsData"
  | "simulatedResourcesData"
  | "routesData"
  | "roadClosuresData"
  | "unavailableResourcesData"
>;

export function OperationsMap({
  incidentData,
  detectionsData,
  exposedAssetsData,
  simulatedResourcesData,
  routesData,
  roadClosuresData,
  unavailableResourcesData,
  view,
}: OperationsMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const latestDataRef = useRef<DynamicMapData>({
    incidentData,
    detectionsData,
    exposedAssetsData,
    simulatedResourcesData,
    routesData,
    roadClosuresData,
    unavailableResourcesData,
  });

  latestDataRef.current = {
    incidentData,
    detectionsData,
    exposedAssetsData,
    simulatedResourcesData,
    routesData,
    roadClosuresData,
    unavailableResourcesData,
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const map = new maplibregl.Map({
      container,
      style: BASEMAP_STYLE_URL,
      center: [-121.58, 39.79],
      zoom: 8,
      attributionControl: {},
    });
    mapRef.current = map;
    let fallbackAttempted = false;

    const initializeLayers = (): void => {
      if (loadedRef.current) {
        return;
      }

      const data = latestDataRef.current;
      map.addSource(MAP_SOURCE_IDS.incident, {
        type: "geojson",
        data: data.incidentData,
      });
      map.addSource(MAP_SOURCE_IDS.detections, {
        type: "geojson",
        data: data.detectionsData,
      });
      map.addSource(MAP_SOURCE_IDS.exposedAssets, {
        type: "geojson",
        data: data.exposedAssetsData,
      });
      map.addSource(MAP_SOURCE_IDS.simulatedResources, {
        type: "geojson",
        data: data.simulatedResourcesData,
      });
      map.addSource(MAP_SOURCE_IDS.routes, {
        type: "geojson",
        data: data.routesData,
      });
      map.addSource(MAP_SOURCE_IDS.roadClosures, {
        type: "geojson",
        data: data.roadClosuresData,
      });
      map.addSource(MAP_SOURCE_IDS.unavailableResources, {
        type: "geojson",
        data: data.unavailableResourcesData,
      });

      for (const { id, image } of MAP_IMAGES) {
        map.addImage(id, image);
      }
      for (const layer of MAP_LAYERS) {
        map.addLayer(layer);
      }
      loadedRef.current = true;
    };

    const handleStyleError = (): void => {
      if (loadedRef.current || fallbackAttempted) {
        return;
      }
      fallbackAttempted = true;
      map.setStyle(INLINE_MAP_STYLE);
    };

    map.on("style.load", initializeLayers);
    map.on("error", handleStyleError);

    return () => {
      map.off("style.load", initializeLayers);
      map.off("error", handleStyleError);
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) {
      return;
    }

    setSourceData(map, MAP_SOURCE_IDS.incident, incidentData);
    setSourceData(map, MAP_SOURCE_IDS.detections, detectionsData);
    setSourceData(map, MAP_SOURCE_IDS.exposedAssets, exposedAssetsData);
    setSourceData(
      map,
      MAP_SOURCE_IDS.simulatedResources,
      simulatedResourcesData,
    );
  }, [
    incidentData,
    detectionsData,
    exposedAssetsData,
    simulatedResourcesData,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) {
      return;
    }

    setSourceData(map, MAP_SOURCE_IDS.routes, routesData);
  }, [routesData]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && loadedRef.current) setSourceData(map, MAP_SOURCE_IDS.roadClosures, roadClosuresData);
  }, [roadClosuresData]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && loadedRef.current) setSourceData(map, MAP_SOURCE_IDS.unavailableResources, unavailableResourcesData);
  }, [unavailableResourcesData]);

  const observedSummary = [
    countLabel(incidentData.features.length, "incident feature"),
    countLabel(detectionsData.features.length, "detection"),
  ].join(", ");
  const currentContextSummary = [
    countLabel(exposedAssetsData.features.length, "exposed asset"),
    countLabel(simulatedResourcesData.features.length, "simulated resource"),
  ].join(", ");
  const summary =
    view === "replay"
      ? `Replay frame: ${observedSummary}. Current snapshot: ${currentContextSummary}`
      : `Current snapshot: ${observedSummary}, ${currentContextSummary}`;

  return (
    <div className="operations-map">
      <div
        ref={containerRef}
        className="operations-map__canvas"
        role="region"
        aria-label="Wildfire operations map"
      />
      <p className="operations-map__summary">{summary}</p>
      <ul className="operations-map__legend" aria-label="Map legend">
        <LegendItem marker="▰" label="Incident geometry" modifier="incident" />
        <LegendItem marker="●" label="Detections" modifier="detection" />
        <LegendItem marker="◆" label="Exposed assets" modifier="asset" />
        <LegendItem
          marker="■"
          label="Simulated resources"
          modifier="resource"
        />
        <LegendItem marker="━" label={`Routes — ${countLabel(routesData.features.length, "segment")}`} modifier="route" />
        <LegendItem
          marker="┄"
          label={`Road closures — ${countLabel(roadClosuresData.features.length, "segment")}`}
          modifier="closure"
        />
        <LegendItem marker="⊠" label={`Unavailable resources — ${countLabel(unavailableResourcesData.features.length, "resource")}`} modifier="unavailable" />
      </ul>
    </div>
  );
}

function setSourceData(
  map: maplibregl.Map,
  sourceId: string,
  data: OperationsFeatureCollection,
): void {
  const source = map.getSource(sourceId) as GeoJSONSource | undefined;
  source?.setData(data);
}

function countLabel(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

function LegendItem({
  marker,
  label,
  modifier,
}: {
  marker: string;
  label: string;
  modifier: string;
}) {
  return (
    <li className="operations-map__legend-item">
      <span
        className={`operations-map__legend-marker operations-map__legend-marker--${modifier}`}
        aria-hidden="true"
      >
        {marker}
      </span>{" "}
      {label}
    </li>
  );
}
