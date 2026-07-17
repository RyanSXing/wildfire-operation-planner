import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiClient } from "../../api/client";
import type { Decision, Recommendation } from "../../api/types";
import { AppProviders } from "../../app/AppProviders";
import { DecisionDialog } from "./DecisionDialog";

const recommendation: Recommendation = {
  id: "recommendation-1",
  scenarioVersionId: "version-1",
  incidentSnapshotId: "snapshot-1",
  assignments: [
    {
      resourceId: "resource-1",
      destinationId: "asset-1",
      route: { status: "reachable", edgeIds: ["edge-1"], distanceMeters: 1, travelMinutes: 2, graphVersion: "roads-v1", closureHash: "closures-1" },
      travelMinutes: 2,
      capacity: 1,
    },
  ],
  uncoveredDestinationIds: [],
  objectiveComponents: { travelCost: 2, uncoveredRiskPenalty: 0, objectiveValue: 2 },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 1,
  graphVersion: "roads-v1",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "input-1",
  sourceVersions: {},
  explanation: {},
  outcome: { scenarioRisk: { score: 1, algorithmVersion: "risk-v1", contributions: [] }, weightedRiskCovered: 1, weightedRiskUncovered: 0, totalTravelMinutes: 2, unreachableDestinationIds: [], unavailableResourceIds: [] },
};

const decision: Decision = {
  id: "decision-1",
  recommendationId: recommendation.id,
  action: "approve",
  note: "Proceed",
  actorId: "operator-1",
  assignments: recommendation.assignments,
  createdAt: "2026-07-17T12:00:00Z",
};

function renderDialog(props: Partial<React.ComponentProps<typeof DecisionDialog>> = {}) {
  return render(
    <AppProviders>
      <DecisionDialog
        recommendation={recommendation}
        freshness="current"
        planningDisabled={false}
        resources={["resource-1", "resource-2"]}
        destinations={["asset-1", "asset-2"]}
        {...props}
      />
    </AppProviders>,
  );
}

describe("DecisionDialog", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends an exact trimmed approve request without edited assignments", async () => {
    const createDecision = vi.spyOn(apiClient, "createDecision").mockResolvedValue(decision);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "  Proceed  ");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));

    await waitFor(() => expect(createDecision).toHaveBeenCalledOnce());
    expect(createDecision).toHaveBeenCalledWith(
      recommendation.id,
      { action: "approve", note: "Proceed" },
      expect.any(String),
    );
  });

  it("sends an exact trimmed reject request without edited assignments", async () => {
    const createDecision = vi.spyOn(apiClient, "createDecision").mockResolvedValue({
      ...decision,
      action: "reject",
      note: "Do not proceed",
    });
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Reject recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "  Do not proceed  ");
    await user.click(screen.getByRole("button", { name: "Submit reject decision" }));

    await waitFor(() => expect(createDecision).toHaveBeenCalledOnce());
    expect(createDecision).toHaveBeenCalledWith(
      recommendation.id,
      { action: "reject", note: "Do not proceed" },
      expect.any(String),
    );
  });

  it("validates notes and duplicate edit resources before posting", async () => {
    const createDecision = vi.spyOn(apiClient, "createDecision").mockResolvedValue(decision);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Edit recommendation" }));
    await user.click(screen.getByRole("button", { name: "Submit edit decision" }));
    expect(screen.getByText("A note is required.")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Decision note" }), {
      target: { value: "x".repeat(2001) },
    });
    await user.click(screen.getByRole("button", { name: "Submit edit decision" }));
    expect(screen.getByText("Note must be 2,000 characters or fewer.")).toBeVisible();
    await user.clear(screen.getByRole("textbox", { name: "Decision note" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Move resources");
    await user.click(screen.getByRole("button", { name: "Add assignment" }));
    const resourceSelects = screen.getAllByRole("combobox", { name: "Resource" });
    const destinationSelects = screen.getAllByRole("combobox", { name: "Destination" });
    await user.selectOptions(resourceSelects[1], "resource-1");
    await user.selectOptions(destinationSelects[1], "asset-2");
    await user.click(screen.getByRole("button", { name: "Submit edit decision" }));
    expect(screen.getByText("Each resource can have only one destination.")).toBeVisible();
    expect(createDecision).not.toHaveBeenCalled();
  });

  it("requires at least one edit assignment", async () => {
    const createDecision = vi.spyOn(apiClient, "createDecision").mockResolvedValue(decision);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Edit recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Move resources");
    await user.click(screen.getByRole("button", { name: "Remove assignment" }));
    await user.click(screen.getByRole("button", { name: "Submit edit decision" }));

    expect(screen.getByText("Add at least one assignment.")).toBeVisible();
    expect(createDecision).not.toHaveBeenCalled();
  });

  it.each([
    [{ freshness: "stale" as const }, [true, false, true]],
    [{ recommendation: { ...recommendation, solverStatus: "INFEASIBLE" } }, [true, false, true]],
    [{ planningDisabled: true }, [true, true, true]],
  ])("enforces the action policy", (props, disabled) => {
    renderDialog(props);
    expect(screen.getByRole("button", { name: "Approve recommendation" })).toHaveProperty("disabled", disabled[0]);
    expect(screen.getByRole("button", { name: "Reject recommendation" })).toHaveProperty("disabled", disabled[1]);
    expect(screen.getByRole("button", { name: "Edit recommendation" })).toHaveProperty("disabled", disabled[2]);
  });

  it("renders safe errors and latches stale decisions", async () => {
    const onStale = vi.fn();
    vi.spyOn(apiClient, "createDecision").mockRejectedValue(
      new ApiClientError("recommendation_stale", "untrusted server message", {}, 409),
    );
    const user = userEvent.setup();
    renderDialog({ onStale });

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Recommendation is stale. Regenerate before approving or editing.",
    );
    expect(onStale).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([
    [new ApiClientError("recommendation_not_actionable", "untrusted", {}, 409), "This solver result cannot be approved or edited."],
    [new ApiClientError("resource_already_assigned", "untrusted", {}, 409), "A selected resource was assigned elsewhere. Regenerate before dispatch."],
    [new ApiClientError("decision_invalid", "untrusted", {}, 422), "Decision could not be validated. Review the note and assignments."],
    [new ApiClientError("anything", "untrusted", {}, 422), "Decision could not be validated. Review the note and assignments."],
    [new ApiClientError("network_error", "untrusted", {}, 0), "Decision request failed. Retrying this unchanged decision is safe."],
    [new ApiClientError("unexpected", "untrusted", {}, 400), "Decision could not be completed."],
  ])("never exposes server error details", async (error, message) => {
    vi.spyOn(apiClient, "createDecision").mockRejectedValue(error);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("untrusted")).not.toBeInTheDocument();
  });

  it("makes already-decided responses terminal", async () => {
    vi.spyOn(apiClient, "createDecision").mockRejectedValue(
      new ApiClientError("recommendation_already_decided", "untrusted", {}, 409),
    );
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This recommendation has already been decided.",
    );
    expect(screen.getByRole("button", { name: "Approve recommendation" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject recommendation" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit recommendation" })).toBeDisabled();
  });

  it("prevents double posts and persists a terminal response", async () => {
    let settle!: (value: Decision) => void;
    const request = new Promise<Decision>((resolve) => { settle = resolve; });
    const createDecision = vi.spyOn(apiClient, "createDecision").mockReturnValue(request);
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    const submit = screen.getByRole("button", { name: "Submit approve decision" });
    await user.click(submit);
    await user.click(submit);
    expect(createDecision).toHaveBeenCalledOnce();
    settle(decision);

    expect(await screen.findByText("Decision recorded")).toBeVisible();
    expect(screen.getByText("operator-1")).toBeVisible();
    expect(screen.getByText("Proceed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve recommendation" })).toBeDisabled();
  });

  it("starts clean for a new recommendation ID", async () => {
    vi.spyOn(apiClient, "createDecision").mockResolvedValue(decision);
    const user = userEvent.setup();
    const view = renderDialog();
    await user.click(screen.getByRole("button", { name: "Approve recommendation" }));
    await user.type(screen.getByRole("textbox", { name: "Decision note" }), "Proceed");
    await user.click(screen.getByRole("button", { name: "Submit approve decision" }));
    await screen.findByText("Decision recorded");

    view.rerender(
      <AppProviders>
        <DecisionDialog
          key="recommendation-2"
          recommendation={{ ...recommendation, id: "recommendation-2" }}
          freshness="current"
          planningDisabled={false}
          resources={["resource-1"]}
          destinations={["asset-1"]}
        />
      </AppProviders>,
    );
    expect(screen.queryByText("Decision recorded")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve recommendation" })).toBeEnabled();
  });
});
