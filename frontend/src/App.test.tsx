import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const shellHarness = vi.hoisted(() => ({
  clients: new Set<object>(),
  shouldThrow: false,
}));

vi.mock("./app/AppShell", async () => {
  const { useQueryClient } = await import("@tanstack/react-query");

  return {
    AppShell() {
      shellHarness.clients.add(useQueryClient());
      if (shellHarness.shouldThrow) {
        throw new Error("app-shell-render-secret");
      }
      return <p>Integrated operator shell</p>;
    },
  };
});

import App from "./App";

beforeEach(() => {
  shellHarness.clients.clear();
  shellHarness.shouldThrow = false;
  // The live monitor now lives at /monitor; "/" renders the decision exercise.
  window.history.replaceState({}, "", "/monitor");
});

describe("App", () => {
  it("keeps one QueryClient for an app mount and creates a new one for a new mount", () => {
    const firstMount = render(<App />);

    expect(screen.getByText("Integrated operator shell")).toBeVisible();
    expect(shellHarness.clients).toHaveLength(1);

    firstMount.rerender(<App />);
    expect(shellHarness.clients).toHaveLength(1);

    firstMount.unmount();
    render(<App />);
    expect(shellHarness.clients).toHaveLength(2);
  });

  it("places the render-failure boundary outside the provided shell", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    shellHarness.shouldThrow = true;

    render(<App />);

    expect(
      screen.getByRole("alert", { name: "Interface unavailable" }),
    ).toBeVisible();
  });
});
