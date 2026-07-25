import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiClient } from "../api/client";
import { ExerciseConflictError, exerciseApiClient } from "../api/exerciseClient";
import type {
  ExerciseMetadata,
  ExercisePlanCommand,
  ExerciseSession,
  PlanOutput,
} from "../api/exerciseTypes";
import { AppProviders } from "../app/AppProviders";
import { mapLibreMock, resetMapLibreTestState } from "../test/maplibre";
import { ExerciseWorkspace, SESSION_STORAGE_KEY } from "./ExerciseWorkspace";

vi.mock("maplibre-gl", () => ({ default: mapLibreMock }));

// Values mirror live `park-fire-decision` responses.
const metadata: ExerciseMetadata = {
  exerciseId: "park-fire-decision",
  version: "2",
  name: "Park Fire decision exercise",
  description: "A portfolio decision exercise.",
  checkpointCount: 3,
  objectives: [
    "fastest-response",
    "protect-critical-services",
    "maximize-population-coverage",
  ],
  safetyStatement:
    "Portfolio decision exercise only. Do not use for emergency or life-safety decisions.",
  assets: [
    {
      assetId: "census-place-0655520",
      assetKind: "community",
      name: "Paradise town",
      position: { longitude: -121.6064, latitude: 39.754192 },
      sourceName: "census",
      sourceVersion: "2020-decennial-pl",
      sourceRecordId: "census-place-0655520",
      citationUrl: "https://www.census.gov/quickfacts",
      provenance: "historical",
    },
    {
      assetId: "census-place-0613014",
      assetKind: "community",
      name: "Chico city",
      position: { longitude: -121.81772, latitude: 39.758951 },
      sourceName: "census",
      sourceVersion: "2020-decennial-pl",
      sourceRecordId: "census-place-0613014",
      citationUrl: "https://www.census.gov/quickfacts",
      provenance: "historical",
    },
  ],
  resources: [
    {
      resourceId: "exercise-bus-1",
      resourceType: "evacuation-bus",
      capabilities: ["evacuation-transport"],
      capacity: 40,
      available: true,
      position: { longitude: -121.6064, latitude: 39.754192 },
      provenance: "exercise",
    },
  ],
  sandbox: {
    checkpointKeys: ["initial-allocation"],
    closureEdgeIds: ["edge-nunneley"],
    windPresets: [
      {
        key: "historical-calm",
        disruption: {
          windSpeedMps: 2.1,
          windDirectionDegrees: 210,
          closedEdgeIds: [],
          provenance: "exercise",
        },
      },
    ],
    priorityPresets: [
      { key: "standard", multiplier: 1 },
      { key: "elevated", multiplier: 2 },
      { key: "urgent", multiplier: 3 },
    ],
  },
};

const plan: PlanOutput = {
  status: "OPTIMAL",
  assignments: [
    {
      resourceId: "exercise-bus-1",
      taskId: "evacuate-paradise",
      incidentId: "park-fire",
      assetId: "census-place-0655520",
      capacity: 40,
      travelMinutes: 0,
      route: {
        status: "reachable",
        edgeIds: [],
        distanceMeters: 0,
        travelMinutes: 0,
      },
    },
  ],
  uncoveredTaskIds: ["evacuate-chico"],
  coveredTaskIds: ["evacuate-paradise"],
  taskCoverage: [
    {
      taskId: "evacuate-chico",
      requiredCapacity: 40,
      suppliedCapacity: 0,
      covered: false,
    },
    {
      taskId: "evacuate-paradise",
      requiredCapacity: 40,
      suppliedCapacity: 40,
      covered: true,
    },
  ],
  candidateFacts: [],
  unassignedResourceIds: [],
  objectiveComponents: {
    travelCost: 0,
    uncoveredTaskPenalty: 121,
    objectiveValue: 121,
  },
  bindingConstraints: [
    "resource-contention: task=evacuate-chico; eligible assignments=exercise-bus-1->evacuate-paradise consume needed capacity",
  ],
  runtimeMilliseconds: 1,
  algorithmVersion: "task-allocation-v1",
  explanation: {
    changes: [
      {
        code: "plan.outcome",
        summary: "The plan covers 1 of 2 tasks; 1 remains uncovered.",
        evidence: {
          coveredTaskIds: ["evacuate-paradise"],
          status: "OPTIMAL",
          uncoveredTaskIds: ["evacuate-chico"],
        },
      },
      {
        code: "task.uncovered-contention",
        summary:
          "evacuate-chico remains uncovered because its compatible resource is assigned elsewhere.",
        evidence: {
          resourceIds: ["exercise-bus-1"],
          taskId: "evacuate-chico",
        },
      },
    ],
  },
  versions: { inputHash: "hash-1", graph: "graph-1" },
};

function session(overrides: Partial<ExerciseSession> = {}): ExerciseSession {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    exerciseId: "park-fire-decision",
    definitionVersion: "2",
    definitionDigest: "3d4bca9ca86b7356186d8f71848684083bac913f",
    callsign: "EMBER-TEST",
    displayName: null,
    checkpointIndex: 0,
    objective: null,
    status: "active",
    version: 1,
    consequences: {},
    expiresAt: "2026-07-26T17:41:25.809768Z",
    allowedActions: ["select-objective"],
    currentCheckpoint: {
      checkpointKey: "initial-allocation",
      title: "Initial allocation",
      situationSummary:
        "Historical detections establish the Park Fire; task demand is an exercise assumption.",
      decisionPrompt: "Choose an objective and allocate the scarce resources.",
      referenceAt: "2024-07-29T20:10:00Z",
      historicalWeatherIdentity: "noaa_ncei:72497393203-2024-07-29T19:54:00",
      incidents: [
        {
          incidentKey: "park-fire",
          name: "Park Fire",
          provenance: "historical",
          detectionIdentities: ["nasa_firms:viirs-snpp-2024-us-line-225982"],
          simulatedPosition: null,
        },
      ],
      tasks: [
        task("evacuate-paradise", "census-place-0655520", 4764),
        task("evacuate-chico", "census-place-0613014", 101475),
      ],
      disruption: {
        windSpeedMps: 2.1,
        windDirectionDegrees: 210,
        closedEdgeIds: [],
        provenance: "exercise",
      },
      fieldReports: [],
    },
    latestPlan: null,
    ...overrides,
  };
}

function task(taskId: string, assetId: string, affectedPopulation: number) {
  return {
    taskId,
    incidentKey: "park-fire",
    assetId,
    taskType: "community-evacuation",
    requiredCapability: "evacuation-transport",
    requiredCapacity: 40,
    deadlineMinutes: 1000,
    affectedPopulation,
    criticalService: false,
    basePriority: 100,
    provenance: "exercise",
  };
}

function renderWorkspace() {
  return render(
    <AppProviders>
      <ExerciseWorkspace />
    </AppProviders>,
  );
}

beforeEach(() => {
  resetMapLibreTestState();
  window.sessionStorage.clear();
  vi.spyOn(exerciseApiClient, "getMetadata").mockResolvedValue(metadata);
  vi.spyOn(exerciseApiClient, "getAudit").mockResolvedValue({ items: [] });
  vi.spyOn(exerciseApiClient, "getSession").mockResolvedValue(session());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ExerciseWorkspace", () => {
  it("discloses safety and provenance before a session can be created", async () => {
    const createSession = vi
      .spyOn(exerciseApiClient, "createSession")
      .mockResolvedValue(session());
    renderWorkspace();

    expect(
      await screen.findByRole("heading", {
        name: "Park Fire decision exercise",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/Do not use for emergency or life-safety decisions/),
    ).toBeVisible();
    expect(screen.getByText(/Invented for training/)).toBeVisible();
    expect(createSession).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: /start the exercise/ }),
    );
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("sends the version it is holding and stops the operator at the objective", async () => {
    const selectObjective = vi
      .spyOn(exerciseApiClient, "selectObjective")
      .mockResolvedValue(
        session({
          objective: "protect-critical-services",
          version: 2,
          allowedActions: ["select-objective", "generate-plan"],
        }),
      );
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, session().id);
    renderWorkspace();

    const picker = await screen.findByRole("dialog", {
      name: "Choose an objective",
    });
    await userEvent.click(
      within(picker).getByRole("button", { name: /Protect critical services/ }),
    );

    expect(selectObjective).toHaveBeenCalledWith(
      session().id,
      { expectedVersion: 1, objective: "protect-critical-services" },
      expect.any(String),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Generate the plan" }),
      ).toBeVisible(),
    );
  });

  it("explains an uncovered task in plain language and shows no raw identifiers", async () => {
    const planned = session({
      objective: "protect-critical-services",
      version: 3,
      allowedActions: ["select-objective", "advance"],
      latestPlan: plan,
    });
    vi.spyOn(exerciseApiClient, "getSession").mockResolvedValue(
      session({
        objective: "protect-critical-services",
        version: 2,
        allowedActions: ["select-objective", "generate-plan"],
      }),
    );
    vi.spyOn(exerciseApiClient, "generatePlan").mockResolvedValue({
      session: planned,
      plan: {
        id: "plan-1",
        sessionId: planned.id,
        checkpointKey: "initial-allocation",
        inputHash: "hash-1",
        inputData: {},
        outputData: plan,
        versions: {},
        createdAt: "2026-07-25T17:41:25.000Z",
      },
    } satisfies ExercisePlanCommand);
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, planned.id);
    renderWorkspace();

    await userEvent.click(
      await screen.findByRole("button", { name: "Generate the plan" }),
    );

    const briefing = await screen.findByRole("dialog", {
      name: "Initial allocation",
    });
    expect(
      within(briefing).getByText("Evacuate Chico city is uncovered"),
    ).toBeVisible();
    expect(within(briefing).getByText(/Evacuation bus 1 could do this job/)).toBeVisible();
    expect(briefing.textContent).not.toContain("exercise-bus-1");
    expect(briefing.textContent).not.toContain("evacuate-chico");

    await userEvent.click(
      within(briefing).getByRole("button", { name: "Review the plan" }),
    );

    const drawer = screen.getByRole("complementary", {
      name: "Checkpoint details",
    });
    expect(within(drawer).getByText("Evacuate Paradise town")).toBeVisible();
    expect(within(drawer).getByText("Evacuation bus 1")).toBeVisible();

    await userEvent.click(within(drawer).getByRole("tab", { name: "Evidence" }));
    expect(
      within(drawer).getByText(
        "Evacuate Chico city has no capacity left — Evacuation bus 1 is on Evacuate Paradise town.",
      ),
    ).toBeVisible();
  });

  it("does not show the previous checkpoint's plan after advancing", async () => {
    // The server keeps returning the last accepted plan in `latestPlan` until a
    // new one is generated, so a naive read shows checkpoint 0's assignments
    // under checkpoint 1's title.
    const advanced = session({
      objective: "protect-critical-services",
      version: 4,
      checkpointIndex: 1,
      allowedActions: ["select-objective", "generate-plan"],
      latestPlan: plan,
    });
    vi.spyOn(exerciseApiClient, "getSession").mockResolvedValue(advanced);
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, advanced.id);
    renderWorkspace();

    const drawer = await screen.findByRole("complementary", {
      name: "Checkpoint details",
    });
    expect(within(drawer).getByText(/No plan yet for this checkpoint/)).toBeVisible();
    expect(within(drawer).queryByText("Evacuation bus 1")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Generate the plan" }),
    ).toBeVisible();
  });

  it("clears a closure the plan reports as reopened", async () => {
    // A corridor the checkpoint scripts as closed can have been cleared by an
    // earlier decision; the plan's change list is the authority.
    const reopened = session({
      objective: "protect-critical-services",
      version: 5,
      allowedActions: ["select-objective", "advance"],
      latestPlan: {
        ...plan,
        assignments: [
          {
            ...plan.assignments[0],
            route: { ...plan.assignments[0].route, edgeIds: ["edge-route-1"] },
          },
        ],
        explanation: {
          changes: [
            ...plan.explanation.changes,
            {
              code: "route.reopened",
              summary: "A corridor reopened.",
              evidence: { edgeId: "edge-nunneley" },
            },
          ],
        },
      },
    });
    reopened.currentCheckpoint.disruption.closedEdgeIds = ["edge-nunneley"];
    vi.spyOn(exerciseApiClient, "getSession").mockResolvedValue(reopened);
    const listRoadEdges = vi.spyOn(apiClient, "listRoadEdges").mockResolvedValue({
      items: [],
      total: 0,
      missingEdgeIds: [],
    });
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, reopened.id);
    renderWorkspace();

    await screen.findByRole("complementary", { name: "Checkpoint details" });
    // Route geometry is still fetched, so the absence of the closure below is
    // the fix working rather than the whole lookup being skipped.
    await waitFor(() => expect(listRoadEdges).toHaveBeenCalled());
    for (const call of listRoadEdges.mock.calls) {
      expect(call[1].edgeIds ?? []).toContain("edge-route-1");
      expect(call[1].edgeIds ?? []).not.toContain("edge-nunneley");
    }
    expect(document.querySelector(".wf-marker--closed")).not.toBeInTheDocument();
  });

  it("adopts the authoritative session when the server rejects a stale version", async () => {
    const stale = session({
      objective: "protect-critical-services",
      version: 2,
      allowedActions: ["select-objective", "generate-plan"],
    });
    const authoritative = session({
      objective: "protect-critical-services",
      version: 7,
      allowedActions: ["approve-plan"],
      latestPlan: plan,
    });
    vi.spyOn(exerciseApiClient, "getSession").mockResolvedValue(stale);
    vi.spyOn(exerciseApiClient, "generatePlan").mockRejectedValue(
      new ExerciseConflictError(
        new ApiClientError(
          "exercise_version_conflict",
          "exercise session version did not match",
          { currentSession: authoritative },
          409,
        ),
      ),
    );
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, stale.id);
    renderWorkspace();

    await userEvent.click(
      await screen.findByRole("button", { name: "Generate the plan" }),
    );

    // The workspace resynchronises to the server's state instead of guessing,
    // and still walks the operator through the plan it had not seen.
    const briefing = await screen.findByRole("dialog", {
      name: "Initial allocation",
    });
    expect(
      screen.getByText(/version did not match.*resynchronised/i),
    ).toBeVisible();
    await userEvent.click(
      within(briefing).getByRole("button", { name: "Review the plan" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Approve the plan" }),
    ).toBeVisible();
  });
});
