import type { Recommendation, ScenarioVersion } from "../api/types";

/**
 * The monitor speaks the same plain language as the decision exercise: the
 * solver's vocabulary stays in the Evidence tab, and every other surface says
 * what happened in words an operator would use.
 */

export type PlanTone = "good" | "caution" | "alert" | "neutral";

const SOLVER_STATUS: Record<string, { plain: string; tone: PlanTone }> = {
  OPTIMAL: {
    plain: "This is the best allocation the planner could find.",
    tone: "good",
  },
  FEASIBLE: {
    plain:
      "This allocation works, but the planner ran out of time before it could prove nothing better exists.",
    tone: "caution",
  },
  INFEASIBLE: {
    plain: "No allocation satisfies these assumptions.",
    tone: "alert",
  },
  UNBOUNDED: {
    plain: "The problem as posed has no bounded answer.",
    tone: "alert",
  },
  UNKNOWN: {
    plain: "The planner could not determine an allocation.",
    tone: "alert",
  },
};

export function isActionable(recommendation: Recommendation): boolean {
  return (
    recommendation.solverStatus === "OPTIMAL" ||
    recommendation.solverStatus === "FEASIBLE"
  );
}

export function solverPlain(recommendation: Recommendation): {
  plain: string;
  tone: PlanTone;
} {
  return (
    SOLVER_STATUS[recommendation.solverStatus] ?? {
      plain: `The planner returned ${recommendation.solverStatus.toLowerCase()}.`,
      tone: "alert" as const,
    }
  );
}

/** "Covers 3 of 4 destinations" — the one line the dock and drawer both lead with. */
export function coverageLine(recommendation: Recommendation): string {
  const covered = recommendation.assignments.length;
  const uncovered = recommendation.uncoveredDestinationIds.length;
  const total = covered + uncovered;
  if (total === 0) {
    return "No destinations to cover";
  }
  if (uncovered === 0) {
    return total === 1
      ? "Covers the only destination"
      : `Covers all ${total} destinations`;
  }
  return `Covers ${covered} of ${total} ${
    total === 1 ? "destination" : "destinations"
  }`;
}

export function labelFor(
  labels: Readonly<Record<string, string>>,
  id: string,
): string {
  return labels[id] ?? humanize(id);
}

export function humanize(value: string): string {
  const spaced = value.replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function formatMinutes(value: number): string {
  if (value <= 0) {
    return "already on scene";
  }
  return value < 1 ? "under a minute away" : `${Math.round(value)} min away`;
}

export function formatDistance(meters: number): string {
  if (meters <= 0) {
    return "no travel";
  }
  return meters < 1000
    ? `${Math.round(meters)} m`
    : `${(meters / 1000).toFixed(1)} km`;
}

/** Describes what a scenario version changed, without naming raw edge hashes. */
export function versionChanges(
  version: ScenarioVersion,
  roadNames: ReadonlyMap<string, string>,
  resourceLabels: Readonly<Record<string, string>>,
): string[] {
  const changes: string[] = [];
  for (const { edgeId } of version.roadClosures) {
    changes.push(`${roadNames.get(edgeId) ?? "A road segment"} is closed`);
  }
  for (const override of version.resourceOverrides) {
    changes.push(
      `${labelFor(resourceLabels, override.resourceId)} is ${
        override.available ? "available" : "out of service"
      }`,
    );
  }
  for (const weather of version.weatherOverrides) {
    changes.push(
      `Wind assumed at ${(weather.windSpeedMps * 2.23694).toFixed(0)} mph from ${compass(
        weather.windDirectionDegrees,
      )}`,
    );
  }
  return changes;
}

const COMPASS = [
  "the north",
  "the north-east",
  "the east",
  "the south-east",
  "the south",
  "the south-west",
  "the west",
  "the north-west",
];

export function compass(degrees: number): string {
  const normalized = ((degrees % 360) + 360) % 360;
  return COMPASS[Math.round(normalized / 45) % 8];
}
