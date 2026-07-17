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
  baselineRecommendationResponse,
  baselineScenarioVersionResponse,
  incidentListResponse,
  scenarioRecommendationResponse,
  scenarioVersionTwoResponse,
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

type EventListenerValue = EventListenerOrEventListenerObject;

class TestEventSource {
  static readonly instances: TestEventSource[] = [];

  readonly url: string;
  readonly listeners = new Map<string, Set<EventListenerValue>>();

  constructor(url: string | URL) {
    this.url = String(url);
    TestEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerValue): void {
    const listeners = this.listeners.get(type) ?? new Set<EventListenerValue>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListenerValue): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {}

  emit(type: string, payload?: unknown): void {
    const event =
      type === "open" || type === "error"
        ? new Event(type)
        : new MessageEvent(type, {
            data: typeof payload === "string" ? payload : JSON.stringify(payload),
          });

    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") {
        listener.call(this, event);
      } else {
        listener.handleEvent(event);
      }
    }
  }
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
    expect(screen.getByText("Observe + plan")).toBeVisible();
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

  it("runs the complete baseline, immutable branch, and recommendation comparison flow without hiding observe tools", async () => {
    const calls: Array<{
      path: string;
      body: unknown;
      key: string | null;
    }> = [];
    installSuccessfulPlanningCommands(calls);
    const user = userEvent.setup();
    renderShell();

    const overview = await screen.findByRole("region", {
      name: "Incident overview",
    });
    expect(within(overview).getByText("Redwood Creek")).toBeVisible();
    await user.type(
      await screen.findByRole("textbox", { name: "Scenario name (optional)" }),
      "Redwood production drill",
    );
    await user.click(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );

    expect(
      await screen.findByText("Baseline scenario version 1"),
    ).toBeVisible();
    expect(calls.slice(0, 2)).toEqual([
      {
        path: `/api/incidents/${REDWOOD_ID}/scenarios`,
        body: {
          graphVersion: "roads-v1",
          objective: "minimize-response-time",
          name: "Redwood production drill",
          algorithmConfigVersion: "scenario-v1",
        },
        key: expect.any(String),
      },
      {
        path: `/api/scenario-versions/${baselineScenarioVersionResponse.id}/recommendations`,
        body: { maxResponseMinutes: 30, maxSolverSeconds: 2 },
        key: expect.any(String),
      },
    ]);
    expect(calls[0].key).not.toBe("");
    expect(calls[1].key).not.toBe("");

    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.type(screen.getByLabelText("Wind speed (m/s)"), "14.5");
    await user.type(screen.getByLabelText("Wind direction (degrees)"), "225");
    await user.click(screen.getByRole("checkbox", { name: /engine-1/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    expect(
      await screen.findByText(
        "Active version 2 has no successful recommendation yet.",
      ),
    ).toBeVisible();
    expect(calls[2]).toEqual({
      path: `/api/scenarios/${baselineScenarioVersionResponse.scenarioId}/versions`,
      body: {
        roadClosures: [{ edgeId: "edge-2" }],
        weatherOverrides: [
          { windSpeedMps: 14.5, windDirectionDegrees: 225 },
        ],
        resourceOverrides: [{ resourceId: "engine-1", available: false }],
      },
      key: expect.any(String),
    });

    await user.click(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    );
    expect(await screen.findByText("Current scenario version 2")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Scenario outcome comparison" }),
    ).toBeVisible();
    expect(calls[3]).toEqual({
      path: `/api/scenario-versions/${scenarioVersionTwoResponse.id}/recommendations`,
      body: { maxResponseMinutes: 30, maxSolverSeconds: 2 },
      key: expect.any(String),
    });

    expect(within(overview).getByText("Redwood Creek")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Wildfire operations map" }),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Incident replay timeline" }),
    ).toBeVisible();
    expect(screen.getByRole("note")).toBeVisible();
  });

  it("scopes planning freshness to the active incident and ignores source or malformed events", async () => {
    const calls: Array<{
      path: string;
      body: unknown;
      key: string | null;
    }> = [];
    installSuccessfulPlanningCommands(calls);
    const user = userEvent.setup();
    renderShell();
    await screen.findByRole("combobox", { name: "Road graph" });
    const events = TestEventSource.instances[0];

    act(() => {
      events.emit("incident-updated", { incidentId: BEAR_ID });
      events.emit("source-status-updated", { sourceName: "nasa_firms" });
      events.emit("incident-updated", { incidentId: 42 });
    });
    await user.click(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    expect(
      await screen.findByText("Recommendation freshness: Current"),
    ).toBeVisible();

    act(() => {
      events.emit("incident-updated", { incidentId: BEAR_ID });
      events.emit("source-status-updated", { sourceName: "nasa_firms" });
    });
    expect(
      screen.queryByRole("alert", { name: "Stale planning session" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Recommendation freshness: Current"),
    ).toBeVisible();

    act(() => {
      events.emit("incident-updated", { incidentId: REDWOOD_ID });
    });
    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByText("Recommendation freshness: Stale"),
    ).toBeVisible();
  });

  it("treats the first open as baseline reconciliation and a later open as reconnect invalidation", async () => {
    const calls: Array<{
      path: string;
      body: unknown;
      key: string | null;
    }> = [];
    installSuccessfulPlanningCommands(calls);
    const user = userEvent.setup();
    renderShell();
    await screen.findByRole("combobox", { name: "Road graph" });
    const events = TestEventSource.instances[0];

    act(() => {
      events.emit("open");
    });
    await user.click(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    expect(
      await screen.findByText("Recommendation freshness: Current"),
    ).toBeVisible();

    act(() => {
      events.emit("open");
    });
    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByText("Recommendation freshness: Stale"),
    ).toBeVisible();
  });

  it("marks an established planning session stale after a valid resync event", async () => {
    const calls: Array<{
      path: string;
      body: unknown;
      key: string | null;
    }> = [];
    installSuccessfulPlanningCommands(calls);
    const user = userEvent.setup();
    renderShell();
    await screen.findByRole("combobox", { name: "Road graph" });
    await user.click(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await screen.findByText("Recommendation freshness: Current");

    act(() => {
      TestEventSource.instances[0].emit("resync-required", {});
    });
    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByText("Recommendation freshness: Stale"),
    ).toBeVisible();
  });

  it("destroys ephemeral planning state when the selected incident changes", async () => {
    const calls: Array<{
      path: string;
      body: unknown;
      key: string | null;
    }> = [];
    installSuccessfulPlanningCommands(calls);
    const user = userEvent.setup();
    renderShell();

    await screen.findByRole("combobox", { name: "Road graph" });
    await user.click(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    expect(
      await screen.findByText("Baseline scenario version 1"),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Bear Ridge/i }));
    expect(
      await screen.findByRole("combobox", { name: "Road graph" }),
    ).toHaveValue("roads-bear-v1");
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Scenario name (optional)" }),
    ).toHaveValue("");

    await user.click(screen.getByRole("button", { name: /Redwood Creek/i }));
    expect(
      await screen.findByRole("combobox", { name: "Road graph" }),
    ).toHaveValue("roads-v1");
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeEnabled();
  });

  it("passes historical replay policy to planning while keeping read tools usable", async () => {
    renderShell();

    await screen.findByRole("combobox", { name: "Road graph" });
    fireEvent.change(
      screen.getByRole("slider", { name: "Replay position" }),
      { target: { value: String(Date.parse("2024-07-24T18:00:00Z")) } },
    );

    expect(
      await screen.findByText("Return to the current snapshot to plan."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search roads" })).toBeEnabled();
    expect(screen.getByText(/Replay frame: 1 incident feature/i)).toBeVisible();
  });
});

function installSuccessfulPlanningCommands(
  calls: Array<{ path: string; body: unknown; key: string | null }>,
) {
  const record = async (request: Request) => {
    calls.push({
      path: new URL(request.url).pathname,
      body: await request.json(),
      key: request.headers.get("Idempotency-Key"),
    });
  };
  server.use(
    http.post("/api/incidents/:incidentId/scenarios", async ({ request }) => {
      await record(request);
      return HttpResponse.json(baselineScenarioVersionResponse, { status: 201 });
    }),
    http.post(
      "/api/scenarios/:scenarioId/versions",
      async ({ request }) => {
        await record(request);
        return HttpResponse.json(scenarioVersionTwoResponse, { status: 201 });
      },
    ),
    http.post(
      "/api/scenario-versions/:versionId/recommendations",
      async ({ params, request }) => {
        await record(request);
        return HttpResponse.json(
          String(params.versionId) === baselineScenarioVersionResponse.id
            ? baselineRecommendationResponse
            : scenarioRecommendationResponse,
          { status: 201 },
        );
      },
    ),
  );
}
