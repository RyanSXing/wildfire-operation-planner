import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { incidentDetailSchema } from "../../api/types";
import { queryKeys } from "../../api/hooks";
import { AppProviders } from "../../app/AppProviders";
import {
  BEAR_ID,
  REDWOOD_ID,
  baselineRecommendationResponse,
  baselineScenarioVersionResponse,
  bearDetailResponse,
  incidentDetailResponse,
  scenarioRecommendationResponse,
  scenarioVersionTwoResponse,
} from "../../test/fixtures";
import { server } from "../../test/server";
import { ScenarioPlanningPanel } from "./ScenarioPlanningPanel";

const incident = incidentDetailSchema.parse(incidentDetailResponse);
const bearIncident = incidentDetailSchema.parse(bearDetailResponse);

type RecordedCommand = {
  path: string;
  body: unknown;
  key: string | null;
};

function renderPanel(
  planningDisabled = false,
  currentIncident = incident,
  freshnessToken = "0:0",
) {
  return render(
    <AppProviders>
      <ScenarioPlanningPanel
        incident={currentIncident}
        planningDisabled={planningDisabled}
        freshnessToken={freshnessToken}
      />
    </AppProviders>,
  );
}

function installSuccessfulCommands(calls: RecordedCommand[]) {
  server.use(
    http.post("/api/incidents/:incidentId/scenarios", async ({ request }) => {
      calls.push(await recordCommand(request));
      return HttpResponse.json(baselineScenarioVersionResponse, { status: 201 });
    }),
    http.post(
      "/api/scenarios/:scenarioId/versions",
      async ({ request }) => {
        calls.push(await recordCommand(request));
        return HttpResponse.json(scenarioVersionTwoResponse, { status: 201 });
      },
    ),
    http.post(
      "/api/scenario-versions/:versionId/recommendations",
      async ({ params, request }) => {
        calls.push(await recordCommand(request));
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

describe("ScenarioPlanningPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("discovers the default graph and bounded road catalog without posting on mount", async () => {
    renderPanel();

    expect(
      screen.getByRole("status", { name: "Planning context status" }),
    ).toHaveTextContent("Loading planning context");

    const graph = await screen.findByRole("combobox", { name: "Road graph" });
    expect(graph).toHaveValue("roads-v1");
    expect(within(graph).getAllByRole("option")).toHaveLength(2);
    expect(await screen.findByText("Showing 3 of 205 road edges.")).toBeVisible();
    expect(
      screen.getByText("Road catalog is a bounded subset of matching edges."),
    ).toBeVisible();
    expect(screen.getByText(/Alpha Road.*Geometry unavailable/)).toBeVisible();
  });

  it("renders an empty-graph state without issuing road or command requests", async () => {
    let roadRequests = 0;
    let commandRequests = 0;
    server.use(
      http.get("/api/incidents/:incidentId/decision-context", () =>
        HttpResponse.json({
          incidentId: REDWOOD_ID,
          defaultGraphVersion: null,
          availableGraphs: [],
        }),
      ),
      http.get("/api/road-graphs/:graphVersion/edges", () => {
        roadRequests += 1;
        return HttpResponse.json({ items: [], total: 0, missingEdgeIds: [] });
      }),
      http.post("/api/incidents/:incidentId/scenarios", () => {
        commandRequests += 1;
        return HttpResponse.json(baselineScenarioVersionResponse);
      }),
      http.post("/api/scenarios/:scenarioId/versions", () => {
        commandRequests += 1;
        return HttpResponse.json(scenarioVersionTwoResponse);
      }),
      http.post("/api/scenario-versions/:versionId/recommendations", () => {
        commandRequests += 1;
        return HttpResponse.json(baselineRecommendationResponse);
      }),
    );

    renderPanel();

    const emptyState = await screen.findByText(
      "No road graphs are available for planning.",
    );
    expect(emptyState).toHaveAttribute("role", "status");
    expect(
      screen.queryByRole("combobox", { name: "Road graph" }),
    ).not.toBeInTheDocument();
    expect(roadRequests).toBe(0);
    expect(commandRequests).toBe(0);
  });

  it("creates and recommends the baseline before allowing an immutable branch", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    renderPanel();

    await user.type(
      await screen.findByRole("textbox", { name: "Scenario name (optional)" }),
      "Redwood plan",
    );
    const bootstrap = screen.getByRole("button", {
      name: "Create baseline and generate recommendation",
    });
    expect(
      screen.queryByRole("form", { name: "Scenario version editor" }),
    ).not.toBeInTheDocument();
    await user.click(bootstrap);

    const recommendation = await screen.findByRole("region", {
      name: "Recommendation result",
    });
    expect(recommendation).toHaveTextContent("Baseline scenario version 1");
    expect(
      screen.getByRole("button", { name: "Approve recommendation" }),
    ).toBeVisible();
    expect(
      screen.getByRole("form", { name: "Scenario version editor" }),
    ).toBeVisible();
    expect(calls.map(({ path }) => path)).toEqual([
      `/api/incidents/${REDWOOD_ID}/scenarios`,
      `/api/scenario-versions/${baselineScenarioVersionResponse.id}/recommendations`,
    ]);
    expect(calls[0].body).toEqual({
      graphVersion: "roads-v1",
      objective: "minimize-response-time",
      name: "Redwood plan",
      algorithmConfigVersion: "scenario-v1",
    });
    expect(calls[1].body).toEqual({
      maxResponseMinutes: 30,
      maxSolverSeconds: 2,
    });
    expect(calls[0].key).toEqual(expect.any(String));
    expect(calls[0].key).not.toBe("");
    expect(calls[1].key).toEqual(expect.any(String));
    expect(calls[1].key).not.toBe(calls[0].key);
    expect(graphSelection()).toBeDisabled();
  });

  it("keeps the baseline graph locked when refreshed context changes its default", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </QueryClientProvider>,
    );
    await bootstrapBaseline(user);

    act(() => {
      queryClient.setQueryData(
        queryKeys.incidents.decisionContext(REDWOOD_ID),
        {
          incidentId: REDWOOD_ID,
          defaultGraphVersion: "roads-v2",
          availableGraphs: [{ graphVersion: "roads-v2", edgeCount: 9 }],
        },
      );
    });

    await waitFor(() => {
      expect(
        within(graphSelection()).getByRole("option", {
          name: "roads-v2 (9 edges)",
        }),
      ).toBeVisible();
    });
    expect(graphSelection()).toHaveValue("roads-v1");
    expect(
      within(graphSelection()).getByRole("option", {
        name: "roads-v1 (locked baseline)",
      }),
    ).toBeVisible();
    expect(graphSelection()).toBeDisabled();
  });

  it("keeps an established planning workflow visible when refreshed context has no graphs", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </QueryClientProvider>,
    );
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await screen.findByText(
      "Active version 2 has no successful recommendation yet.",
    );

    act(() => {
      queryClient.setQueryData(
        queryKeys.incidents.decisionContext(REDWOOD_ID),
        {
          incidentId: REDWOOD_ID,
          defaultGraphVersion: null,
          availableGraphs: [],
        },
      );
    });

    await waitFor(() => {
      expect(
        screen.queryByText("No road graphs are available for planning."),
      ).not.toBeInTheDocument();
    });
    expect(graphSelection()).toHaveValue("roads-v1");
    expect(
      within(graphSelection()).getByRole("option", {
        name: "roads-v1 (locked baseline)",
      }),
    ).toBeVisible();
    expect(graphSelection()).toBeDisabled();
    expect(screen.getByRole("region", { name: "Road catalog" })).toBeVisible();
    expect(
      screen.getByRole("form", { name: "Scenario version editor" }),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Previous successful scenario version 1");
    expect(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    ).toBeEnabled();
  });

  it("does not issue command POSTs from StrictMode mount effects", async () => {
    let postCount = 0;
    const rejectPost = () => {
      postCount += 1;
      return HttpResponse.json({}, { status: 500 });
    };
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", rejectPost),
      http.post("/api/scenarios/:scenarioId/versions", rejectPost),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        rejectPost,
      ),
    );

    render(
      <StrictMode>
        <AppProviders>
          <ScenarioPlanningPanel
            incident={incident}
            planningDisabled={false}
            freshnessToken="0:0"
          />
        </AppProviders>
      </StrictMode>,
    );

    await screen.findByText("Showing 3 of 205 road edges.");
    expect(postCount).toBe(0);
  });

  it("retries only baseline generation after creation succeeds and reuses its key", async () => {
    const user = userEvent.setup();
    let createAttempts = 0;
    const generationKeys: Array<string | null> = [];
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () => {
        createAttempts += 1;
        return HttpResponse.json(baselineScenarioVersionResponse, {
          status: 201,
        });
      }),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        ({ request }) => {
          generationKeys.push(request.headers.get("Idempotency-Key"));
          if (generationKeys.length === 1) {
            return HttpResponse.json(
              {
                error: {
                  code: "solver_unavailable",
                  message: "secret solver failure",
                  details: {},
                },
              },
              { status: 503 },
            );
          }
          return HttpResponse.json(baselineRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    expect(
      await screen.findByRole("button", {
        name: "Retry baseline recommendation",
      }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Retry baseline recommendation" }),
    );

    expect(
      await screen.findByText("Baseline scenario version 1"),
    ).toBeVisible();
    expect(createAttempts).toBe(1);
    expect(generationKeys).toHaveLength(2);
    expect(generationKeys[1]).toBe(generationKeys[0]);
  });

  it("creates version 2, retains the baseline while pending, then compares the generated result", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    renderPanel();

    await bootstrapBaseline(user);
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
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Previous successful scenario version 1");
    expect(calls[2].body).toEqual({
      roadClosures: [{ edgeId: "edge-2" }],
      weatherOverrides: [
        { windSpeedMps: 14.5, windDirectionDegrees: 225 },
      ],
      resourceOverrides: [{ resourceId: "engine-1", available: false }],
    });

    await user.click(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    );

    expect(
      await screen.findByText("Current scenario version 2"),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Scenario outcome comparison" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 3, name: "Scenario planning" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 4, name: "Recommendation" }),
    ).toBeVisible();
    expect(screen.getByText("Audit history")).toBeVisible();
    expect(
      screen.getByRole("heading", {
        level: 4,
        name: "Scenario outcome comparison",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 5, name: "Assignments" }),
    ).toBeVisible();
    expect(calls[3].body).toEqual({
      maxResponseMinutes: 30,
      maxSolverSeconds: 2,
    });
  });

  it("isolates a pending old decision when a new recommendation replaces its sibling workspace", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const decisionGate = deferred<void>();
    let decisionAttempts = 0;
    server.use(
      http.post("/api/recommendations/:recommendationId/decisions", async () => {
        decisionAttempts += 1;
        await decisionGate.promise;
        return HttpResponse.json(
          { error: { code: "recommendation_stale", message: "hidden", details: {} } },
          { status: 409 },
        );
      }),
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderPanel();
    await bootstrapBaseline(user);

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));
    await waitFor(() => expect(decisionAttempts).toBe(1));
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(screen.getByRole("button", { name: "Save scenario version" }));
    await user.click(await screen.findByRole("button", { name: "Generate recommendation for version 2" }));
    await screen.findByText("Current scenario version 2");

    await release(decisionGate);

    expect(screen.queryByRole("alert", { name: "Stale planning session" })).not.toBeInTheDocument();
    expect(screen.getByText("Recommendation freshness: Current")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve recommendation" })).toBeEnabled();
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
  });

  it("disables the editor without a saving label while recommendation generation is pending", async () => {
    const generationGate = deferred<void>();
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post("/api/scenarios/:scenarioId/versions", () =>
        HttpResponse.json(scenarioVersionTwoResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        async ({ params }) => {
          if (String(params.versionId) === baselineScenarioVersionResponse.id) {
            return HttpResponse.json(baselineRecommendationResponse, {
              status: 201,
            });
          }
          await generationGate.promise;
          return HttpResponse.json(scenarioRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    const user = userEvent.setup();
    renderPanel();
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Generating recommendation for version 2",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: /County Road 1/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();
    expect(screen.queryByText("Saving scenario version")).not.toBeInTheDocument();

    await release(generationGate);
    expect(await screen.findByText("Current scenario version 2")).toBeVisible();
  });

  it("disables generation while a newer immutable version is being saved", async () => {
    const versionGate = deferred<void>();
    let versionAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post("/api/scenarios/:scenarioId/versions", async () => {
        versionAttempts += 1;
        if (versionAttempts === 1) {
          return HttpResponse.json(scenarioVersionTwoResponse, { status: 201 });
        }
        await versionGate.promise;
        return HttpResponse.json(
          {
            ...scenarioVersionTwoResponse,
            id: "scenario-version-redwood-3",
            version: 3,
            roadClosures: [{ edgeId: "edge-1" }, { edgeId: "edge-2" }],
          },
          { status: 201 },
        );
      }),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        ({ params }) =>
          HttpResponse.json(
            String(params.versionId) === baselineScenarioVersionResponse.id
              ? baselineRecommendationResponse
              : scenarioRecommendationResponse,
            { status: 201 },
          ),
      ),
    );
    const user = userEvent.setup();
    renderPanel();
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    );
    await screen.findByText("Current scenario version 2");

    await user.click(screen.getByRole("checkbox", { name: /County Road 1/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(
      await screen.findByRole("button", { name: "Saving scenario version" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    ).toBeDisabled();

    await release(versionGate);
    expect(
      await screen.findByText(
        "Active version 3 has no successful recommendation yet.",
      ),
    ).toBeVisible();
  });

  it("preserves and accurately labels the last success when newer generation fails, then reuses its key", async () => {
    const user = userEvent.setup();
    const generationKeys: Array<string | null> = [];
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post("/api/scenarios/:scenarioId/versions", () =>
        HttpResponse.json(scenarioVersionTwoResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        ({ params, request }) => {
          const key = request.headers.get("Idempotency-Key");
          if (String(params.versionId) === baselineScenarioVersionResponse.id) {
            return HttpResponse.json(baselineRecommendationResponse, {
              status: 201,
            });
          }
          generationKeys.push(key);
          generationAttempts += 1;
          if (generationAttempts === 1) {
            return HttpResponse.json(
              {
                error: {
                  code: "solver_unavailable",
                  message: "backend-secret-solver-message",
                  details: { host: "backend-secret-host" },
                },
              },
              { status: 503 },
            );
          }
          return HttpResponse.json(scenarioRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    renderPanel();

    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    const generate = await screen.findByRole("button", {
      name: "Generate recommendation for version 2",
    });
    await user.click(generate);

    const error = await screen.findByRole("alert", {
      name: "Planning command error",
    });
    expect(error).toHaveTextContent(
      "Request failed. Retrying the unchanged request is safe.",
    );
    expect(error).not.toHaveTextContent(/backend-secret/i);
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Previous successful scenario version 1");
    expect(
      screen.getByText(
        /^Active version 2 has no successful recommendation yet\./,
      ),
    ).toBeVisible();

    await user.click(generate);
    expect(await screen.findByText("Current scenario version 2")).toBeVisible();
    expect(generationKeys).toHaveLength(2);
    expect(generationKeys[1]).toBe(generationKeys[0]);
  });

  it("preserves the prior result and requires start-over after scenario_stale", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post("/api/scenarios/:scenarioId/versions", () =>
        HttpResponse.json(scenarioVersionTwoResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        ({ params }) =>
          String(params.versionId) === baselineScenarioVersionResponse.id
            ? HttpResponse.json(baselineRecommendationResponse, { status: 201 })
            : HttpResponse.json(
                {
                  error: {
                    code: "scenario_stale",
                    message: "backend-secret-stale-message",
                    details: { latestVersion: 3 },
                  },
                },
                { status: 409 },
              ),
      ),
    );
    renderPanel();
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    );

    const stale = await screen.findByRole("alert", {
      name: "Stale planning session",
    });
    expect(stale).toHaveTextContent(
      "Planning state is stale. Start over with the current snapshot.",
    );
    expect(stale).not.toHaveTextContent(/backend-secret/i);
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Previous successful scenario version 1");
    expect(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeEnabled();
  });

  it("keeps reads visible but disables every planning command during replay", async () => {
    renderPanel(true);

    expect(
      await screen.findByText("Return to the current snapshot to plan."),
    ).toBeVisible();
    expect(
      await screen.findByRole("combobox", { name: "Road graph" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search roads" })).toBeEnabled();
    expect(await screen.findByText("Showing 3 of 205 road edges.")).toBeVisible();
  });

  it("uses the latest freshness token as the baseline when an event arrives before planning", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    const view = renderPanel(false, incident, "0:0");
    await screen.findByRole("combobox", { name: "Road graph" });

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:1"
        />
      </AppProviders>,
    );
    await bootstrapBaseline(user);

    expect(
      screen.getByText("Recommendation freshness: Current"),
    ).toBeVisible();
    expect(
      screen.queryByRole("alert", { name: "Stale planning session" }),
    ).not.toBeInTheDocument();
  });

  it("latches an established planning session stale until local start-over", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    const view = renderPanel(false, incident, "0:0");
    await bootstrapBaseline(user);
    expect(
      screen.getByText("Recommendation freshness: Current"),
    ).toBeVisible();

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:1"
        />
      </AppProviders>,
    );

    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByText("Recommendation freshness: Stale"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:1"
        />
      </AppProviders>,
    );
    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    await bootstrapBaseline(user);
    expect(
      screen.getByText("Recommendation freshness: Current"),
    ).toBeVisible();
  });

  it("retains an in-flight recommendation but marks it stale when freshness changes", async () => {
    const generationGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        async () => {
          generationAttempts += 1;
          await generationGate.promise;
          return HttpResponse.json(baselineRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    const user = userEvent.setup();
    const view = renderPanel(false, incident, "0:0");

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await waitFor(() => expect(generationAttempts).toBe(1));
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:1"
        />
      </AppProviders>,
    );
    await release(generationGate);

    expect(
      await screen.findByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Baseline scenario version 1");
    expect(
      screen.getByText("Recommendation freshness: Stale"),
    ).toBeVisible();
    expect(
      screen.getByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
  });

  it("marks retained results stale after the incident snapshot changes and only start-over unlocks planning", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    const view = renderPanel();
    await bootstrapBaseline(user);

    const nextIncident = {
      ...incident,
      snapshotId: "10000000-0000-0000-0000-000000000099",
      snapshotVersion: incident.snapshotVersion + 1,
    };
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={nextIncident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );

    const stale = await screen.findByRole("alert", {
      name: "Stale planning session",
    });
    expect(stale).toHaveTextContent(
      "Planning state is stale. Start over with the current snapshot.",
    );
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeEnabled();
    expect(graphSelection()).toBeEnabled();
  });

  it("keeps a snapshot mismatch latched after props return to the original snapshot", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    const view = renderPanel();
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await screen.findByText(
      "Active version 2 has no successful recommendation yet.",
    );

    const nextIncident = {
      ...incident,
      snapshotId: "10000000-0000-0000-0000-000000000099",
      snapshotVersion: incident.snapshotVersion + 1,
    };
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={nextIncident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    await screen.findByRole("alert", { name: "Stale planning session" });

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );

    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "Generate recommendation for version 2",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: /County Road 1/ }),
    ).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeEnabled();
  });

  it("retains a created baseline without generating when replay starts during creation", async () => {
    const createGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", async () => {
        await createGate.promise;
        return HttpResponse.json(baselineScenarioVersionResponse, {
          status: 201,
        });
      }),
      http.post("/api/scenario-versions/:versionId/recommendations", () => {
        generationAttempts += 1;
        return HttpResponse.json(baselineRecommendationResponse, {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    const view = renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    await release(createGate);

    expect(
      await screen.findByRole("button", {
        name: "Retry baseline recommendation",
      }),
    ).toBeDisabled();
    expect(generationAttempts).toBe(0);
    expect(
      screen.getByText("Return to the current snapshot to plan."),
    ).toBeVisible();
  });

  it("marks a created baseline stale without generating when the snapshot changes during creation", async () => {
    const createGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", async () => {
        await createGate.promise;
        return HttpResponse.json(baselineScenarioVersionResponse, {
          status: 201,
        });
      }),
      http.post("/api/scenario-versions/:versionId/recommendations", () => {
        generationAttempts += 1;
        return HttpResponse.json(baselineRecommendationResponse, {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    const view = renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={{
            ...incident,
            snapshotId: "10000000-0000-0000-0000-000000000099",
            snapshotVersion: incident.snapshotVersion + 1,
          }}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    await release(createGate);

    expect(
      await screen.findByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Retry baseline recommendation" }),
    ).toBeDisabled();
    expect(generationAttempts).toBe(0);
  });

  it("does not continue a deferred create after a keyed incident switch unmounts the panel", async () => {
    const createGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", async () => {
        await createGate.promise;
        return HttpResponse.json(baselineScenarioVersionResponse, {
          status: 201,
        });
      }),
      http.post("/api/scenario-versions/:versionId/recommendations", () => {
        generationAttempts += 1;
        return HttpResponse.json(baselineRecommendationResponse, {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    const view = render(
      <AppProviders>
        <ScenarioPlanningPanel
          key={REDWOOD_ID}
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          key={BEAR_ID}
          incident={bearIncident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    expect(
      await screen.findByRole("combobox", { name: "Road graph" }),
    ).toHaveValue("roads-bear-v1");
    await release(createGate);

    expect(generationAttempts).toBe(0);
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(graphSelection()).toHaveValue("roads-bear-v1");
  });

  it("retains an in-flight generation result for inspection when replay starts", async () => {
    const generationGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        async () => {
          generationAttempts += 1;
          await generationGate.promise;
          return HttpResponse.json(baselineRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    const user = userEvent.setup();
    const view = renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await waitFor(() => expect(generationAttempts).toBe(1));
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    await release(generationGate);

    expect(generationAttempts).toBe(1);
    expect(
      await screen.findByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Baseline scenario version 1");
    expect(
      screen.queryByRole("button", { name: "Retry baseline recommendation" }),
    ).not.toBeInTheDocument();

    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={incident}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    expect(
      screen.getByRole("region", { name: "Recommendation result" }),
    ).toBeVisible();
    expect(generationAttempts).toBe(1);
  });

  it("retains and marks an in-flight generation result stale when the snapshot changes", async () => {
    const generationGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        async () => {
          generationAttempts += 1;
          await generationGate.promise;
          return HttpResponse.json(baselineRecommendationResponse, {
            status: 201,
          });
        },
      ),
    );
    const user = userEvent.setup();
    const view = renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await waitFor(() => expect(generationAttempts).toBe(1));
    view.rerender(
      <AppProviders>
        <ScenarioPlanningPanel
          incident={{
            ...incident,
            snapshotId: "10000000-0000-0000-0000-000000000099",
            snapshotVersion: incident.snapshotVersion + 1,
          }}
          planningDisabled={false}
          freshnessToken="0:0"
        />
      </AppProviders>,
    );
    await release(generationGate);

    expect(generationAttempts).toBe(1);
    expect(
      await screen.findByRole("region", { name: "Recommendation result" }),
    ).toHaveTextContent("Baseline scenario version 1");
    expect(
      screen.getByRole("alert", { name: "Stale planning session" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Retry baseline recommendation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();
  });

  it("does not let a late baseline-create response resurrect a reset session", async () => {
    const createGate = deferred<void>();
    let generationAttempts = 0;
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", async () => {
        await createGate.promise;
        return HttpResponse.json(
          {
            ...baselineScenarioVersionResponse,
            incidentSnapshotId: "late-stale-snapshot",
          },
          { status: 201 },
        );
      }),
      http.post("/api/scenario-versions/:versionId/recommendations", () => {
        generationAttempts += 1;
        return HttpResponse.json(baselineRecommendationResponse, {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Start over" }));
    await release(createGate);

    expect(
      screen.queryByRole("alert", { name: "Stale planning session" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
    expect(generationAttempts).toBe(0);
    expect(
      screen.getByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    ).toBeEnabled();
  });

  it("does not let a late baseline-generation response resurrect a reset session", async () => {
    const generationGate = deferred<void>();
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post(
        "/api/scenario-versions/:versionId/recommendations",
        async () => {
          await generationGate.promise;
          return HttpResponse.json(
            {
              ...baselineRecommendationResponse,
              incidentSnapshotId: "late-stale-snapshot",
            },
            { status: 201 },
          );
        },
      ),
    );
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", {
        name: "Create baseline and generate recommendation",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Start over" }));
    await release(generationGate);

    expect(
      screen.queryByRole("alert", { name: "Stale planning session" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Recommendation result" }),
    ).not.toBeInTheDocument();
  });

  it("does not let a late version response restore stale state after reset", async () => {
    const versionGate = deferred<void>();
    server.use(
      http.post("/api/incidents/:incidentId/scenarios", () =>
        HttpResponse.json(baselineScenarioVersionResponse, { status: 201 }),
      ),
      http.post("/api/scenario-versions/:versionId/recommendations", () =>
        HttpResponse.json(baselineRecommendationResponse, { status: 201 }),
      ),
      http.post("/api/scenarios/:scenarioId/versions", async () => {
        await versionGate.promise;
        return HttpResponse.json(
          {
            ...scenarioVersionTwoResponse,
            incidentSnapshotId: "late-stale-snapshot",
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPanel();
    await bootstrapBaseline(user);
    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    await user.click(screen.getByRole("button", { name: "Start over" }));
    await release(versionGate);

    expect(
      screen.queryByRole("alert", { name: "Stale planning session" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Scenario version editor" }),
    ).not.toBeInTheDocument();
  });

  it("keeps selected draft closures visible after a submitted road search", async () => {
    const calls: RecordedCommand[] = [];
    installSuccessfulCommands(calls);
    const user = userEvent.setup();
    renderPanel();
    await bootstrapBaseline(user);

    await user.click(screen.getByRole("checkbox", { name: /Alpha Road/ }));
    await user.type(screen.getByRole("searchbox", { name: "Search road edges" }), "County");
    await user.click(screen.getByRole("button", { name: "Search roads" }));

    expect(await screen.findByText("Showing 1 of 1 road edges.")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "edge-2" })).toBeChecked();
  });

  it("contains context and road failures with fixed local messages", async () => {
    server.use(
      http.get("/api/incidents/:incidentId/decision-context", () =>
        HttpResponse.json(
          {
            error: {
              code: "secret_context_code",
              message: "backend-secret-context-message",
              details: { host: "backend-secret-host" },
            },
          },
          { status: 503 },
        ),
      ),
    );
    const first = renderPanel();

    const contextError = await screen.findByRole("alert", {
      name: "Planning context unavailable",
    });
    expect(contextError).toHaveTextContent(
      "Planning context could not be loaded.",
    );
    expect(contextError).not.toHaveTextContent(/backend-secret/i);
    first.unmount();

    server.resetHandlers();
    server.use(
      http.get("/api/road-graphs/:graphVersion/edges", () =>
        HttpResponse.json(
          {
            error: {
              code: "secret_road_code",
              message: "backend-secret-road-message",
              details: { host: "backend-secret-host" },
            },
          },
          { status: 500 },
        ),
      ),
    );
    renderPanel();
    const roadError = await screen.findByRole("alert", {
      name: "Road catalog unavailable",
    });
    expect(roadError).toHaveTextContent("Road catalog could not be loaded.");
    expect(roadError).not.toHaveTextContent(/backend-secret/i);
    expect(
      screen.getByRole("region", { name: "Scenario planning" }),
    ).toBeVisible();
  });
});

async function bootstrapBaseline(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("combobox", { name: "Road graph" });
  await user.click(
    screen.getByRole("button", {
      name: "Create baseline and generate recommendation",
    }),
  );
  await screen.findByText("Baseline scenario version 1");
}

function graphSelection(): HTMLSelectElement {
  return screen.getByRole("combobox", { name: "Road graph" });
}

async function recordCommand(request: Request): Promise<RecordedCommand> {
  return {
    path: new URL(request.url).pathname,
    body: await request.json(),
    key: request.headers.get("Idempotency-Key"),
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

async function release(gate: ReturnType<typeof deferred<void>>) {
  await act(async () => {
    gate.resolve();
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}
