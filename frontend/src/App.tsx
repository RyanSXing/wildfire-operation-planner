import "maplibre-gl/dist/maplibre-gl.css";

import "./App.css";
import { AppProviders } from "./app/AppProviders";
import { AppShell } from "./app/AppShell";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { ExerciseWorkspace } from "./exercise/ExerciseWorkspace";

/**
 * The Park Fire decision exercise is the primary experience. The original live
 * monitoring dashboard stays reachable at /monitor. A path check is enough for
 * two destinations — a router dependency would not earn its place.
 */
export default function App() {
  const isMonitor =
    typeof window !== "undefined" &&
    window.location.pathname.replace(/\/+$/, "") === "/monitor";

  return (
    <ErrorBoundary>
      <AppProviders>
        {isMonitor ? <AppShell /> : <ExerciseWorkspace />}
      </AppProviders>
    </ErrorBoundary>
  );
}
