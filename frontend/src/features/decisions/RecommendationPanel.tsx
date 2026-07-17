import type { JsonValue, Recommendation } from "../../api/types";

export type RecommendationPanelProps = {
  recommendation: Recommendation;
  versionLabel: string;
};

const numberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 6,
});

export function RecommendationPanel({
  recommendation,
  versionLabel,
}: RecommendationPanelProps) {
  const actionable =
    recommendation.solverStatus === "OPTIMAL" ||
    recommendation.solverStatus === "FEASIBLE";
  const bindingConstraints = stringArray(
    recommendation.explanation.binding_constraints,
  );
  const unassignedResources = stringArray(
    recommendation.explanation.unassigned_resource_ids,
  );

  return (
    <section className="recommendation-panel" aria-label="Recommendation result">
      <header>
        <h4>Recommendation</h4>
        <p className="snapshot-context">{versionLabel}</p>
      </header>
      <p
        className={
          actionable
            ? "recommendation-panel__status recommendation-panel__status--actionable"
            : "recommendation-panel__status recommendation-panel__status--blocked"
        }
        role="status"
      >
        <strong>{recommendation.solverStatus}</strong> — {actionable
          ? "Actionable recommendation"
          : "Non-actionable solver result"}
      </p>

      <h5>Assignments</h5>
      {recommendation.assignments.length === 0 ? (
        <p className="decision-workspace__empty">No assignments were returned.</p>
      ) : (
        <ul
          className="recommendation-panel__assignments"
          aria-label="Recommendation assignments"
        >
          {recommendation.assignments.map((assignment) => (
            <li key={`${assignment.resourceId}:${assignment.destinationId}`}>
              <dl>
                <dt>Resource</dt>
                <dd>{assignment.resourceId}</dd>
                <dt>Destination</dt>
                <dd>{assignment.destinationId}</dd>
                <dt>Route status</dt>
                <dd>{assignment.route.status}</dd>
                <dt>Edge IDs</dt>
                <dd>
                  {assignment.route.edgeIds.length > 0
                    ? assignment.route.edgeIds.join(", ")
                    : "None"}
                </dd>
                <dt>Distance</dt>
                <dd>{formatNumber(assignment.route.distanceMeters)} m</dd>
                <dt>Route travel</dt>
                <dd>{formatNumber(assignment.route.travelMinutes)} min</dd>
                <dt>Assignment travel</dt>
                <dd>{formatNumber(assignment.travelMinutes)} min</dd>
                <dt>Capacity</dt>
                <dd>{formatNumber(assignment.capacity)}</dd>
              </dl>
            </li>
          ))}
        </ul>
      )}

      <h5>Uncovered destinations</h5>
      {recommendation.uncoveredDestinationIds.length === 0 ? (
        <p className="decision-workspace__empty">
          No destinations are uncovered.
        </p>
      ) : (
        <ul aria-label="Uncovered destinations">
          {recommendation.uncoveredDestinationIds.map((destinationId) => (
            <li key={destinationId}>{destinationId}</li>
          ))}
        </ul>
      )}

      <section aria-label="Solver evidence">
        <h5>Solver evidence</h5>
        <dl className="recommendation-panel__evidence">
          <dt>Runtime</dt>
          <dd>{formatNumber(recommendation.runtimeMilliseconds)} ms</dd>
          <dt>Travel cost</dt>
          <dd>{formatNumber(recommendation.objectiveComponents.travelCost)}</dd>
          <dt>Uncovered risk penalty</dt>
          <dd>
            {formatNumber(
              recommendation.objectiveComponents.uncoveredRiskPenalty,
            )}
          </dd>
          <dt>Objective value</dt>
          <dd>
            {formatNumber(recommendation.objectiveComponents.objectiveValue)}
          </dd>
          <dt>Graph</dt>
          <dd>{recommendation.graphVersion}</dd>
          <dt>Risk</dt>
          <dd>{recommendation.riskVersion}</dd>
          <dt>Allocation</dt>
          <dd>{recommendation.algorithmVersion}</dd>
          <dt>Input</dt>
          <dd>{recommendation.inputVersion}</dd>
        </dl>
      </section>

      <h5>Source versions</h5>
      <pre className="decision-workspace__evidence">
        {JSON.stringify(recommendation.sourceVersions, null, 2)}
      </pre>

      <section aria-label="Constraint diagnostics">
        <h5>Constraint diagnostics</h5>
        {bindingConstraints === null && unassignedResources === null ? (
          <p className="decision-workspace__empty">
            No known constraint diagnostics are available.
          </p>
        ) : (
          <dl className="recommendation-panel__diagnostics">
            {bindingConstraints !== null ? (
              <>
                <dt>Binding constraints</dt>
                <dd>{listText(bindingConstraints)}</dd>
              </>
            ) : null}
            {unassignedResources !== null ? (
              <>
                <dt>Unassigned resources</dt>
                <dd>{listText(unassignedResources)}</dd>
              </>
            ) : null}
          </dl>
        )}
      </section>

      <details>
        <summary>Full solver explanation</summary>
        <pre className="decision-workspace__evidence">
          {JSON.stringify(recommendation.explanation, null, 2)}
        </pre>
      </details>
    </section>
  );
}

function stringArray(value: JsonValue | undefined): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : null;
}

function listText(values: readonly string[]): string {
  return values.length > 0 ? values.join(", ") : "None reported";
}

function formatNumber(value: number): string {
  return numberFormat.format(value);
}
