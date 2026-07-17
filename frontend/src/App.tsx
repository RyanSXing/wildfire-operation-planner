import "maplibre-gl/dist/maplibre-gl.css";

import "./App.css";
import { AppProviders } from "./app/AppProviders";
import { AppShell } from "./app/AppShell";
import { ErrorBoundary } from "./app/ErrorBoundary";

export default function App() {
  return (
    <ErrorBoundary>
      <AppProviders>
        <AppShell />
      </AppProviders>
    </ErrorBoundary>
  );
}
