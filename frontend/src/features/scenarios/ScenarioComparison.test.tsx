import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecommendationOutcome } from "../../api/types";
import { ScenarioComparison } from "./ScenarioComparison";

const baseline: RecommendationOutcome = {
  scenarioRisk: {
    score: 20,
    algorithmVersion: "risk-v1",
    contributions: [
      factor("wind", 10),
      factor("population", 5),
      factor("stable", 1),
    ],
  },
  weightedRiskCovered: 30,
  weightedRiskUncovered: 10,
  totalTravelMinutes: 8,
  unreachableDestinationIds: ["town-2", "town-1"],
  unavailableResourceIds: [],
};

const scenario: RecommendationOutcome = {
  scenarioRisk: {
    score: 15,
    algorithmVersion: "risk-v1",
    contributions: [
      factor("terrain", 2),
      factor("wind", 7),
      factor("stable", 1),
    ],
  },
  weightedRiskCovered: 35,
  weightedRiskUncovered: 20,
  totalTravelMinutes: 8,
  unreachableDestinationIds: [],
  unavailableResourceIds: ["crew-9", "crew-4"],
};

describe("ScenarioComparison", () => {
  it("renders absolute values, signed deltas, and visible change meaning", () => {
    render(<ScenarioComparison baseline={baseline} scenario={scenario} />);

    expectMetric("Risk score", "20", "15", "-5 Improved", "good");
    expectMetric(
      "Weighted risk covered",
      "30",
      "35",
      "+5 Improved",
      "good",
    );
    expectMetric(
      "Weighted risk uncovered",
      "10",
      "20",
      "+10 Worsened",
      "bad",
    );
    expectMetric(
      "Total travel minutes",
      "8",
      "8",
      "0 No change",
      "neutral",
    );
    expectMetric(
      "Unreachable destinations",
      "2",
      "0",
      "-2 Improved",
      "good",
    );
    expectMetric(
      "Unavailable resources",
      "0",
      "2",
      "+2 Worsened",
      "bad",
    );
  });

  it("aligns risk factors by name and treats absent factors as zero for deltas", () => {
    render(<ScenarioComparison baseline={baseline} scenario={scenario} />);

    const table = screen.getByRole("table", {
      name: "Risk factor contribution comparison",
    });
    const factorRows = within(table).getAllByRole("row").slice(1);
    expect(
      factorRows.map(
        (row) => within(row).getByRole("rowheader").textContent,
      ),
    ).toEqual(["population", "stable", "terrain", "wind"]);
    expectFactor("population", "5", "Not available", "-5 Improved", "good");
    expectFactor("stable", "1", "1", "0 No change", "neutral");
    expectFactor("terrain", "Not available", "2", "+2 Worsened", "bad");
    expectFactor("wind", "10", "7", "-3 Improved", "good");
  });

  it("renders sorted identifiers and explicit empty states", () => {
    render(<ScenarioComparison baseline={baseline} scenario={scenario} />);

    const destinations = screen.getByRole("region", {
      name: "Unreachable destination details",
    });
    expect(
      within(destinations)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["town-1", "town-2"]);
    expect(within(destinations).getByText("Scenario: none.")).toBeVisible();

    const resources = screen.getByRole("region", {
      name: "Unavailable resource details",
    });
    expect(within(resources).getByText("Baseline: none.")).toBeVisible();
    expect(
      within(resources)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["crew-4", "crew-9"]);
  });

  it("preserves backend six-decimal precision in absolutes and deltas", () => {
    render(
      <ScenarioComparison
        baseline={{
          ...baseline,
          scenarioRisk: { ...baseline.scenarioRisk, score: 1 },
        }}
        scenario={{
          ...scenario,
          scenarioRisk: { ...scenario.scenarioRisk, score: 1.000001 },
        }}
      />,
    );

    expectMetric(
      "Risk score",
      "1",
      "1.000001",
      "+0.000001 Worsened",
      "bad",
    );
  });
});

function factor(name: string, contribution: number) {
  return {
    name,
    rawValue: contribution,
    normalizedValue: contribution,
    weight: 1,
    contribution,
  };
}

function expectMetric(
  name: string,
  baselineValue: string,
  scenarioValue: string,
  change: string,
  tone: "good" | "bad" | "neutral",
): void {
  const table = screen.getByRole("table", { name: "Outcome metrics comparison" });
  expectRow(table, name, baselineValue, scenarioValue, change, tone);
}

function expectFactor(
  name: string,
  baselineValue: string,
  scenarioValue: string,
  change: string,
  tone: "good" | "bad" | "neutral",
): void {
  const table = screen.getByRole("table", {
    name: "Risk factor contribution comparison",
  });
  expectRow(table, name, baselineValue, scenarioValue, change, tone);
}

function expectRow(
  table: HTMLElement,
  name: string,
  baselineValue: string,
  scenarioValue: string,
  change: string,
  tone: "good" | "bad" | "neutral",
): void {
  const row = within(table).getByRole("row", { name: new RegExp(`^${name} `) });
  const cells = within(row).getAllByRole("cell");
  expect(cells[0]).toHaveTextContent(new RegExp(`^${baselineValue}$`));
  expect(cells[1]).toHaveTextContent(new RegExp(`^${scenarioValue}$`));
  expect(cells[2]).toHaveTextContent(
    new RegExp(`^${escapeRegExp(change)}$`),
  );
  expect(cells[2].firstElementChild).toHaveClass(
    `scenario-comparison__change--${tone}`,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
