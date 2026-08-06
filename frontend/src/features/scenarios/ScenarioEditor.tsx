import {
  scenarioDraftKey,
  useScenarioDraft,
  type ScenarioEditorProps,
} from "./useScenarioDraft";

export type { ScenarioEditorProps };

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
      key={scenarioDraftKey(version, resources)}
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
  const {
    directionErrorId, existingWeatherOverrides, fieldsDisabled,
    multipleWeather, resourceDrafts, roads, setResourceAvailable,
    setWeatherMode, setWindDirection, setWindSpeed, speedErrorId, submit,
    submitDisabled, toggleRoad, weather, weatherMode, windDirection, windSpeed,
  } = useScenarioDraft({
    roadEdges,
    resources,
    version,
    busy,
    disabled,
    errorMessage,
    onSubmit,
  });

  return (
    <form aria-label="Scenario version editor" onSubmit={submit}>
      <fieldset disabled={fieldsDisabled}>
        <legend>Road closures</legend>
        {roads.map(({ edgeId, label, closed }) => (
          <label key={edgeId}>
            <input
              type="checkbox"
              checked={closed}
              onChange={(event) =>
                toggleRoad(edgeId, event.currentTarget.checked)
              }
            />
            {label === edgeId ? edgeId : `${label} (${edgeId})`}
          </label>
        ))}
        {roads.length === 0 ? (
          <p>No road edges are available.</p>
        ) : null}
      </fieldset>

      <fieldset disabled={fieldsDisabled}>
        <legend>Weather override</legend>
        {multipleWeather ? (
          <>
            <p>Existing weather overrides</p>
            <ul aria-label="Existing weather overrides">
              {existingWeatherOverrides.map((override, index) => (
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

      <fieldset disabled={fieldsDisabled}>
        <legend>Resource availability</legend>
        {resourceDrafts.map(({ resourceId, resourceType, available }) => (
          <label key={resourceId}>
            <input
              type="checkbox"
              checked={available}
              onChange={(event) =>
                setResourceAvailable(resourceId, event.currentTarget.checked)
              }
            />
            {resourceId} ({resourceType})
          </label>
        ))}
        {resourceDrafts.length === 0 ? <p>No resources are available.</p> : null}
      </fieldset>

      {errorMessage ? <p role="alert">{errorMessage}</p> : null}
      <button type="submit" disabled={submitDisabled}>
        {busy ? "Saving scenario version" : "Save scenario version"}
      </button>
    </form>
  );
}
