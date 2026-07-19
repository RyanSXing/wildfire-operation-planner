import type { Feature, FeatureCollection, Geometry } from "geojson";
import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  mapLibreMock,
  mapLibreTestState,
  resetMapLibreTestState,
  type RecordedMap,
} from "../../test/maplibre";
import {
  BASEMAP_STYLE_URL,
  EMPTY_FEATURE_COLLECTION,
  INLINE_MAP_STYLE,
  MAP_IMAGE_IDS,
  MAP_LAYER_IDS,
  MAP_SOURCE_IDS,
} from "./layers";
import { OperationsMap } from "./OperationsMap";

vi.mock("maplibre-gl", () => ({ default: mapLibreMock }));

function collection(
  features: Array<Feature<Geometry, Record<string, unknown>>>,
): FeatureCollection<Geometry, Record<string, unknown>> {
  return { type: "FeatureCollection", features };
}

function pointFeature(
  id: string,
  coordinates: [number, number],
): Feature<Geometry, Record<string, unknown>> {
  return {
    type: "Feature",
    id,
    properties: { id },
    geometry: { type: "Point", coordinates },
  };
}

const currentIncident = collection([
  {
    type: "Feature",
    id: "incident-current",
    properties: { name: "Redwood Creek" },
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [-121.66, 39.75],
          [-121.54, 39.77],
          [-121.57, 39.87],
          [-121.66, 39.75],
        ],
      ],
    },
  },
]);

const replayIncident = collection([
  pointFeature("incident-replay", [-121.62, 39.8]),
]);
const currentDetections = collection([
  pointFeature("detection-1", [-121.61, 39.81]),
  pointFeature("detection-2", [-121.59, 39.79]),
]);
const replayDetections = collection([
  pointFeature("detection-replay", [-121.62, 39.8]),
]);
const exposedAssets = collection([
  pointFeature("asset-1", [-121.65, 39.86]),
]);
const simulatedResources = collection([
  pointFeature("resource-1", [-121.7, 39.7]),
]);

const currentProps = {
  incidentData: currentIncident,
  detectionsData: currentDetections,
  exposedAssetsData: exposedAssets,
  simulatedResourcesData: simulatedResources,
  routesData: EMPTY_FEATURE_COLLECTION,
  roadClosuresData: EMPTY_FEATURE_COLLECTION,
  unavailableResourcesData: EMPTY_FEATURE_COLLECTION,
  view: "current" as const,
};

function onlyMap(): RecordedMap {
  expect(mapLibreTestState.instances).toHaveLength(1);
  return mapLibreTestState.instances[0];
}

beforeEach(() => {
  resetMapLibreTestState();
});

describe("OperationsMap", () => {
  it("loads the external basemap and adds stable sources and overlays once", () => {
    render(<OperationsMap {...currentProps} />);

    const region = screen.getByRole("region", {
      name: "Wildfire operations map",
    });
    const map = onlyMap();
    expect(map.options.container).toBe(region);
    expect(map.options.style).toBe(BASEMAP_STYLE_URL);
    expect(map.options.attributionControl).toEqual({});

    act(() => {
      map.emit("style.load");
      map.emit("style.load");
    });

    expect(map.sourceAdds.map(({ id }) => id)).toEqual(
      Object.values(MAP_SOURCE_IDS),
    );
    expect(map.layerAdds.map(({ id }) => id)).toEqual(
      Object.values(MAP_LAYER_IDS),
    );
    expect(map.sources.get(MAP_SOURCE_IDS.routes)?.data).toEqual(
      EMPTY_FEATURE_COLLECTION,
    );
    expect(map.sources.get(MAP_SOURCE_IDS.roadClosures)?.data).toEqual(
      EMPTY_FEATURE_COLLECTION,
    );
    expect([...map.layerVisibility.values()]).toEqual(
      Object.values(MAP_LAYER_IDS).map(() => "visible"),
    );

    expect(map.imageAdds.map(({ id }) => id)).toEqual(
      Object.values(MAP_IMAGE_IDS),
    );
    expect(map.layers.get(MAP_LAYER_IDS.detections)).toMatchObject({
      type: "circle",
    });
    expect(map.layers.get(MAP_LAYER_IDS.exposedAssets)).toMatchObject({
      type: "symbol",
      layout: { "icon-image": MAP_IMAGE_IDS.exposedAsset },
    });
    expect(map.layers.get(MAP_LAYER_IDS.simulatedResources)).toMatchObject({
      type: "symbol",
      layout: { "icon-image": MAP_IMAGE_IDS.simulatedResource },
    });
  });

  it("falls back to the inline style once when the external style fails", () => {
    render(<OperationsMap {...currentProps} />);
    const map = onlyMap();

    act(() => {
      map.emit("error");
      map.emit("error");
    });

    expect(map.setStyleCalls).toEqual([INLINE_MAP_STYLE]);
    expect(map.sourceAdds).toHaveLength(0);

    act(() => {
      map.emit("style.load");
      map.emit("error");
      map.emit("style.load");
    });

    expect(map.setStyleCalls).toEqual([INLINE_MAP_STYLE]);
    expect(map.sourceAdds.map(({ id }) => id)).toEqual(
      Object.values(MAP_SOURCE_IDS),
    );
    expect(map.layerAdds.map(({ id }) => id)).toEqual(
      Object.values(MAP_LAYER_IDS),
    );
  });

  it("keeps critical counts and a textual legend outside the canvas region", () => {
    render(<OperationsMap {...currentProps} />);

    const region = screen.getByRole("region", {
      name: "Wildfire operations map",
    });
    const summary = screen.getByText(
      /current snapshot: 1 incident feature, 2 detections, 1 exposed asset, 1 simulated resource/i,
    );
    const legend = screen.getByRole("list", { name: "Map legend" });

    expect(region).not.toContainElement(summary);
    expect(region).not.toContainElement(legend);
    expect(within(legend).getByText("Incident geometry")).toBeVisible();
    expect(within(legend).getByText("Detections")).toBeVisible();
    expect(within(legend).getByText("Exposed assets")).toBeVisible();
    expect(within(legend).getByText("Simulated resources")).toBeVisible();
    expect(within(legend).getByText("Routes — 0 segments")).toBeVisible();
    expect(within(legend).getByText("Road closures — 0 segments")).toBeVisible();
  });

  it("updates existing dynamic sources on replay without reconstructing or duplicating setup", () => {
    const { rerender } = render(<OperationsMap {...currentProps} />);
    const map = onlyMap();
    act(() => {
      map.emit("style.load");
    });

    rerender(
      <OperationsMap
        {...currentProps}
        incidentData={replayIncident}
        detectionsData={replayDetections}
        view="replay"
      />,
    );

    expect(mapLibreTestState.instances).toHaveLength(1);
    expect(map.sourceAdds).toHaveLength(Object.values(MAP_SOURCE_IDS).length);
    expect(map.layerAdds).toHaveLength(Object.values(MAP_LAYER_IDS).length);
    expect(map.sources.get(MAP_SOURCE_IDS.incident)?.setDataCalls).toEqual([
      replayIncident,
    ]);
    expect(map.sources.get(MAP_SOURCE_IDS.detections)?.setDataCalls).toEqual([
      replayDetections,
    ]);
    expect(
      map.sources.get(MAP_SOURCE_IDS.exposedAssets)?.setDataCalls,
    ).toEqual([exposedAssets]);
    expect(
      map.sources.get(MAP_SOURCE_IDS.simulatedResources)?.setDataCalls,
    ).toEqual([simulatedResources]);
    expect(map.sources.get(MAP_SOURCE_IDS.routes)?.setDataCalls).toHaveLength(0);
    expect(
      map.sources.get(MAP_SOURCE_IDS.roadClosures)?.setDataCalls,
    ).toHaveLength(0);
    expect(
      screen.getByText(
        /replay frame: 1 incident feature, 1 detection\. current snapshot: 1 exposed asset, 1 simulated resource/i,
      ),
    ).toBeVisible();
  });

  it("loads and independently updates planning overlays without rebuilding observed sources", () => {
    const routes = collection([pointFeature("route-1", [-121.6, 39.8])]);
    const closures = collection([pointFeature("closure-1", [-121.61, 39.81])]);
    const unavailable = collection([pointFeature("unavailable-1", [-121.7, 39.7])]);
    const { rerender } = render(<OperationsMap {...currentProps} routesData={routes} roadClosuresData={closures} unavailableResourcesData={unavailable} />);
    const map = onlyMap();
    act(() => map.emit("style.load"));

    expect(map.sources.get(MAP_SOURCE_IDS.routes)?.data).toEqual(routes);
    expect(map.sources.get(MAP_SOURCE_IDS.roadClosures)?.data).toEqual(closures);
    expect(map.sources.get(MAP_SOURCE_IDS.unavailableResources)?.data).toEqual(unavailable);
    expect(map.layers.get(MAP_LAYER_IDS.unavailableResources)).toMatchObject({ type: "symbol" });

    rerender(<OperationsMap {...currentProps} routesData={EMPTY_FEATURE_COLLECTION} roadClosuresData={closures} unavailableResourcesData={unavailable} />);
    expect(mapLibreTestState.instances).toHaveLength(1);
    expect(map.sources.get(MAP_SOURCE_IDS.routes)?.setDataCalls).toEqual([EMPTY_FEATURE_COLLECTION]);
    expect(map.sources.get(MAP_SOURCE_IDS.roadClosures)?.setDataCalls).toEqual([]);
    expect(map.sources.get(MAP_SOURCE_IDS.unavailableResources)?.setDataCalls).toEqual([]);
  });

  it("removes the map exactly once on unmount", () => {
    const { unmount } = render(<OperationsMap {...currentProps} />);
    const map = onlyMap();

    unmount();

    expect(map.removed).toBe(true);
    expect(map.removeCalls).toBe(1);
    expect(map.listeners.get("style.load")).toHaveLength(0);
    expect(map.listeners.get("error")).toHaveLength(0);
  });
});
