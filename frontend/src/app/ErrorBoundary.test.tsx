import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function BrokenPanel(): never {
  throw new Error("render-secret-that-must-not-be-shown");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("leaves healthy children unchanged", () => {
    render(
      <ErrorBoundary>
        <p>Healthy operator surface</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("Healthy operator surface")).toBeVisible();
  });

  it("replaces render failures with a sanitized safety-preserving fallback", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary>
        <BrokenPanel />
      </ErrorBoundary>,
    );

    const fallback = screen.getByRole("alert", {
      name: "Interface unavailable",
    });
    expect(fallback).toHaveTextContent(
      "The operator interface could not be displayed. Reload the page to try again.",
    );
    expect(fallback).toHaveTextContent(
      "Portfolio simulation only. Do not use for emergency or life-safety decisions.",
    );
    expect(fallback).not.toHaveTextContent(/render-secret/i);
  });
});
