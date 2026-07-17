import { act, render, screen, waitFor, within } from "@testing-library/react";
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
  beforeState: { proposedPairs: [{ resourceId: "engine-1", destinationId: "asset-1" }] },
  afterState: { action: "approve", note: "Proceed", decisionId: "decision-1", finalPairs: [{ resourceId: "engine-1", destinationId: "asset-1" }] },
  inputs: { sourceVersions: { fire: "firms-v1" }, stalenessToken: "fresh-1" },
  note: "Proceed",
  occurredAt: "2026-07-17T12:00:00Z",
};

function renderDrawer(recommendationId = "recommendation-1") {
  return render(
    <AppProviders>
      <AuditDrawer recommendationId={recommendationId} />
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

  it("keeps event B visible when event A settles late", async () => {
    const second = {
      ...event,
      id: "event-2",
      decisionActionId: "decision-2",
      actorId: "operator-2",
      afterState: { action: "edit", note: "Move", decisionId: "decision-2", finalPairs: [{ resourceId: "engine-2", destinationId: "asset-2" }] },
    };
    const firstDetail = deferred<AuditEvent>();
    const secondDetail = deferred<AuditEvent>();
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items: [event, second] });
    const getAuditEvent = vi.spyOn(apiClient, "getAuditEvent").mockImplementation(
      (eventId) => eventId === event.id ? firstDetail.promise : secondDetail.promise,
    );
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await user.click(await screen.findByRole("button", { name: "View details for event-1" }));
    await waitFor(() => expect(getAuditEvent).toHaveBeenCalledWith("event-1", expect.any(AbortSignal)));
    await user.click(await screen.findByRole("button", { name: "View details for event-2" }));
    await waitFor(() => expect(getAuditEvent).toHaveBeenCalledWith("event-2", expect.any(AbortSignal)));
    await act(async () => secondDetail.resolve(second));
    const provenance = await screen.findByLabelText("Audit provenance");
    expect(within(provenance).getByText("decision-2")).toBeVisible();

    await act(async () => firstDetail.resolve(event));
    expect(within(provenance).getByText("decision-2")).toBeVisible();
    expect(within(provenance).queryByText("decision-1")).not.toBeInTheDocument();
  });

  it("isolates a late recommendation-A detail from recommendation B without a keyed remount", async () => {
    const next = {
      ...event,
      id: "event-2",
      recommendationId: "recommendation-2",
      aggregateId: "recommendation-2",
      decisionActionId: "decision-2",
      actorId: "operator-2",
      afterState: { ...event.afterState, decisionId: "decision-2" },
    };
    const firstDetail = deferred<AuditEvent>();
    vi.spyOn(apiClient, "listAuditEvents").mockImplementation((recommendationId) =>
      Promise.resolve({ items: recommendationId === "recommendation-1" ? [event] : [next] }),
    );
    const getAuditEvent = vi.spyOn(apiClient, "getAuditEvent").mockImplementation((eventId) =>
      eventId === event.id ? firstDetail.promise : Promise.resolve(next),
    );
    const user = userEvent.setup();
    const view = renderDrawer();

    await user.click(screen.getByText("Audit history"));
    await user.click(await screen.findByRole("button", { name: "View details for event-1" }));
    await waitFor(() => expect(getAuditEvent).toHaveBeenCalledWith("event-1", expect.any(AbortSignal)));
    view.rerender(
      <AppProviders>
        <AuditDrawer recommendationId="recommendation-2" />
      </AppProviders>,
    );
    await user.click(await screen.findByRole("button", { name: "View details for event-2" }));
    expect(await screen.findByText("decision-2")).toBeVisible();

    await act(async () => firstDetail.reject(new ApiClientError("hidden", "untrusted", {}, 500)));
    expect(screen.getByText("decision-2")).toBeVisible();
    expect(screen.queryByText("Audit details could not be loaded.")).not.toBeInTheDocument();
    expect(getAuditEvent).toHaveBeenCalledTimes(2);
  });

  it("records only complete provenance pair arrays", async () => {
    const items: AuditEvent[] = [
      event,
      { ...event, id: "event-2", beforeState: {}, afterState: {} },
      { ...event, id: "event-3", beforeState: { proposedPairs: [] }, afterState: { ...event.afterState, finalPairs: [] } },
      {
        ...event,
        id: "event-4",
        beforeState: { proposedPairs: [null] },
        afterState: { ...event.afterState, finalPairs: [{ resourceId: "engine-1" }] },
      },
    ];
    vi.spyOn(apiClient, "listAuditEvents").mockResolvedValue({ items });
    vi.spyOn(apiClient, "getAuditEvent").mockImplementation((eventId) =>
      Promise.resolve(items.find(({ id }) => id === eventId)!),
    );
    const user = userEvent.setup();
    renderDrawer();
    await user.click(screen.getByText("Audit history"));

    await user.click(await screen.findByRole("button", { name: "View details for event-1" }));
    await screen.findByText("Proposed assignments");
    expect(provenanceValue("Proposed assignments")).toHaveTextContent("engine-1");
    expect(provenanceValue("Final assignments")).toHaveTextContent("asset-1");

    await user.click(screen.getByRole("button", { name: "View details for event-2" }));
    await waitFor(() => expect(provenanceValue("Proposed assignments")).toHaveTextContent("Not recorded"));
    expect(provenanceValue("Final assignments")).toHaveTextContent("Not recorded");

    await user.click(screen.getByRole("button", { name: "View details for event-3" }));
    await waitFor(() => expect(provenanceValue("Proposed assignments")).toHaveTextContent("[]"));
    expect(provenanceValue("Final assignments")).toHaveTextContent("[]");

    await user.click(screen.getByRole("button", { name: "View details for event-4" }));
    await waitFor(() => expect(provenanceValue("Proposed assignments")).toHaveTextContent("Not recorded"));
    expect(provenanceValue("Final assignments")).toHaveTextContent("Not recorded");
    await user.click(screen.getByText("Complete audit JSON"));
    expect(screen.getByText("Complete audit JSON").parentElement).toHaveTextContent('"proposedPairs": [ null ]');
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function provenanceValue(label: string): Element {
  const term = within(screen.getByLabelText("Audit provenance")).getByText(label);
  if (!term.nextElementSibling) {
    throw new Error(`${label} has no value`);
  }
  return term.nextElementSibling;
}
