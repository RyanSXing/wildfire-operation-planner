import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Recommendation } from "../../api/types";
import { RecommendationPanel } from "./RecommendationPanel";

const recommendation: Recommendation = {
  id: "recommendation-2",
  scenarioVersionId: "version-2",
  incidentSnapshotId: "snapshot-1",
  assignments: [
    {
      resourceId: "engine-1",
      destinationId: "town-1",
      route: {
        status: "reachable",
        edgeIds: ["edge-2", "edge-9"],
        distanceMeters: 1_250.5,
        travelMinutes: 8.25,
        graphVersion: "roads-v1",
        closureHash: "closure-hash",
      },
      travelMinutes: 8.25,
      capacity: 4,
    },
  ],
  uncoveredDestinationIds: ["town-2"],
  objectiveComponents: {
    travelCost: 8,
    uncoveredRiskPenalty: 20,
    objectiveValue: 28,
  },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 17,
  graphVersion: "roads-v1",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "input-hash",
  sourceVersions: { observation_inputs: "snapshot-1" },
  explanation: {
    binding_constraints: ["crew_capacity", "road_closure"],
    unassigned_resource_ids: ["engine-2"],
    solver_status: "OPTIMAL",
  },
  outcome: {
    scenarioRisk: {
      score: 24,
      algorithmVersion: "risk-v1",
      contributions: [],
    },
    weightedRiskCovered: 24,
    weightedRiskUncovered: 8,
    totalTravelMinutes: 8.25,
    unreachableDestinationIds: ["town-2"],
    unavailableResourceIds: ["engine-2"],
  },
};

describe("RecommendationPanel", () => {
  it.each([
    ["current", "Current"],
    ["stale", "Stale"],
  ] as const)("renders an explicit %s freshness label", (freshness, label) => {
    render(
      <RecommendationPanel
        recommendation={recommendation}
        versionLabel="Current scenario version 2"
        freshness={freshness}
      />,
    );

    expect(
      screen.getByText(`Recommendation freshness: ${label}`),
    ).toBeVisible();
  });

  it("renders an actionable result with complete assignment evidence", () => {
    render(
      <RecommendationPanel
        recommendation={recommendation}
        versionLabel="Current scenario version 2"
        freshness="current"
      />,
    );

    expect(screen.getByText("Current scenario version 2")).toBeVisible();
    const solver = screen.getByRole("status");
    expect(solver).toHaveTextContent("OPTIMAL");
    expect(solver).toHaveTextContent("Actionable recommendation");

    const assignment = within(
      screen.getByRole("list", { name: "Recommendation assignments" }),
    ).getByRole("listitem");
    expectDefinition(assignment, "Resource", "engine-1");
    expectDefinition(assignment, "Destination", "town-1");
    expectDefinition(assignment, "Route status", "reachable");
    expectDefinition(assignment, "Edge IDs", "edge-2, edge-9");
    expectDefinition(assignment, "Distance", "1,250.5 m");
    expectDefinition(assignment, "Route travel", "8.25 min");
    expectDefinition(assignment, "Assignment travel", "8.25 min");
    expectDefinition(assignment, "Capacity", "4");

    expect(
      within(
        screen.getByRole("list", { name: "Uncovered destinations" }),
      ).getByText("town-2"),
    ).toBeVisible();
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Runtime", "17 ms");
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Travel cost", "8");
    expectDefinition(
      screen.getByRole("region", { name: "Solver evidence" }),
      "Uncovered risk penalty",
      "20",
    );
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Objective value", "28");
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Graph", "roads-v1");
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Risk", "risk-v1");
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Allocation", "allocation-v1");
    expectDefinition(screen.getByRole("region", { name: "Solver evidence" }), "Input", "input-hash");
    expect(
      screen.getByText(/"observation_inputs": "snapshot-1"/),
    ).toBeVisible();
  });

  it.each(["FEASIBLE", "OPTIMAL"])(
    "marks %s as actionable",
    (solverStatus) => {
      render(
        <RecommendationPanel
          recommendation={{ ...recommendation, solverStatus }}
          versionLabel="Current scenario version 2"
          freshness="current"
        />,
      );

      expect(screen.getByRole("status")).toHaveTextContent(
        "Actionable recommendation",
      );
    },
  );

  it.each(["INFEASIBLE", "UNKNOWN"])(
    "marks %s as non-actionable rather than empty success",
    (solverStatus) => {
      render(
        <RecommendationPanel
          recommendation={{
            ...recommendation,
            solverStatus,
            assignments: [],
            uncoveredDestinationIds: [],
          }}
          versionLabel="Previous successful version 1"
          freshness="current"
        />,
      );

      expect(screen.getByText("Previous successful version 1")).toBeVisible();
      expect(screen.getByRole("status")).toHaveTextContent(solverStatus);
      expect(screen.getByRole("status")).toHaveTextContent(
        "Non-actionable solver result",
      );
      expect(screen.getByText("No assignments were returned.")).toBeVisible();
      expect(screen.getByText("No destinations are uncovered.")).toBeVisible();
    },
  );

  it("renders known diagnostics and the complete explanation fallback", () => {
    render(
      <RecommendationPanel
        recommendation={recommendation}
        versionLabel="Current scenario version 2"
        freshness="current"
      />,
    );

    const diagnostics = screen.getByRole("region", {
      name: "Constraint diagnostics",
    });
    expect(diagnostics).toHaveTextContent("crew_capacity");
    expect(diagnostics).toHaveTextContent("road_closure");
    expect(diagnostics).toHaveTextContent("engine-2");
    const disclosure = screen.getByText("Full solver explanation").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).toHaveTextContent('"binding_constraints"');
    expect(disclosure).toHaveTextContent('"solver_status": "OPTIMAL"');
    expect(
      screen.queryByRole("button", { name: /approve|reject|edit/i }),
    ).not.toBeInTheDocument();
  });

  it("ignores malformed known diagnostics while preserving bounded JSON", () => {
    render(
      <RecommendationPanel
        recommendation={{
          ...recommendation,
          explanation: {
            binding_constraints: "not-an-array",
            unassigned_resource_ids: ["engine-2", 7],
          },
        }}
        versionLabel="Current scenario version 2"
        freshness="current"
      />,
    );

    const diagnostics = screen.getByRole("region", {
      name: "Constraint diagnostics",
    });
    expect(diagnostics).toHaveTextContent("No known constraint diagnostics");
    expect(screen.getByText("Full solver explanation").closest("details")).toHaveTextContent(
      '"binding_constraints": "not-an-array"',
    );
  });

  it("renders only the valid known diagnostic when its sibling is malformed", () => {
    render(
      <RecommendationPanel
        recommendation={{
          ...recommendation,
          explanation: {
            binding_constraints: { malformed: true },
            unassigned_resource_ids: ["engine-2"],
          },
        }}
        versionLabel="Current scenario version 2"
        freshness="current"
      />,
    );

    const diagnostics = screen.getByRole("region", {
      name: "Constraint diagnostics",
    });
    expect(within(diagnostics).getByText("engine-2")).toBeVisible();
    expect(
      within(diagnostics).queryByText("Binding constraints"),
    ).not.toBeInTheDocument();
    expect(
      within(diagnostics).queryByText("None reported"),
    ).not.toBeInTheDocument();
  });
});

function expectDefinition(
  container: HTMLElement,
  term: string,
  value: string,
): void {
  const termElement = within(container).getByText(term, { selector: "dt" });
  expect(termElement.nextElementSibling).toHaveTextContent(value);
}
