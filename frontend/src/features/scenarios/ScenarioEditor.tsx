import { useId, useState } from "react";

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

export function ScenarioEditor({
  roadEdges,
  resources,
  version,
  busy,
  disabled = false,
  errorMessage,
  onSubmit,
}: ScenarioEditorProps) {
  return (
    <ScenarioEditorForm
      key={`${version?.id ?? "baseline"}:${resourceBaselineKey(resources)}`}
      roadEdges={roadEdges}
      resources={resources}
      version={version}
      busy={busy}
      disabled={disabled}
      errorMessage={errorMessage}
      onSubmit={onSubmit}
    />
  );
}

function ScenarioEditorForm({
  roadEdges,
  resources,
  version,
  busy,
  disabled = false,
  errorMessage,
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
  const roads = roadOptions(roadEdges, version, selectedRoadIds);

  return (
    <form
      aria-label="Scenario version editor"
      onSubmit={(event) => {
        event.preventDefault();
        if (!submitDisabled && request) {
          onSubmit(request);
        }
      }}
    >
      <fieldset disabled={disabled || busy}>
        <legend>Road closures</legend>
        {roads.map(({ edgeId, label }) => (
          <label key={edgeId}>
            <input
              type="checkbox"
              checked={selectedRoadIds.includes(edgeId)}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setSelectedRoadIds((current) =>
                  checked
                    ? [...new Set([...current, edgeId])].sort()
                    : current.filter((item) => item !== edgeId),
                );
              }}
            />
            {label === edgeId ? edgeId : `${label} (${edgeId})`}
          </label>
        ))}
        {roads.length === 0 ? (
          <p>No road edges are available.</p>
        ) : null}
      </fieldset>

      <fieldset disabled={disabled || busy}>
        <legend>Weather override</legend>
        {multipleWeather ? (
          <>
            <p>Existing weather overrides</p>
            <ul aria-label="Existing weather overrides">
              {version?.weatherOverrides.map((override, index) => (
                <li
                  key={`${override.windSpeedMps}:${override.windDirectionDegrees}:${index}`}
                >
                  {override.windSpeedMps} m/s at {override.windDirectionDegrees}°
                </li>
              ))}
            </ul>
            {weatherMode === "preserve" ? (
              <button
                type="button"
                onClick={() => setWeatherMode("replace")}
              >
                Replace or clear weather overrides
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setWeatherMode("preserve")}
              >
                Keep existing weather overrides
              </button>
            )}
          </>
        ) : null}
        {weatherMode === "replace" ? (
          <>
            <label>
              Wind speed (m/s)
              <input
                type="number"
                min="0"
                step="any"
                value={windSpeed}
                aria-invalid={Boolean(weather.speedError)}
                aria-describedby={weather.speedError ? speedErrorId : undefined}
                onChange={(event) => setWindSpeed(event.currentTarget.value)}
              />
            </label>
            {weather.speedError ? (
              <p id={speedErrorId}>{weather.speedError}</p>
            ) : null}
            <label>
              Wind direction (degrees)
              <input
                type="number"
                min="0"
                max="359.999999"
                step="any"
                value={windDirection}
                aria-invalid={Boolean(weather.directionError)}
                aria-describedby={
                  weather.directionError ? directionErrorId : undefined
                }
                onChange={(event) => setWindDirection(event.currentTarget.value)}
              />
            </label>
            {weather.directionError ? (
              <p id={directionErrorId}>{weather.directionError}</p>
            ) : null}
          </>
        ) : null}
      </fieldset>

      <fieldset disabled={disabled || busy}>
        <legend>Resource availability</legend>
        {[...resources]
          .sort((left, right) =>
            compareCodeUnits(left.resourceId, right.resourceId),
          )
          .map((resource) => (
            <label key={resource.resourceId}>
              <input
                type="checkbox"
                checked={
                  availability.get(resource.resourceId) ?? resource.available
                }
                onChange={(event) => {
                  const available = event.currentTarget.checked;
                  setAvailability((current) => {
                    const next = new Map(current);
                    next.set(resource.resourceId, available);
                    return next;
                  });
                }}
              />
              {resource.resourceId} ({resource.resourceType})
            </label>
          ))}
        {resources.length === 0 ? <p>No resources are available.</p> : null}
      </fieldset>

      {errorMessage ? <p role="alert">{errorMessage}</p> : null}
      <button type="submit" disabled={submitDisabled}>
        {busy ? "Saving scenario version" : "Save scenario version"}
      </button>
    </form>
  );
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
