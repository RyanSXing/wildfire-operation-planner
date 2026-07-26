import { useId, useState, type FormEvent } from "react";

import type {
  RoadEdge,
  ScenarioVersion,
  ScenarioVersionCreateRequest,
  SimulatedResource,
  WeatherOverride,
} from "../../api/types";

export type ScenarioEditorProps = {
  roadEdges: readonly RoadEdge[];
  resources: readonly SimulatedResource[];
  version?: ScenarioVersion | null;
  busy: boolean;
  disabled?: boolean;
  errorMessage?: string | null;
  onSubmit: (request: ScenarioVersionCreateRequest) => void;
};

type WeatherValidation = {
  weatherOverrides: WeatherOverride[] | null;
  speedError?: string;
  directionError?: string;
};

type WeatherMode = "preserve" | "replace";

/**
 * The identity of a draft, which decides when the draft is thrown away.
 *
 * The editor is seeded from props once and then owned by the operator, so the
 * only things allowed to discard their edits are a different scenario version
 * and a change in observed resource availability — the latter because the
 * request only carries resources whose availability *differs* from what was
 * observed, so a baseline draft computed against stale availability would emit
 * the wrong overrides. Re-sent but equal props must not reset anything, which
 * is why this is a value key and not an identity check.
 */
export function scenarioDraftKey(
  version: ScenarioVersion | null | undefined,
  resources: readonly SimulatedResource[],
): string {
  return `${version?.id ?? "baseline"}:${resourceBaselineKey(resources)}`;
}

/**
 * The scenario version draft, with no presentation attached.
 *
 * Everything here is about what may be submitted rather than how it looks:
 * weather preserve/replace with its validation, the exact-replacement request
 * and its deterministic ordering, and the "semantically unchanged" comparison
 * that keeps the form from saving a version identical to the one it was seeded
 * from. Extracted verbatim from ScenarioEditor so the presentation could be
 * replaced without putting any of that at risk — the behaviour is pinned by
 * ScenarioEditor.test.tsx, which was not changed.
 */
export function useScenarioDraft({
  roadEdges,
  resources,
  version,
  busy,
  disabled = false,
  onSubmit,
}: ScenarioEditorProps) {
  const speedErrorId = useId();
  const directionErrorId = useId();
  const [selectedRoadIds, setSelectedRoadIds] = useState(() =>
    normalizedRoadIds(version),
  );
  const multipleWeather = (version?.weatherOverrides.length ?? 0) > 1;
  const [weatherMode, setWeatherMode] = useState<WeatherMode>(() =>
    multipleWeather ? "preserve" : "replace",
  );
  const initialWeather = multipleWeather
    ? undefined
    : version?.weatherOverrides[0];
  const [windSpeed, setWindSpeed] = useState(() =>
    initialWeather ? String(initialWeather.windSpeedMps) : "",
  );
  const [windDirection, setWindDirection] = useState(() =>
    initialWeather ? String(initialWeather.windDirectionDegrees) : "",
  );
  const [availability, setAvailability] = useState(() =>
    initialAvailability(resources, version),
  );
  const weather: WeatherValidation =
    weatherMode === "preserve"
      ? { weatherOverrides: [...(version?.weatherOverrides ?? [])] }
      : validateWeather(windSpeed, windDirection);
  const request =
    weather.weatherOverrides === null
      ? null
      : replacementRequest(
          selectedRoadIds,
          weather.weatherOverrides,
          resources,
          availability,
        );
  const initialRequest = initialReplacement(resources, version);
  const unchanged =
    request !== null && JSON.stringify(request) === JSON.stringify(initialRequest);
  const submitDisabled = disabled || busy || request === null || unchanged;
  const roads = roadOptions(roadEdges, version, selectedRoadIds).map(
    (option) => ({
      ...option,
      closed: selectedRoadIds.includes(option.edgeId),
    }),
  );
  const resourceDrafts = [...resources]
    .sort((left, right) => compareCodeUnits(left.resourceId, right.resourceId))
    .map((resource) => ({
      resourceId: resource.resourceId,
      resourceType: resource.resourceType,
      available: availability.get(resource.resourceId) ?? resource.available,
    }));

  const toggleRoad = (edgeId: string, closed: boolean): void => {
    setSelectedRoadIds((current) =>
      closed
        ? [...new Set([...current, edgeId])].sort()
        : current.filter((item) => item !== edgeId),
    );
  };

  const setResourceAvailable = (
    resourceId: string,
    available: boolean,
  ): void => {
    setAvailability((current) => {
      const next = new Map(current);
      next.set(resourceId, available);
      return next;
    });
  };

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!submitDisabled && request) {
      onSubmit(request);
    }
  };

  return {
    directionErrorId,
    existingWeatherOverrides: version?.weatherOverrides ?? [],
    fieldsDisabled: disabled || busy,
    multipleWeather,
    resourceDrafts,
    roads,
    setResourceAvailable,
    setWeatherMode,
    setWindDirection,
    setWindSpeed,
    speedErrorId,
    submit,
    submitDisabled,
    toggleRoad,
    weather,
    weatherMode,
    windDirection,
    windSpeed,
  };
}

function resourceBaselineKey(resources: readonly SimulatedResource[]): string {
  return JSON.stringify(
    [...resources]
      .sort((left, right) => compareCodeUnits(left.resourceId, right.resourceId))
      .map(({ resourceId, available }) => [resourceId, available]),
  );
}

function normalizedRoadIds(version?: ScenarioVersion | null): string[] {
  return [...new Set(version?.roadClosures.map(({ edgeId }) => edgeId) ?? [])].sort();
}

function roadOptions(
  roadEdges: readonly RoadEdge[],
  version?: ScenarioVersion | null,
  selectedRoadIds: readonly string[] = [],
): Array<{ edgeId: string; label: string }> {
  const options = new Map(
    roadEdges.map(({ edgeId, label }) => [edgeId, label] as const),
  );
  for (const { edgeId } of version?.roadClosures ?? []) {
    if (!options.has(edgeId)) {
      options.set(edgeId, edgeId);
    }
  }
  for (const edgeId of selectedRoadIds) {
    if (!options.has(edgeId)) {
      options.set(edgeId, edgeId);
    }
  }
  return [...options]
    .map(([edgeId, label]) => ({ edgeId, label }))
    .sort((left, right) => compareCodeUnits(left.edgeId, right.edgeId));
}

function initialAvailability(
  resources: readonly SimulatedResource[],
  version?: ScenarioVersion | null,
): Map<string, boolean> {
  const availability = new Map(
    resources.map(({ resourceId, available }) => [resourceId, available] as const),
  );
  for (const override of version?.resourceOverrides ?? []) {
    if (availability.has(override.resourceId)) {
      availability.set(override.resourceId, override.available);
    }
  }
  return availability;
}

function initialReplacement(
  resources: readonly SimulatedResource[],
  version?: ScenarioVersion | null,
): ScenarioVersionCreateRequest {
  return replacementRequest(
    normalizedRoadIds(version),
    [...(version?.weatherOverrides ?? [])],
    resources,
    initialAvailability(resources, version),
  );
}

function replacementRequest(
  selectedRoadIds: readonly string[],
  weatherOverrides: WeatherOverride[],
  resources: readonly SimulatedResource[],
  availability: ReadonlyMap<string, boolean>,
): ScenarioVersionCreateRequest {
  return {
    roadClosures: [...new Set(selectedRoadIds)]
      .sort()
      .map((edgeId) => ({ edgeId })),
    weatherOverrides,
    resourceOverrides: [...resources]
      .sort((left, right) => compareCodeUnits(left.resourceId, right.resourceId))
      .filter(
        (resource) =>
          (availability.get(resource.resourceId) ?? resource.available) !==
          resource.available,
      )
      .map((resource) => ({
        resourceId: resource.resourceId,
        available: availability.get(resource.resourceId) ?? resource.available,
      })),
  };
}

function validateWeather(speedText: string, directionText: string): WeatherValidation {
  const speedBlank = speedText.trim() === "";
  const directionBlank = directionText.trim() === "";
  if (speedBlank && directionBlank) {
    return { weatherOverrides: [] };
  }

  const speed = Number(speedText);
  const direction = Number(directionText);
  const speedError = speedBlank
    ? "Enter wind speed with wind direction."
    : !Number.isFinite(speed) || speed < 0
      ? "Wind speed must be a finite nonnegative number."
      : undefined;
  const directionError = directionBlank
    ? "Enter wind direction with wind speed."
    : !Number.isFinite(direction) || direction < 0 || direction >= 360
      ? "Wind direction must be at least 0 and less than 360."
      : undefined;

  return speedError || directionError
    ? { weatherOverrides: null, speedError, directionError }
    : {
        weatherOverrides: [
          { windSpeedMps: speed, windDirectionDegrees: direction },
        ],
      };
}

function compareCodeUnits(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
