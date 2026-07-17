import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BEAR_ID, REDWOOD_ID, incidentListResponse } from "../../test/fixtures";
import { IncidentQueue } from "./IncidentQueue";

describe("IncidentQueue", () => {
  it("preserves response order and exposes complete selectable incident context", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <IncidentQueue
        incidents={incidentListResponse.items}
        selectedIncidentId={REDWOOD_ID}
        onSelect={onSelect}
      />,
    );

    const rows = screen.getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Redwood Creek")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Bear Ridge")).toBeInTheDocument();
    expect(within(rows[0]).getByText("82")).toBeInTheDocument();
    expect(within(rows[1]).getByText("61")).toBeInTheDocument();
    expect(within(rows[0]).getByText("3 exposed")).toBeInTheDocument();
    expect(within(rows[1]).getByText("1 exposed")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Fresh")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Stale")).toBeInTheDocument();
    expect(within(rows[0]).getByText("●")).toHaveAttribute("aria-hidden", "true");
    expect(rows[0]).toHaveAttribute("aria-pressed", "true");
    expect(rows[1]).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText(/resource locations shown on the map are simulated/i),
    ).toBeInTheDocument();

    await user.click(rows[1]);
    expect(onSelect).toHaveBeenCalledWith(BEAR_ID);
  });
});
