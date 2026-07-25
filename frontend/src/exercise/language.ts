import type {
  ExerciseAsset,
  ExerciseDisruption,
  ExerciseIncident,
  ExerciseObjective,
  ExerciseResource,
  ExerciseTask,
  PlanChange,
} from "../api/exerciseTypes";

/**
 * The API speaks in stable identifiers: `exercise-bus-1`, `evacuate-chico`,
 * `route.closed`. Reviewers should never have to. Everything in this module
 * turns a contract value into a sentence a duty officer could read aloud, and
 * nothing here invents facts — every label is derived from data the API sent.
 */

export type NameBook = {
  assets: ReadonlyMap<string, ExerciseAsset>;
  resources: ReadonlyMap<string, ExerciseResource>;
  tasks: ReadonlyMap<string, ExerciseTask>;
  incidents: ReadonlyMap<string, ExerciseIncident>;
  roadNames: ReadonlyMap<string, string>;
};

export function buildNameBook(
  assets: readonly ExerciseAsset[],
  resources: readonly ExerciseResource[],
  tasks: readonly ExerciseTask[],
  roadNames: ReadonlyMap<string, string> = new Map(),
  incidents: readonly ExerciseIncident[] = [],
): NameBook {
  return {
    assets: new Map(assets.map((asset) => [asset.assetId, asset])),
    resources: new Map(
      resources.map((resource) => [resource.resourceId, resource]),
    ),
    tasks: new Map(tasks.map((task) => [task.taskId, task])),
    incidents: new Map(
      incidents.map((incident) => [incident.incidentKey, incident]),
    ),
    roadNames,
  };
}

export function incidentLabel(
  incidentKey: string,
  book: Pick<NameBook, "incidents">,
): string {
  return book.incidents.get(incidentKey)?.name ?? humanize(incidentKey);
}

const RESOURCE_NOUNS: Record<string, string> = {
  engine: "Engine",
  "evacuation-bus": "Evacuation bus",
  "medical-team": "Medical team",
  "road-crew": "Road crew",
};

const TASK_VERBS: Record<string, string> = {
  "community-evacuation": "Evacuate",
  "hospital-support": "Support",
  "power-substation-protection": "Protect",
  "communications-protection": "Protect",
  "corridor-clearing": "Clear",
  "shelter-transport": "Move evacuees to",
};

const CAPABILITY_PHRASES: Record<string, string> = {
  "evacuation-transport": "evacuation transport",
  suppression: "fire suppression",
  "critical-infrastructure-protection": "infrastructure protection",
  "medical-support": "medical support",
  "corridor-clearing": "corridor clearing",
};

const ASSET_KIND_PHRASES: Record<string, string> = {
  community: "Community",
  hospital: "Hospital",
  shelter: "Shelter",
  "power-substation": "Power substation",
  communications: "Communications site",
  "road-corridor": "Road corridor",
};

export const OBJECTIVE_COPY: Record<
  ExerciseObjective,
  { title: string; plain: string; tradeoff: string }
> = {
  "fastest-response": {
    title: "Reach tasks fastest",
    plain: "Send every unit to whatever it can reach soonest.",
    tradeoff:
      "Travel time dominates, so a nearby low-priority task can outrank a distant critical one.",
  },
  "protect-critical-services": {
    title: "Protect critical services",
    plain:
      "Cover hospitals, power, and communications first, even when they are further away.",
    tradeoff:
      "Large-population evacuations can go uncovered while units hold critical sites.",
  },
  "maximize-population-coverage": {
    title: "Cover the most people",
    plain: "Weight every task by how many people it protects.",
    tradeoff:
      "Small critical sites lose out to whichever task shelters the bigger population.",
  },
};

export function resourceLabel(
  resourceId: string,
  book: Pick<NameBook, "resources">,
): string {
  const resource = book.resources.get(resourceId);
  if (!resource) {
    return humanize(resourceId);
  }
  const noun =
    RESOURCE_NOUNS[resource.resourceType] ?? humanize(resource.resourceType);
  const ordinal = resourceId.match(/(\d+)$/)?.[1];
  return ordinal ? `${noun} ${ordinal}` : noun;
}

export function resourceDetail(
  resourceId: string,
  book: Pick<NameBook, "resources">,
): string {
  const resource = book.resources.get(resourceId);
  if (!resource) {
    return "";
  }
  const capabilities = resource.capabilities.map(capabilityLabel).join(", ");
  return `Capacity ${resource.capacity} · ${capabilities}`;
}

export function assetLabel(
  assetId: string,
  book: Pick<NameBook, "assets">,
): string {
  return book.assets.get(assetId)?.name ?? humanize(assetId);
}

export function assetKindLabel(kind: string): string {
  return ASSET_KIND_PHRASES[kind] ?? humanize(kind);
}

export function taskLabel(
  taskId: string,
  book: Pick<NameBook, "tasks" | "assets">,
): string {
  const task = book.tasks.get(taskId);
  if (!task) {
    return humanize(taskId);
  }
  const place = assetLabel(task.assetId, book);
  const verb = TASK_VERBS[task.taskType];
  return verb ? `${verb} ${place}` : `${humanize(task.taskType)} — ${place}`;
}

export function taskDetail(
  taskId: string,
  book: Pick<NameBook, "tasks">,
): string {
  const task = book.tasks.get(taskId);
  if (!task) {
    return "";
  }
  const parts = [
    `Needs ${task.requiredCapacity} ${capabilityLabel(task.requiredCapability)}`,
    `${formatPopulation(task.affectedPopulation)} people affected`,
  ];
  if (task.criticalService) {
    parts.push("critical service");
  }
  return parts.join(" · ");
}

export function capabilityLabel(capability: string): string {
  return CAPABILITY_PHRASES[capability] ?? humanize(capability).toLowerCase();
}

export function roadLabel(
  edgeId: string,
  book: Pick<NameBook, "roadNames">,
): string {
  return book.roadNames.get(edgeId) ?? "a road segment";
}

export function formatPopulation(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatMinutes(value: number): string {
  if (value <= 0) {
    return "already on scene";
  }
  if (value < 1) {
    return "under a minute away";
  }
  return `${Math.round(value)} min away`;
}

export function formatDistance(meters: number): string {
  if (meters <= 0) {
    return "no travel";
  }
  return meters < 1000
    ? `${Math.round(meters)} m`
    : `${(meters / 1000).toFixed(1)} km`;
}

const COMPASS = [
  "north",
  "north-east",
  "east",
  "south-east",
  "south",
  "south-west",
  "west",
  "north-west",
];

export function compassLabel(degrees: number): string {
  const normalized = ((degrees % 360) + 360) % 360;
  return COMPASS[Math.round(normalized / 45) % 8];
}

export function windLabel(disruption: ExerciseDisruption): string {
  const mph = disruption.windSpeedMps * 2.23694;
  return `${mph.toFixed(0)} mph from the ${compassLabel(
    disruption.windDirectionDegrees,
  )}`;
}

export type ChangeTone = "neutral" | "caution" | "alert" | "good";

export type PlainChange = {
  code: string;
  tone: ChangeTone;
  headline: string;
  detail: string;
};

/**
 * Turns one `explanation.changes` entry into a headline plus a sentence.
 * Unknown codes fall through to the server's own summary rather than being
 * dropped, so a backend addition degrades to "still readable" and never to
 * "silently missing".
 */
export function describeChange(
  change: PlanChange,
  book: NameBook,
): PlainChange {
  const evidence = change.evidence as Record<string, unknown>;
  const resource = () =>
    resourceLabel(stringField(evidence, "resourceId"), book);
  const task = (key: string) => taskLabel(stringField(evidence, key), book);

  switch (change.code) {
    case "plan.outcome": {
      const covered = arrayField(evidence, "coveredTaskIds").length;
      const uncovered = arrayField(evidence, "uncoveredTaskIds").length;
      return {
        code: change.code,
        tone: uncovered > 0 ? "caution" : "good",
        headline:
          uncovered > 0
            ? `${covered} of ${covered + uncovered} tasks covered`
            : "Every task covered",
        detail:
          uncovered > 0
            ? `The solver found the best assignment it could; ${uncovered} ${
                uncovered === 1 ? "task has" : "tasks have"
              } no unit left to send.`
            : "Every task has a unit assigned with enough capacity.",
      };
    }
    case "wind.changed": {
      const before = windFromEvidence(evidence.before);
      const after = windFromEvidence(evidence.after);
      return {
        code: change.code,
        tone: "caution",
        headline: "The wind shifted",
        detail: `Wind went from ${before} to ${after}, which changes how the fire is expected to move.`,
      };
    }
    case "incident.task-added":
      return {
        code: change.code,
        tone: "alert",
        headline: `New task: ${task("taskId")}`,
        detail: `${incidentLabel(
          stringField(evidence, "incidentId"),
          book,
        )} added work that was not in the previous checkpoint.`,
      };
    case "incident.task-removed":
      return {
        code: change.code,
        tone: "neutral",
        headline: `No longer in play: ${task("taskId")}`,
        detail: "This task is not part of the current checkpoint.",
      };
    case "route.closed":
      return {
        code: change.code,
        tone: "alert",
        headline: `${roadLabel(stringField(evidence, "edgeId"), book)} is closed`,
        detail:
          "Units that used this segment have to route around it, which lengthens their travel time.",
      };
    case "route.reopened":
      return {
        code: change.code,
        tone: "good",
        headline: `${roadLabel(stringField(evidence, "edgeId"), book)} reopened`,
        detail: "Routing through this segment is available again.",
      };
    case "assignment.changed": {
      const beforeTaskId = evidence.beforeTaskId;
      const afterTaskId = evidence.afterTaskId;
      if (typeof beforeTaskId !== "string") {
        return {
          code: change.code,
          tone: "neutral",
          headline: `${resource()} was committed`,
          detail: `${resource()} had nothing assigned before and now handles ${task(
            "afterTaskId",
          )}.`,
        };
      }
      if (typeof afterTaskId !== "string") {
        return {
          code: change.code,
          tone: "caution",
          headline: `${resource()} was released`,
          detail: `${resource()} was handling ${task(
            "beforeTaskId",
          )} and now has no assignment.`,
        };
      }
      return {
        code: change.code,
        tone: "caution",
        headline: `${resource()} was reassigned`,
        detail: `${resource()} moved off ${task("beforeTaskId")} and onto ${task(
          "afterTaskId",
        )}.`,
      };
    }

    case "override.locked-assignment":
      return {
        code: change.code,
        tone: "neutral",
        headline: "Your override was applied",
        detail: `${resource()} was pinned to ${task(
          "taskId",
        )} before the solver ran, so it could not be moved.`,
      };
    case "operator.override-changed-plan": {
      const before = numberField(evidence.before, "objectiveValue");
      const after = numberField(evidence.after, "objectiveValue");
      const direction =
        after === null || before === null
          ? "changed the plan"
          : after > before
            ? "cost the plan some coverage"
            : "improved the plan";
      return {
        code: change.code,
        tone: after !== null && before !== null && after > before ? "caution" : "neutral",
        headline: `Your override ${direction}`,
        detail:
          before === null || after === null
            ? "The stored plan differs from the one the solver would have chosen."
            : `The solver's score went from ${before} to ${after}. Lower is better, so this override traded measured quality for the judgement in the field report.`,
      };
    }
    case "objective.changed":
      return {
        code: change.code,
        tone: "neutral",
        headline: "The objective changed",
        detail: `Planning switched from ${objectiveTitle(
          evidence.before,
        )} to ${objectiveTitle(evidence.after)}, which changes how competing tasks are ranked.`,
      };
    case "task.priority-changed":
      return {
        code: change.code,
        tone: "caution",
        headline: `${task("taskId")} changed priority`,
        detail: "This task is now weighted differently against the others.",
      };
    case "resource.unavailable":
      return {
        code: change.code,
        tone: "alert",
        headline: `${resource()} went out of service`,
        detail: `${resource()} can no longer be assigned to anything at this checkpoint.`,
      };
    default:
      if (change.code.startsWith("task.uncovered-")) {
        return uncoveredChange(change, evidence, book);
      }
      return {
        code: change.code,
        tone: "neutral",
        headline: humanize(change.code.replace(/\./g, " ")),
        // A code this build has never seen still must not put raw identifiers
        // on screen, so the server's sentence is rewritten before it is shown.
        detail: plainify(change.summary, book),
      };
  }
}

/**
 * The solver reports nine distinct reasons a task went uncovered. They all name
 * the task and the units it competed for, so they share one shape: an alert
 * headline plus the specific reason in the operator's vocabulary.
 */
function uncoveredChange(
  change: PlanChange,
  evidence: Record<string, unknown>,
  book: NameBook,
): PlainChange {
  const taskId = stringField(evidence, "taskId");
  const label = taskLabel(taskId, book);
  const units = arrayField(evidence, "resourceIds").map((id) =>
    resourceLabel(id, book),
  );
  const named = joinLabels(units);
  const plural = units.length > 1;

  const detail = ((): string => {
    switch (change.code) {
      case "task.uncovered-availability":
        return `${named || "The only compatible unit"} could do this job, but ${
          plural ? "they are" : "it is"
        } out of service.`;
      case "task.uncovered-compatibility": {
        const capability = book.tasks.get(taskId)?.requiredCapability;
        return capability
          ? `Nothing on scene carries ${capabilityLabel(capability)}.`
          : "No unit on scene has the capability this task needs.";
      }
      case "task.uncovered-route":
        return `${named || "The compatible unit"} cannot reach it — every route is blocked.`;
      case "task.uncovered-deadline":
        return `${named || "The compatible unit"} would arrive after this task's deadline.`;
      case "task.uncovered-capacity": {
        const supplied = numberField(evidence, "eligibleCapacity");
        const required = numberField(evidence, "requiredCapacity");
        return supplied === null || required === null
          ? "The units that could take it cannot supply enough capacity between them."
          : `The units that could take it supply ${supplied} between them; it needs ${required}.`;
      }
      case "task.uncovered-contention":
        return `${named || "The only compatible unit"} could do this job, but ${
          plural ? "they are" : "it is"
        } already committed elsewhere. Nothing else on scene has the right capability.`;
      case "task.uncovered-feasible-incumbent":
        return "The solver ran out of time before it could prove this was the best it could do, and left a capable unit unused.";
      case "task.uncovered-objective-tradeoff":
        return "A unit could have taken this, but the objective you chose ranked the work it is doing now higher.";
      case "task.uncovered-solver-status": {
        const status = stringField(evidence, "status");
        return status
          ? `The planner returned ${status.toLowerCase()} and produced no assignment for this task.`
          : "The planner produced no assignment for this task.";
      }
      default:
        return plainify(change.summary, book);
    }
  })();

  return {
    code: change.code,
    tone: "alert",
    headline: `${label} is uncovered`,
    detail,
  };
}

function objectiveTitle(value: unknown): string {
  return typeof value === "string" && value in OBJECTIVE_COPY
    ? OBJECTIVE_COPY[value as keyof typeof OBJECTIVE_COPY].title.toLowerCase()
    : "an unrecorded objective";
}

function joinLabels(labels: readonly string[]): string {
  if (labels.length === 0) {
    return "";
  }
  if (labels.length === 1) {
    return labels[0];
  }
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * Last line of defence for any server sentence this build does not parse:
 * every identifier the exercise knows about is swapped for its plain label, so
 * an unrecognised message degrades to readable rather than to `evacuate-chico`.
 */
export function plainify(sentence: string, book: NameBook): string {
  let result = sentence;
  for (const [taskId] of book.tasks) {
    result = replaceAll(result, taskId, taskLabel(taskId, book));
  }
  for (const [resourceId] of book.resources) {
    result = replaceAll(result, resourceId, resourceLabel(resourceId, book));
  }
  for (const [edgeId] of book.roadNames) {
    result = replaceAll(result, edgeId, roadLabel(edgeId, book));
  }
  return result;
}

function replaceAll(haystack: string, needle: string, value: string): string {
  return needle.length === 0 ? haystack : haystack.split(needle).join(value);
}

// Every `bindingConstraints` family the solver emits. The strings are stable
// contract output from decision/task_optimizer.py; each carries identifiers
// that must be relabelled before an operator sees them.
const CONSTRAINT_PATTERNS: {
  pattern: RegExp;
  render: (groups: string[], book: NameBook) => string;
}[] = [
  {
    pattern: /^compatibility: resource=(.+?); task=(.+?); resource lacks capability=(.+)$/,
    render: ([resourceId, taskId, capability], book) =>
      `${resourceLabel(resourceId, book)} cannot take ${taskLabel(
        taskId,
        book,
      )} — it has no ${capabilityLabel(capability)}.`,
  },
  {
    pattern: /^availability: resource=(.+?); task=(.+?); resource is unavailable$/,
    render: ([resourceId, taskId], book) =>
      `${resourceLabel(resourceId, book)} is out of service, so it cannot take ${taskLabel(
        taskId,
        book,
      )}.`,
  },
  {
    pattern: /^route: resource=(.+?); task=(.+?); route is unreachable$/,
    render: ([resourceId, taskId], book) =>
      `${resourceLabel(resourceId, book)} has no route to ${taskLabel(taskId, book)}.`,
  },
  {
    pattern: /^deadline: resource=(.+?); task=(.+?); travel_minutes=(.+?) exceeds deadline_minutes=(.+)$/,
    render: ([resourceId, taskId, travel, deadline], book) =>
      `${resourceLabel(resourceId, book)} would take ${Math.round(
        Number(travel),
      )} min to reach ${taskLabel(taskId, book)}, past its ${deadline} min deadline.`,
  },
  {
    pattern: /^route: task=(.+?); no candidate route$/,
    render: ([taskId], book) =>
      `No unit has a usable route to ${taskLabel(taskId, book)}.`,
  },
  {
    pattern: /^capacity: task=(.+?); eligible_capacity=(.+?) is below required_capacity=(.+)$/,
    render: ([taskId, supplied, required], book) =>
      `${taskLabel(
        taskId,
        book,
      )} needs ${required} and the units that could take it supply only ${supplied}.`,
  },
  {
    pattern: /^solver-status: task=(.+?); status=(.+?) produced no solution$/,
    render: ([taskId, status], book) =>
      `The planner returned ${status.toLowerCase()} and produced nothing for ${taskLabel(
        taskId,
        book,
      )}.`,
  },
  {
    pattern: /^resource-contention: task=(.+?); eligible assignments=(.+?) consume needed capacity$/,
    render: ([taskId, assignments], book) => {
      const holders = assignments
        .split(",")
        .map((pair) => pair.trim())
        .filter(Boolean)
        .map((pair) => {
          const [resourceId, heldTaskId] = pair.split("->");
          return `${resourceLabel(resourceId, book)} is on ${taskLabel(
            heldTaskId,
            book,
          )}`;
        })
        .join("; ");
      return `${taskLabel(taskId, book)} has no capacity left — ${holders}.`;
    },
  },
];

/**
 * `bindingConstraints` are solver-facing strings. Reviewers get the same facts
 * as a sentence; anything that matches no known family is still stripped of
 * identifiers rather than shown raw.
 */
export function describeConstraint(constraint: string, book: NameBook): string {
  for (const { pattern, render } of CONSTRAINT_PATTERNS) {
    const match = pattern.exec(constraint);
    if (match) {
      return render(match.slice(1), book);
    }
  }
  return plainify(constraint, book);
}

export function eventLabel(eventType: string): string {
  switch (eventType) {
    case "exercise.session-created":
      return "Exercise started";
    case "exercise.objective-selected":
      return "Objective chosen";
    case "exercise.plan-generated":
      return "Plan generated";
    case "exercise.checkpoint-advanced":
      return "Moved to the next checkpoint";
    case "exercise.override-applied":
      return "Operator override applied";
    case "exercise.plan-approved":
      return "Plan approved";
    default:
      return humanize(eventType.replace(/^exercise\./, "").replace(/\./g, " "));
  }
}

export function humanize(value: string): string {
  const spaced = value.replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function stringField(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  return typeof value === "string" ? value : "";
}

function arrayField(source: Record<string, unknown>, key: string): string[] {
  const value = source[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function numberField(source: unknown, key: string): number | null {
  if (typeof source !== "object" || source === null) {
    return null;
  }
  const value = (source as Record<string, unknown>)[key];
  return typeof value === "number" ? value : null;
}

function windFromEvidence(value: unknown): string {
  const speed = numberField(value, "speedMps");
  const direction = numberField(value, "directionDegrees");
  if (speed === null || direction === null) {
    return "an unrecorded reading";
  }
  return `${(speed * 2.23694).toFixed(0)} mph from the ${compassLabel(direction)}`;
}

/** Maps a plan's raw change list into the sentences the UI renders. */
export function toPlainChanges(
  plan: { explanation: { changes: readonly PlanChange[] } } | null,
  book: NameBook,
): PlainChange[] {
  return plan === null
    ? []
    : plan.explanation.changes.map((change) => describeChange(change, book));
}
