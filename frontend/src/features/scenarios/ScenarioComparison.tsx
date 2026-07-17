import type { RecommendationOutcome } from "../../api/types";

export type ScenarioComparisonProps = {
  baseline: RecommendationOutcome;
  scenario: RecommendationOutcome;
};

type ComparisonRow = {
  name: string;
  baseline: number | null;
  scenario: number | null;
  higherIsBetter: boolean;
};

const numberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 6,
});

export function ScenarioComparison({
  baseline,
  scenario,
}: ScenarioComparisonProps) {
  const metrics: ComparisonRow[] = [
    {
      name: "Risk score",
      baseline: baseline.scenarioRisk.score,
      scenario: scenario.scenarioRisk.score,
      higherIsBetter: false,
    },
    {
      name: "Weighted risk covered",
      baseline: baseline.weightedRiskCovered,
      scenario: scenario.weightedRiskCovered,
      higherIsBetter: true,
    },
    {
      name: "Weighted risk uncovered",
      baseline: baseline.weightedRiskUncovered,
      scenario: scenario.weightedRiskUncovered,
      higherIsBetter: false,
    },
    {
      name: "Total travel minutes",
      baseline: baseline.totalTravelMinutes,
      scenario: scenario.totalTravelMinutes,
      higherIsBetter: false,
    },
    {
      name: "Unreachable destinations",
      baseline: baseline.unreachableDestinationIds.length,
      scenario: scenario.unreachableDestinationIds.length,
      higherIsBetter: false,
    },
    {
      name: "Unavailable resources",
      baseline: baseline.unavailableResourceIds.length,
      scenario: scenario.unavailableResourceIds.length,
      higherIsBetter: false,
    },
  ];
  const factors = factorRows(baseline, scenario);

  return (
    <section aria-label="Scenario outcome comparison">
      <h2>Scenario outcome comparison</h2>
      <ComparisonTable label="Outcome metrics comparison" rows={metrics} />
      <ComparisonTable
        label="Risk factor contribution comparison"
        rows={factors}
      />
      <IdentifierDetails
        label="Unreachable destination details"
        itemLabel="unreachable destinations"
        baseline={baseline.unreachableDestinationIds}
        scenario={scenario.unreachableDestinationIds}
      />
      <IdentifierDetails
        label="Unavailable resource details"
        itemLabel="unavailable resources"
        baseline={baseline.unavailableResourceIds}
        scenario={scenario.unavailableResourceIds}
      />
    </section>
  );
}

function ComparisonTable({
  label,
  rows,
}: {
  label: string;
  rows: readonly ComparisonRow[];
}) {
  return (
    <table aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Metric</th>
          <th scope="col">Baseline</th>
          <th scope="col">Scenario</th>
          <th scope="col">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const baselineForDelta = row.baseline ?? 0;
          const scenarioForDelta = row.scenario ?? 0;
          const delta = scenarioForDelta - baselineForDelta;
          const change = changePresentation(delta, row.higherIsBetter);
          return (
            <tr key={row.name}>
              <th scope="row">{row.name}</th>
              <td>{absoluteValue(row.baseline)}</td>
              <td>{absoluteValue(row.scenario)}</td>
              <td>
                <span
                  className={`scenario-comparison__change scenario-comparison__change--${change.tone}`}
                >
                  {signedValue(delta)} {change.label}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function IdentifierDetails({
  label,
  itemLabel,
  baseline,
  scenario,
}: {
  label: string;
  itemLabel: string;
  baseline: readonly string[];
  scenario: readonly string[];
}) {
  return (
    <section aria-label={label}>
      <h3>{label}</h3>
      <h4>Baseline</h4>
      <IdentifierList prefix="Baseline" label={itemLabel} ids={baseline} />
      <h4>Scenario</h4>
      <IdentifierList prefix="Scenario" label={itemLabel} ids={scenario} />
    </section>
  );
}

function IdentifierList({
  prefix,
  label,
  ids,
}: {
  prefix: string;
  label: string;
  ids: readonly string[];
}) {
  if (ids.length === 0) {
    return <p>{prefix}: none.</p>;
  }
  return (
    <ul aria-label={`${prefix} ${label}`}>
      {[...ids].sort().map((id) => (
        <li key={id}>{id}</li>
      ))}
    </ul>
  );
}

function factorRows(
  baseline: RecommendationOutcome,
  scenario: RecommendationOutcome,
): ComparisonRow[] {
  const baselineFactors = new Map(
    baseline.scenarioRisk.contributions.map(({ name, contribution }) => [
      name,
      contribution,
    ]),
  );
  const scenarioFactors = new Map(
    scenario.scenarioRisk.contributions.map(({ name, contribution }) => [
      name,
      contribution,
    ]),
  );
  return [...new Set([...baselineFactors.keys(), ...scenarioFactors.keys()])]
    .sort()
    .map((name) => ({
      name,
      baseline: baselineFactors.get(name) ?? null,
      scenario: scenarioFactors.get(name) ?? null,
      higherIsBetter: false,
    }));
}

function absoluteValue(value: number | null): string {
  return value === null ? "Not available" : numberFormat.format(value);
}

function signedValue(value: number): string {
  if (value === 0) {
    return "0";
  }
  return `${value > 0 ? "+" : "-"}${numberFormat.format(Math.abs(value))}`;
}

function changePresentation(
  delta: number,
  higherIsBetter: boolean,
): { tone: "good" | "bad" | "neutral"; label: string } {
  if (delta === 0) {
    return { tone: "neutral", label: "No change" };
  }
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  return improved
    ? { tone: "good", label: "Improved" }
    : { tone: "bad", label: "Worsened" };
}
