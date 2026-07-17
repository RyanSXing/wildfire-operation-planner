import type { FeatureCollection, Geometry } from "geojson";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, delay, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAP_SOURCE_IDS } from "../features/map/layers";
import {
  BEAR_ID,
  REDWOOD_ID,
  incidentListResponse,
} from "../test/fixtures";
import {
  mapLibreMock,
  mapLibreTestState,
  resetMapLibreTestState,
  type RecordedMap,
} from "../test/maplibre";
import { server } from "../test/server";
import { AppProviders } from "./AppProviders";
import { AppShell } from "./AppShell";

vi.mock("maplibre-gl", () => ({ default: mapLibreMock }));

class TestEventSource {
  static readonly instances: TestEventSource[] = [];

  readonly url: string;

  constructor(url: string | URL) {
    this.url = String(url);
    TestEventSource.instances.push(this);
  }

  addEventListener(): void {}

  removeEventListener(): void {}

  close(): void {}
}

function renderShell() {
  return render(
    <AppProviders>
      <AppShell />
    </AppProviders>,
  );
}

function onlyMap(): RecordedMap {
  expect(mapLibreTestState.instances).toHaveLength(1);
  return mapLibreTestState.instances[0];
}

function visualizedIncidentId(map: RecordedMap): unknown {
  const collection = map.sources.get(MAP_SOURCE_IDS.incident)
    ?.data as FeatureCollection<Geometry, { incidentId?: string }> | undefined;
  return collection?.features[0]?.properties?.incidentId;
}

beforeEach(() => {
  resetMapLibreTestState();
  TestEventSource.instances.length = 0;
  vi.stubGlobal(
    "EventSource",
    TestEventSource as unknown as typeof EventSource,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppShell", () => {
  it("renders the required observe surface in server order and updates the workspace when Bear Ridge is selected", async () => {
    const user = userEvent.setup();
    renderShell();

    expect(
      screen.getByRole("heading", { level: 1, name: "WildfireOps" }),
    ).toBeVisible();
    expect(screen.getByText("Observe mode")).toBeVisible();
    expect(screen.getByRole("note")).toHaveTextContent(
      "Portfolio simulation only. Do not use for emergency or life-safety decisions.",
    );

    const queue = await screen.findByRole("complementary", {
      name: "Incident queue",
    });
    const incidentRows = within(queue).getAllByRole("button");
    expect(incidentRows).toHaveLength(2);
    expect(incidentRows[0]).toHaveAccessibleName(/Redwood Creek/i);
    expect(incidentRows[1]).toHaveAccessibleName(/Bear Ridge/i);
    await waitFor(() => {
      expect(incidentRows[0]).toHaveAttribute("aria-pressed", "true");
    });

    expect(
      await screen.findByRole("region", { name: "Wildfire operations map" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Decision workspace" }),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Incident replay timeline" }),
    ).toBeVisible();
    expect(await screen.findByText(/Sources stale/i)).toBeVisible();
    expect(TestEventSource.instances).toHaveLength(1);
    expect(TestEventSource.instances[0].url).toBe("/api/events");

    const map = onlyMap();
    act(() => {
      map.emit("load");
    });
    expect(visualizedIncidentId(map)).toBe(REDWOOD_ID);

    await user.click(incidentRows[1]);

    const overview = screen.getByRole("region", { name: "Incident overview" });
    expect(await within(overview).findByText("Bear Ridge")).toBeVisible();
    expect(incidentRows[1]).toHaveAttribute("aria-pressed", "true");
    expect(incidentRows[0]).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => {
      expect(visualizedIncidentId(map)).toBe(BEAR_ID);
    });
    expect(
      within(screen.getByRole("region", { name: "Risk explanation" })).getByText(
        "61",
      ),
    ).toBeVisible();
  });

  it("selects the nearest returned replay frame while current assets and resources remain current", async () => {
    renderShell();

    const risk = await screen.findByRole("region", {
      name: "Risk explanation",
    });
    expect(within(risk).getByText("82")).toBeVisible();
    expect(
      within(risk).getByRole("heading", { name: "Risk explanation" })
        .nextElementSibling,
    ).toHaveTextContent("Current snapshot");

    const replayPosition = screen.getByRole("slider", {
      name: "Replay position",
    });
    fireEvent.change(replayPosition, {
      target: { value: String(Date.parse("2024-07-24T18:05:00Z")) },
    });

    await waitFor(() => {
      expect(within(risk).getByText("70")).toBeVisible();
      expect(
        within(risk).getByRole("heading", { name: "Risk explanation" })
          .nextElementSibling,
      ).toHaveTextContent("Replay frame");
    });
    expect(screen.getByText(/Replay frame: 1 incident feature/i)).toBeVisible();
    expect(
      within(screen.getByRole("region", { name: "Exposed assets" })).getByText(
        "Current snapshot",
      ),
    ).toBeVisible();
    expect(
      within(
        screen.getByRole("region", { name: "Simulated resources" }),
      ).getByText("Current snapshot"),
    ).toBeVisible();
  });

  it("renders an explicit empty incident state without a stale workspace", async () => {
    server.use(
      http.get("/api/incidents", () =>
        HttpResponse.json({
          items: [],
        }),
      ),
    );

    renderShell();

    expect(
      await screen.findByText("No active incidents are available."),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Wildfire operations map" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Decision workspace" }),
    ).not.toBeInTheDocument();
  });

  it("sanitizes an incident-list failure and recovers through a local retry", async () => {
    let attempts = 0;
    server.use(
      http.get("/api/incidents", () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            {
              error: {
                code: "source_unavailable",
                message: "backend-secret-list-message",
                details: { upstream: "backend-secret-host" },
              },
            },
            { status: 503 },
          );
        }
        return HttpResponse.json(incidentListResponse);
      }),
    );

    const user = userEvent.setup();
    renderShell();

    const failure = await screen.findByRole("alert", {
      name: "Incident queue unavailable",
    });
    expect(failure).toHaveTextContent("Incident data could not be loaded.");
    expect(failure).not.toHaveTextContent(/backend-secret/i);

    await user.click(
      within(failure).getByRole("button", { name: "Retry incidents" }),
    );

    expect(
      await screen.findByRole("button", { name: /Redwood Creek/i }),
    ).toBeVisible();
    expect(attempts).toBe(2);
  });

  it("keeps incidents usable when source freshness fails independently", async () => {
    server.use(
      http.get("/api/sources/status", () =>
        HttpResponse.json(
          {
            error: {
              code: "source_unavailable",
              message: "backend-secret-source-message",
              details: { upstream: "backend-secret-host" },
            },
          },
          { status: 503 },
        ),
      ),
    );

    renderShell();

    const sourceFailure = await screen.findByRole("alert", {
      name: "Source freshness unavailable",
    });
    expect(sourceFailure).not.toHaveTextContent(/backend-secret/i);
    expect(
      within(sourceFailure).getByRole("button", { name: "Retry sources" }),
    ).toBeVisible();
    expect(
      await screen.findByRole("button", { name: /Redwood Creek/i }),
    ).toBeVisible();
    expect(
      await screen.findByRole("region", { name: "Wildfire operations map" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Decision workspace" }),
    ).toBeVisible();
  });

  it("does not report an empty source-status response as fresh", async () => {
    server.use(
      http.get("/api/sources/status", () => HttpResponse.json({ items: [] })),
    );

    renderShell();

    expect(
      await screen.findByText("No source status is available."),
    ).toBeVisible();
    expect(screen.queryByText(/Sources fresh/i)).not.toBeInTheDocument();
  });

  it("distinguishes a pending timeline from an empty replay", async () => {
    server.use(
      http.get("/api/incidents/:incidentId/timeline", async () => {
        await delay("infinite");
        return HttpResponse.json({ items: [] });
      }),
    );

    renderShell();

    expect(await screen.findByText("Loading replay…")).toBeVisible();
    expect(screen.queryByText("Replay unavailable.")).not.toBeInTheDocument();
  });
});
