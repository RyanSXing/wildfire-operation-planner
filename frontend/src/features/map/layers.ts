import type { FeatureCollection } from "geojson";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

export const MAP_SOURCE_IDS = {
  incident: "wildfireops-incident",
  detections: "wildfireops-detections",
  exposedAssets: "wildfireops-exposed-assets",
  simulatedResources: "wildfireops-simulated-resources",
  routes: "wildfireops-routes",
  roadClosures: "wildfireops-road-closures",
} as const;

export const MAP_LAYER_IDS = {
  incidentFill: "wildfireops-incident-fill",
  incidentOutline: "wildfireops-incident-outline",
  incidentPoint: "wildfireops-incident-point",
  detections: "wildfireops-detections",
  exposedAssets: "wildfireops-exposed-assets",
  simulatedResources: "wildfireops-simulated-resources",
  routes: "wildfireops-routes",
  roadClosures: "wildfireops-road-closures",
} as const;

export const MAP_IMAGE_IDS = {
  exposedAsset: "wildfireops-exposed-asset-diamond",
  simulatedResource: "wildfireops-simulated-resource-square",
} as const;

type MapImage = {
  id: string;
  image: { width: number; height: number; data: Uint8Array };
};

export const MAP_IMAGES: readonly MapImage[] = [
  {
    id: MAP_IMAGE_IDS.exposedAsset,
    image: createMarkerImage("diamond", [250, 204, 21], [113, 63, 18]),
  },
  {
    id: MAP_IMAGE_IDS.simulatedResource,
    image: createMarkerImage("square", [37, 99, 235], [23, 37, 84]),
  },
];

export const EMPTY_FEATURE_COLLECTION: FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

export const INLINE_MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "wildfireops-background",
      type: "background",
      paint: { "background-color": "#e2e8f0" },
    },
  ],
};

export const MAP_LAYERS: LayerSpecification[] = [
  {
    id: MAP_LAYER_IDS.incidentFill,
    type: "fill",
    source: MAP_SOURCE_IDS.incident,
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: {
      "fill-color": "#dc2626",
      "fill-opacity": 0.2,
    },
  },
  {
    id: MAP_LAYER_IDS.incidentOutline,
    type: "line",
    source: MAP_SOURCE_IDS.incident,
    paint: {
      "line-color": "#b91c1c",
      "line-width": 3,
    },
  },
  {
    id: MAP_LAYER_IDS.incidentPoint,
    type: "circle",
    source: MAP_SOURCE_IDS.incident,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-color": "#dc2626",
      "circle-radius": 9,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  },
  {
    id: MAP_LAYER_IDS.detections,
    type: "circle",
    source: MAP_SOURCE_IDS.detections,
    paint: {
      "circle-color": "#f97316",
      "circle-radius": 6,
      "circle-stroke-color": "#7c2d12",
      "circle-stroke-width": 1.5,
    },
  },
  {
    id: MAP_LAYER_IDS.exposedAssets,
    type: "symbol",
    source: MAP_SOURCE_IDS.exposedAssets,
    layout: {
      "icon-image": MAP_IMAGE_IDS.exposedAsset,
      "icon-allow-overlap": true,
    },
  },
  {
    id: MAP_LAYER_IDS.simulatedResources,
    type: "symbol",
    source: MAP_SOURCE_IDS.simulatedResources,
    layout: {
      "icon-image": MAP_IMAGE_IDS.simulatedResource,
      "icon-allow-overlap": true,
    },
  },
  {
    id: MAP_LAYER_IDS.routes,
    type: "line",
    source: MAP_SOURCE_IDS.routes,
    paint: {
      "line-color": "#15803d",
      "line-width": 4,
    },
  },
  {
    id: MAP_LAYER_IDS.roadClosures,
    type: "line",
    source: MAP_SOURCE_IDS.roadClosures,
    paint: {
      "line-color": "#111827",
      "line-dasharray": [1.5, 1.5],
      "line-width": 4,
    },
  },
];

function createMarkerImage(
  shape: "diamond" | "square",
  fill: readonly [number, number, number],
  stroke: readonly [number, number, number],
): { width: number; height: number; data: Uint8Array } {
  const size = 15;
  const center = Math.floor(size / 2);
  const data = new Uint8Array(size * size * 4);

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const distance = Math.abs(x - center) + Math.abs(y - center);
      const inside =
        shape === "diamond"
          ? distance <= center - 1
          : x >= 2 && x < size - 2 && y >= 2 && y < size - 2;
      if (!inside) {
        continue;
      }

      const border =
        shape === "diamond"
          ? distance === center - 1
          : x === 2 || x === size - 3 || y === 2 || y === size - 3;
      const color = border ? stroke : fill;
      const offset = (y * size + x) * 4;
      data[offset] = color[0];
      data[offset + 1] = color[1];
      data[offset + 2] = color[2];
      data[offset + 3] = 255;
    }
  }

  return { width: size, height: size, data };
}
