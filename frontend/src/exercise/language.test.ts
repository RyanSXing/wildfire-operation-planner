import { describe, expect, it } from "vitest";

import type {
  ExerciseAsset,
  ExerciseResource,
  ExerciseTask,
} from "../api/exerciseTypes";
import {
  buildNameBook,
  capabilityLabel,
  compassLabel,
  describeChange,
  describeConstraint,
  plainify,
  eventLabel,
  formatMinutes,
  resourceLabel,
  taskLabel,
  windLabel,
} from "./language";

// Shapes and values below are copied from live `park-fire-decision` responses.
const assets: ExerciseAsset[] = [
  asset("census-place-0655520", "Paradise town", "community"),
  asset("census-place-0613014", "Chico city", "community"),
  asset("adventist-health-feather-river", "Adventist Health Feather River", "hospital"),
  asset("card-community-center", "CARD Community Center", "shelter"),
  asset("nunneley-road-corridor", "Nunneley Road corridor", "road-corridor"),
];

const resources: ExerciseResource[] = [
  resource("exercise-bus-1", "evacuation-bus", ["evacuation-transport"], 40),
  resource("exercise-engine-1", "engine", ["suppression"], 2),
  resource("exercise-road-crew-1", "road-crew", ["corridor-clearing"], 1),
];

const tasks: ExerciseTask[] = [
  task("evacuate-chico", "census-place-0613014", "community-evacuation", "evacuation-transport", 40, 101475, false),
  task("evacuate-paradise", "census-place-0655520", "community-evacuation", "evacuation-transport", 40, 4764, false),
  task("shelter-capacity-transport", "card-community-center", "shelter-transport", "evacuation-transport", 40, 300, true),
  task("clear-primary-corridor", "nunneley-road-corridor", "corridor-clearing", "corridor-clearing", 1, 4764, true),
];

const book = buildNameBook(
  assets,
  resources,
  tasks,
  new Map([["osm-2010000", "Nunneley Road"]]),
);

describe("identifier labels", () => {
  it("names resources by type and ordinal, never by raw id", () => {
    expect(resourceLabel("exercise-bus-1", book)).toBe("Evacuation bus 1");
    expect(resourceLabel("exercise-road-crew-1", book)).toBe("Road crew 1");
  });

  it("falls back to a readable phrase for an unknown resource", () => {
    expect(resourceLabel("exercise-helicopter-9", book)).toBe(
      "Exercise helicopter 9",
    );
  });

  it("phrases tasks as instructions about a named place", () => {
    expect(taskLabel("evacuate-chico", book)).toBe("Evacuate Chico city");
    expect(taskLabel("shelter-capacity-transport", book)).toBe(
      "Move evacuees to CARD Community Center",
    );
  });

  it("spells out capabilities", () => {
    expect(capabilityLabel("critical-infrastructure-protection")).toBe(
      "infrastructure protection",
    );
  });

  it("renames audit event types", () => {
    expect(eventLabel("exercise.plan-approved")).toBe("Plan approved");
    expect(eventLabel("exercise.brand-new-thing")).toBe("Brand new thing");
  });
});

describe("units", () => {
  it("reads travel time as an operator would say it", () => {
    expect(formatMinutes(0)).toBe("already on scene");
    expect(formatMinutes(0.4)).toBe("under a minute away");
    expect(formatMinutes(5.97)).toBe("6 min away");
  });

  it("converts wind to mph and a compass point it came from", () => {
    expect(compassLabel(210)).toBe("south-west");
    expect(
      windLabel({
        windSpeedMps: 5.7,
        windDirectionDegrees: 160,
        closedEdgeIds: [],
        provenance: "exercise",
      }),
    ).toBe("13 mph from the south");
  });
});

describe("describeChange", () => {
  it("explains contention by naming the unit that is busy", () => {
    const plain = describeChange(
      {
        code: "task.uncovered-contention",
        summary: "evacuate-chico remains uncovered because its compatible resource is assigned elsewhere.",
        evidence: { resourceIds: ["exercise-bus-1"], taskId: "evacuate-chico" },
      },
      book,
    );
    expect(plain.tone).toBe("alert");
    expect(plain.headline).toBe("Evacuate Chico city is uncovered");
    expect(plain.detail).toContain("Evacuation bus 1");
    expect(plain.detail).not.toContain("exercise-bus-1");
  });

  it("reads a reassignment as a move between two named tasks", () => {
    const plain = describeChange(
      {
        code: "assignment.changed",
        summary: "A resource assignment changed.",
        evidence: {
          resourceId: "exercise-bus-1",
          beforeTaskId: "evacuate-paradise",
          afterTaskId: "shelter-capacity-transport",
        },
      },
      book,
    );
    expect(plain.headline).toBe("Evacuation bus 1 was reassigned");
    expect(plain.detail).toBe(
      "Evacuation bus 1 moved off Evacuate Paradise town and onto Move evacuees to CARD Community Center.",
    );
  });

  it("treats a null beforeTaskId as a first commitment, not a move", () => {
    const plain = describeChange(
      {
        code: "assignment.changed",
        summary: "A resource assignment changed.",
        evidence: {
          resourceId: "exercise-road-crew-1",
          beforeTaskId: null,
          afterTaskId: "clear-primary-corridor",
        },
      },
      book,
    );
    expect(plain.headline).toBe("Road crew 1 was committed");
    expect(plain.detail).toContain("had nothing assigned before");
  });

  it("names the closed road rather than its hash", () => {
    const plain = describeChange(
      {
        code: "route.closed",
        summary: "A corridor closed.",
        evidence: { edgeId: "osm-2010000" },
      },
      book,
    );
    expect(plain.headline).toBe("Nunneley Road is closed");
  });

  it("reports an override that made the objective worse as a trade", () => {
    const plain = describeChange(
      {
        code: "operator.override-changed-plan",
        summary: "The operator override changed the stored plan.",
        evidence: {
          resourceId: "exercise-bus-1",
          taskId: "shelter-capacity-transport",
          before: { travelCost: 6, uncoveredTaskPenalty: 223, objectiveValue: 229 },
          after: { travelCost: 28, uncoveredTaskPenalty: 325, objectiveValue: 353 },
        },
      },
      book,
    );
    expect(plain.tone).toBe("caution");
    expect(plain.headline).toBe("Your override cost the plan some coverage");
    expect(plain.detail).toContain("229 to 353");
  });

  it("keeps the server summary for a code it does not know", () => {
    const plain = describeChange(
      { code: "future.thing", summary: "Something new happened.", evidence: {} },
      book,
    );
    expect(plain.detail).toBe("Something new happened.");
  });

  // Every one of these is emitted by decision/task_explanations.py and every
  // one interpolates the raw task id into its summary.
  it.each([
    ["task.uncovered-availability", /out of service/],
    ["task.uncovered-compatibility", /Nothing on scene carries/],
    ["task.uncovered-route", /every route is blocked/],
    ["task.uncovered-deadline", /after this task's deadline/],
    ["task.uncovered-capacity", /supply/],
    ["task.uncovered-feasible-incumbent", /ran out of time/],
    ["task.uncovered-objective-tradeoff", /ranked the work it is doing now higher/],
    ["task.uncovered-solver-status", /produced no assignment/],
  ])("explains %s without printing an identifier", (code, expected) => {
    const plain = describeChange(
      {
        code,
        summary: `evacuate-chico remains uncovered because of ${code}.`,
        evidence: {
          taskId: "evacuate-chico",
          resourceIds: ["exercise-bus-1"],
          status: "INFEASIBLE",
          requiredCapacity: 40,
          eligibleCapacity: 0,
        },
      },
      book,
    );
    expect(plain.tone).toBe("alert");
    expect(plain.headline).toBe("Evacuate Chico city is uncovered");
    expect(plain.detail).toMatch(expected);
    expect(`${plain.headline} ${plain.detail}`).not.toMatch(
      /evacuate-chico|exercise-bus-1/,
    );
  });

  it("strips identifiers out of a sentence it cannot parse", () => {
    const plain = describeChange(
      {
        code: "future.thing",
        summary: "exercise-bus-1 abandoned evacuate-chico on osm-2010000.",
        evidence: {},
      },
      book,
    );
    expect(plain.detail).toBe(
      "Evacuation bus 1 abandoned Evacuate Chico city on Nunneley Road.",
    );
  });
});

describe("plainify", () => {
  it("rewrites every identifier the exercise knows about", () => {
    expect(
      plainify("exercise-road-crew-1 -> clear-primary-corridor via osm-2010000", book),
    ).toBe("Road crew 1 -> Clear Nunneley Road corridor via Nunneley Road");
  });

  it("leaves text with no identifiers alone", () => {
    expect(plainify("The wind shifted.", book)).toBe("The wind shifted.");
  });
});

describe("describeConstraint", () => {
  it("explains a capability mismatch", () => {
    expect(
      describeConstraint(
        "compatibility: resource=exercise-engine-1; task=evacuate-chico; resource lacks capability=evacuation-transport",
        book,
      ),
    ).toBe(
      "Engine 1 cannot take Evacuate Chico city — it has no evacuation transport.",
    );
  });

  it("explains contention by naming who holds the capacity", () => {
    expect(
      describeConstraint(
        "resource-contention: task=evacuate-chico; eligible assignments=exercise-bus-1->shelter-capacity-transport consume needed capacity",
        book,
      ),
    ).toBe(
      "Evacuate Chico city has no capacity left — Evacuation bus 1 is on Move evacuees to CARD Community Center.",
    );
  });

  // The remaining families the solver emits, all of which embed identifiers.
  it.each([
    [
      "availability: resource=exercise-bus-1; task=evacuate-chico; resource is unavailable",
      "Evacuation bus 1 is out of service, so it cannot take Evacuate Chico city.",
    ],
    [
      "route: resource=exercise-bus-1; task=evacuate-chico; route is unreachable",
      "Evacuation bus 1 has no route to Evacuate Chico city.",
    ],
    [
      "route: task=evacuate-chico; no candidate route",
      "No unit has a usable route to Evacuate Chico city.",
    ],
    [
      "capacity: task=evacuate-chico; eligible_capacity=0 is below required_capacity=40",
      "Evacuate Chico city needs 40 and the units that could take it supply only 0.",
    ],
    [
      "solver-status: task=evacuate-chico; status=INFEASIBLE produced no solution",
      "The planner returned infeasible and produced nothing for Evacuate Chico city.",
    ],
    [
      "deadline: resource=exercise-bus-1; task=evacuate-chico; travel_minutes=21.66 exceeds deadline_minutes=20",
      "Evacuation bus 1 would take 22 min to reach Evacuate Chico city, past its 20 min deadline.",
    ],
  ])("explains %s", (constraint, expected) => {
    expect(describeConstraint(constraint, book)).toBe(expected);
  });

  it("still strips identifiers from a constraint family it cannot parse", () => {
    expect(
      describeConstraint("something-else: resource=exercise-bus-1", book),
    ).toBe("something-else: resource=Evacuation bus 1");
  });
});

function asset(assetId: string, name: string, assetKind: string): ExerciseAsset {
  return {
    assetId,
    assetKind,
    name,
    position: { longitude: -121.6, latitude: 39.75 },
    sourceName: "OpenStreetMap",
    sourceVersion: "2026-07-25T14:03:09Z",
    sourceRecordId: assetId,
    citationUrl: `https://example.invalid/${assetId}`,
    provenance: "historical",
  };
}

function resource(
  resourceId: string,
  resourceType: string,
  capabilities: string[],
  capacity: number,
): ExerciseResource {
  return {
    resourceId,
    resourceType,
    capabilities,
    capacity,
    available: true,
    position: { longitude: -121.6064, latitude: 39.754192 },
    provenance: "exercise",
  };
}

function task(
  taskId: string,
  assetId: string,
  taskType: string,
  requiredCapability: string,
  requiredCapacity: number,
  affectedPopulation: number,
  criticalService: boolean,
): ExerciseTask {
  return {
    taskId,
    incidentKey: "park-fire",
    assetId,
    taskType,
    requiredCapability,
    requiredCapacity,
    deadlineMinutes: 1000,
    affectedPopulation,
    criticalService,
    basePriority: 100,
    provenance: "exercise",
  };
}
