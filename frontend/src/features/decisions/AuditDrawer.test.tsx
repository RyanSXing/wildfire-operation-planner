import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiClient } from "../../api/client";
import type { AuditEvent } from "../../api/types";
import { AppProviders } from "../../app/AppProviders";
import { AuditDrawer } from "./AuditDrawer";

const event: AuditEvent = {
  id: "event-1",
  decisionActionId: "decision-1",
  actorId: "operator-1",
  eventType: "decision.recorded",
  aggregateType: "recommendation",
  aggregateId: "recommendation-1",
  scenarioVersionId: "version-1",
  incidentSnapshotId: "snapshot-1",
  recommendationId: "recommendation-1",
  algorithms: { allocator: "allocation-v1" },
  beforeState: { proposedPairs: [{ resourceId: "engine-1" }] },
  afterState: { action: "approve", note: "Proceed", decisionId: "decision-1", finalPairs: [{ resourceId: "engine-1", destinationId: "asset-1" }] },
  inputs: { sourceVersions: { fire: "firms-v1" }, stalenessToken: "fresh-1" },
  note: "Proceed",
  occurredAt: "2026-07-17T12:00:00Z",
};

function renderDrawer(recommendationId = "recommendation-1") {
  return render(
    <AppProviders>
      <AuditDrawer key={recommendationId} recommendationId={recommendationId} />
    </AppProviders>,
  );
}

describe("AuditDrawer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not load until opened, then preserves server order and complete list metadata", async () => {
    const listAuditEvents = vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({
      items: [event, { ...event, id: "event-2", actorId: "operator-2", eventType: "decision.edited" }],
    });
    const user = userEvent.setup();
    renderDrawer();

    expect(listAuditEvents).not.toHaveBeenCalled();
    await user.click(screen.getByText("Audit history"));
    await waitFor(() => expect(listAuditEvents).toHaveBeenCalledWith("recommendation-1", expect.any(AbortSignal)));

    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("operator-1"),
      expect.stringContaining("operator-2"),
    ]);
    expect(screen.getByText("decision.recorded")).toBeVisible();
    expect(screen.getAllByText("version-1")[0]).toBeVisible();
    expect(screen.getAllByText("recommendation-1")[0]).toBeVisible();
    expect(screen.getAllByText("snapshot-1")[0]).toBeVisible();
    expect(screen.getAllByText("Proceed")[0]).toBeVisible();
    expect(screen.getAllByText(/allocation-v1/)[0]).toBeVisible();
    expect(screen.getAllByText(/fire/)[0]).toBeVisible();
    expect(screen.getAllByText(/proposedPairs/)[0]).toBeVisible();
    expect(screen.getAllByText(/"action"/)[0]).toBeVisible();
    expect(screen.getAllByRole("time")[0]).toHaveAttribute("dateTime", event.occurredAt);
  });

  it("loads detail only after selection and keeps the list through a detail failure and retry", async () => {
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items: [event] });
    const getAuditEvent = vi
      .spyOn(apiClient, "getAuditEvent")
      .mockRejectedValueOnce(new ApiClientError("hidden", "untrusted", {}, 500))
      .mockResolvedValue(event);
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await screen.findByText("operator-1");
    expect(getAuditEvent).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "View details for event-1" }));
    await screen.findByText("Audit details could not be loaded.");
    expect(screen.getByText("operator-1")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry audit details" }));
    await screen.findByText("Observed inputs");

    expect(screen.getByText("Simulated context")).toBeVisible();
    expect(screen.getByText("Calculated evidence")).toBeVisible();
    expect(screen.getByText("Operator-entered decision")).toBeVisible();
    expect(screen.getByText("This identifies the immutable simulated scenario.")).toBeVisible();
    expect(screen.getByText("fresh-1")).toBeVisible();
    expect(screen.getByText("decision-1")).toBeVisible();
    expect(screen.getByText("Final assignments")).toBeVisible();
    expect(screen.getAllByText(/"finalPairs"/)[0]).toBeVisible();
    expect(screen.getByText(/"sourceVersions"/)).toBeInTheDocument();
    expect(screen.getAllByText(/"proposedPairs"/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/"decisionId"/)[0]).toBeInTheDocument();
  });

  it("renders safe list states and clears selection when recommendation scope changes", async () => {
    const listAuditEvents = vi
      .spyOn(apiClient, "listAuditEvents")
      .mockRejectedValueOnce(new ApiClientError("hidden", "untrusted", {}, 500))
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [event] });
    const user = userEvent.setup();
    const view = renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await screen.findByText("Audit history could not be loaded.");
    expect(screen.queryByText("untrusted")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry audit history" }));
    await screen.findByText("No audit events are recorded for this recommendation.");

    view.rerender(
      <AppProviders>
        <AuditDrawer key="recommendation-2" recommendationId="recommendation-2" />
      </AppProviders>,
    );
    await user.click(screen.getByText("Audit history"));
    await waitFor(() => expect(listAuditEvents).toHaveBeenLastCalledWith("recommendation-2", expect.any(AbortSignal)));
    expect(screen.queryByText("Observed inputs")).not.toBeInTheDocument();
  });

  it("marks missing provenance values as not recorded while retaining their full JSON", async () => {
    const incomplete = { ...event, algorithms: {}, beforeState: {}, afterState: {}, inputs: {}, note: "" };
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items: [incomplete] });
    vi.spyOn(apiClient, "getAuditEvent").mockResolvedValue(incomplete);
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await user.click(await screen.findByRole("button", { name: "View details for event-1" }));
    await screen.findByText("Observed inputs");

    expect(screen.getAllByText("Not recorded")).toHaveLength(10);
    await user.click(screen.getByText("Complete audit JSON"));
    expect(screen.getByText(/"beforeState"/)).toBeVisible();
    expect(screen.getByText(/"afterState"/)).toBeVisible();
  });

  it("fetches and shows details for the selected second event", async () => {
    const second = {
      ...event,
      id: "event-2",
      decisionActionId: "decision-2",
      actorId: "operator-2",
      afterState: { action: "edit", note: "Move", decisionId: "decision-2", finalPairs: [{ resourceId: "engine-2", destinationId: "asset-2" }] },
    };
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items: [event, second] });
    const getAuditEvent = vi.spyOn(apiClient, "getAuditEvent").mockResolvedValue(second);
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await user.click(await screen.findByRole("button", { name: "View details for event-2" }));
    await waitFor(() => expect(getAuditEvent).toHaveBeenCalledWith("event-2", expect.any(AbortSignal)));
    expect(await screen.findByText("decision-2")).toBeVisible();
    expect(screen.getAllByText(/engine-2/)[0]).toBeVisible();
  });

  it("records empty final pairs but rejects malformed final-pair provenance", async () => {
    const malformed = { ...event, afterState: { ...event.afterState, finalPairs: "not-an-array" } };
    const empty = { ...event, id: "event-2", afterState: { ...event.afterState, finalPairs: [] } };
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items: [malformed, empty] });
    vi.spyOn(apiClient, "getAuditEvent").mockImplementation((eventId) =>
      Promise.resolve(eventId === malformed.id ? malformed : empty),
    );
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await user.click(await screen.findByRole("button", { name: "View details for event-1" }));
    await screen.findByText("Final assignments");
    expect(screen.getByText("Final assignments").nextElementSibling).toHaveTextContent("Not recorded");
    await user.click(screen.getByText("Complete audit JSON"));
    expect(screen.getByText("Complete audit JSON").parentElement).toHaveTextContent("not-an-array");

    await user.click(screen.getByRole("button", { name: "View details for event-2" }));
    await waitFor(() => expect(screen.getByText("Final assignments").nextElementSibling).toHaveTextContent("[]"));
  });
});
