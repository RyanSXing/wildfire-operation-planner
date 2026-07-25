type Listener = (event?: unknown) => void;

export type RecordedMapOptions = {
  container: string | HTMLElement;
  style?: unknown;
  [key: string]: unknown;
};

export type RecordedSourceSpecification = {
  type: string;
  data?: unknown;
  [key: string]: unknown;
};

export type RecordedLayerSpecification = {
  id: string;
  layout?: { visibility?: string; [key: string]: unknown };
  [key: string]: unknown;
};

export class RecordedGeoJSONSource {
  data: unknown;
  readonly setDataCalls: unknown[] = [];

  constructor(data: unknown) {
    this.data = data;
  }

  setData(data: unknown): this {
    this.data = data;
    this.setDataCalls.push(data);
    return this;
  }
}

export class RecordedMap {
  readonly options: RecordedMapOptions;
  readonly sourceAdds: Array<{
    id: string;
    specification: RecordedSourceSpecification;
  }> = [];
  readonly layerAdds: RecordedLayerSpecification[] = [];
  readonly imageAdds: Array<{ id: string; image: unknown; options?: unknown }> = [];
  readonly sources = new Map<string, RecordedGeoJSONSource>();
  readonly layers = new Map<string, RecordedLayerSpecification>();
  readonly layerVisibility = new Map<string, string>();
  readonly listeners = new Map<string, Set<Listener>>();
  readonly setStyleCalls: unknown[] = [];
  removed = false;
  removeCalls = 0;

  constructor(options: RecordedMapOptions) {
    this.options = options;
    mapLibreTestState.instances.push(this);
  }

  on(type: string, listener: Listener): this {
    const listeners = this.listeners.get(type) ?? new Set<Listener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
    return this;
  }

  off(type: string, listener: Listener): this {
    this.listeners.get(type)?.delete(listener);
    return this;
  }

  emit(type: string): this {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ type, target: this });
    }
    return this;
  }

  addSource(id: string, specification: RecordedSourceSpecification): this {
    this.sourceAdds.push({ id, specification });
    this.sources.set(id, new RecordedGeoJSONSource(specification.data));
    return this;
  }

  addImage(id: string, image: unknown, options?: unknown): this {
    this.imageAdds.push({ id, image, options });
    return this;
  }

  getSource(id: string): RecordedGeoJSONSource | undefined {
    return this.sources.get(id);
  }

  addLayer(specification: RecordedLayerSpecification): this {
    this.layerAdds.push(specification);
    this.layers.set(specification.id, specification);
    this.layerVisibility.set(
      specification.id,
      specification.layout?.visibility ?? "visible",
    );
    return this;
  }

  getLayer(id: string): RecordedLayerSpecification | undefined {
    return this.layers.get(id);
  }

  setLayoutProperty(id: string, property: string, value: unknown): this {
    if (property === "visibility" && typeof value === "string") {
      this.layerVisibility.set(id, value);
    }
    return this;
  }

  setStyle(style: unknown): this {
    this.setStyleCalls.push(style);
    return this;
  }

  addControl(control: unknown, position?: string): this {
    this.controlAdds.push({ control, position });
    return this;
  }

  resize(): this {
    return this;
  }

  fitBounds(bounds: unknown, options?: unknown): this {
    this.fitBoundsCalls.push({ bounds, options });
    return this;
  }

  getCanvas(): { style: Record<string, string> } {
    return this.canvas;
  }

  remove(): this {
    this.removed = true;
    this.removeCalls += 1;
    return this;
  }

  readonly controlAdds: Array<{ control: unknown; position?: string }> = [];
  readonly fitBoundsCalls: Array<{ bounds: unknown; options?: unknown }> = [];
  private readonly canvas = { style: {} as Record<string, string> };
}

export class RecordedMarker {
  lngLat: [number, number] = [0, 0];
  map: RecordedMap | null = null;
  removed = false;

  private readonly options: { element: HTMLElement };

  constructor(options: { element: HTMLElement }) {
    this.options = options;
    mapLibreTestState.markers.push(this);
  }

  setLngLat(lngLat: [number, number]): this {
    this.lngLat = lngLat;
    return this;
  }

  addTo(map: RecordedMap): this {
    this.map = map;
    document.body.append(this.options.element);
    return this;
  }

  getElement(): HTMLElement {
    return this.options.element;
  }

  remove(): this {
    this.removed = true;
    this.options.element.remove();
    return this;
  }
}

export class RecordedLngLatBounds {
  readonly points: Array<[number, number]> = [];

  constructor(first: [number, number], second: [number, number]) {
    this.points.push(first, second);
  }

  extend(point: [number, number]): this {
    this.points.push(point);
    return this;
  }
}

export class RecordedNavigationControl {
  readonly options: unknown;

  constructor(options?: unknown) {
    this.options = options;
  }
}

export const mapLibreTestState = {
  instances: [] as RecordedMap[],
  markers: [] as RecordedMarker[],
};

export function resetMapLibreTestState(): void {
  mapLibreTestState.instances.length = 0;
  mapLibreTestState.markers.length = 0;
}

export const mapLibreMock = {
  Map: RecordedMap,
  Marker: RecordedMarker,
  NavigationControl: RecordedNavigationControl,
  LngLatBounds: RecordedLngLatBounds,
};
