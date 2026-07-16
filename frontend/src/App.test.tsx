import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("identifies the product as a simulation", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "WildfireOps" })).toBeInTheDocument();
    expect(screen.getByText(/portfolio simulation/i)).toBeInTheDocument();
  });
});
