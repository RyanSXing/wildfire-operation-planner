import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  RoadEdge,
  ScenarioVersion,
  SimulatedResource,
} from "../../api/types";
import { ScenarioEditor } from "./ScenarioEditor";

const roadEdges: RoadEdge[] = [
  {
    edgeId: "edge-9",
    label: "Zulu Road",
    geometry: null,
    travelMinutes: 9,
    distanceMeters: 900,
  },
  {
    edgeId: "edge-2",
    label: "Alpha Road",
    geometry: null,
    travelMinutes: 2,
    distanceMeters: 200,
  },
];

const resources: SimulatedResource[] = [
  {
    resourceId: "crew-9",
    resourceType: "crew",
    capabilities: ["evacuation"],
    capacity: 8,
    available: false,
    status: "unavailable",
    geometry: { type: "Point", coordinates: [-121.5, 39.9] },
    simulated: true,
    simulationLabel: "simulated",
  },
  {
    resourceId: "crew-4",
    resourceType: "engine",
    capabilities: ["water"],
    capacity: 4,
    available: true,
    status: "available",
    geometry: { type: "Point", coordinates: [-121.6, 39.8] },
    simulated: true,
    simulationLabel: "simulated",
  },
];

const selectedVersion: ScenarioVersion = {
  id: "version-2",
  scenarioId: "scenario-1",
  incidentId: "incident-1",
  incidentSnapshotId: "snapshot-1",
  version: 2,
  graphVersion: "roads-v1",
  roadClosures: [{ edgeId: "edge-9" }, { edgeId: "edge-2" }],
  weatherOverrides: [{ windSpeedMps: 12, windDirectionDegrees: 220 }],
  resourceOverrides: [{ resourceId: "crew-4", available: false }],
};

const multiWeatherVersion: ScenarioVersion = {
  ...selectedVersion,
  weatherOverrides: [
    ...selectedVersion.weatherOverrides,
    { windSpeedMps: 18, windDirectionDegrees: 270 },
  ],
};

describe("ScenarioEditor", () => {
  it("emits deterministic exact replacements without mutating inputs", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const originalRoads = structuredClone(roadEdges);
    const originalResources = structuredClone(resources);

    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.click(
      screen.getByRole("checkbox", { name: "Zulu Road (edge-9)" }),
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Alpha Road (edge-2)" }),
    );
    await user.type(screen.getByLabelText("Wind speed (m/s)"), "12");
    await user.type(screen.getByLabelText("Wind direction (degrees)"), "220");
    await user.click(
      screen.getByRole("checkbox", { name: "crew-4 (engine)" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [{ edgeId: "edge-2" }, { edgeId: "edge-9" }],
      weatherOverrides: [
        { windSpeedMps: 12, windDirectionDegrees: 220 },
      ],
      resourceOverrides: [{ resourceId: "crew-4", available: false }],
    });
    expect(roadEdges).toEqual(originalRoads);
    expect(resources).toEqual(originalResources);
  });

  it("seeds existing overlays and disables semantically unchanged input", () => {
    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={selectedVersion}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("checkbox", { name: "Alpha Road (edge-2)" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Zulu Road (edge-9)" }),
    ).toBeChecked();
    expect(screen.getByLabelText("Wind speed (m/s)")).toHaveValue(12);
    expect(screen.getByLabelText("Wind direction (degrees)")).toHaveValue(220);
    expect(
      screen.getByRole("checkbox", { name: "crew-4 (engine)" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "crew-9 (crew)" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();
  });

  it("emits explicit empty arrays when every overlay is cleared", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={selectedVersion}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.click(
      screen.getByRole("checkbox", { name: "Alpha Road (edge-2)" }),
    );
    await user.click(
      screen.getByRole("checkbox", { name: "Zulu Road (edge-9)" }),
    );
    await user.clear(screen.getByLabelText("Wind speed (m/s)"));
    await user.clear(screen.getByLabelText("Wind direction (degrees)"));
    await user.click(
      screen.getByRole("checkbox", { name: "crew-4 (engine)" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [],
      weatherOverrides: [],
      resourceOverrides: [],
    });
  });

  it("shows accessible wind errors and disables invalid, busy, or unchanged forms", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    const submit = screen.getByRole("button", {
      name: "Save scenario version",
    });

    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Wind speed (m/s)"), "12");
    expect(screen.getByText("Enter wind direction with wind speed.")).toBeVisible();
    expect(screen.getByLabelText("Wind direction (degrees)")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Wind direction (degrees)"), "360");
    expect(
      screen.getByText("Wind direction must be at least 0 and less than 360."),
    ).toBeVisible();
    expect(submit).toBeDisabled();

    await user.clear(screen.getByLabelText("Wind speed (m/s)"));
    await user.type(screen.getByLabelText("Wind speed (m/s)"), "-1");
    await user.clear(screen.getByLabelText("Wind direction (degrees)"));
    await user.type(screen.getByLabelText("Wind direction (degrees)"), "200");
    expect(
      screen.getByText("Wind speed must be a finite nonnegative number."),
    ).toBeVisible();
    expect(submit).toBeDisabled();

    rerender(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={null}
        busy
        errorMessage="Could not save scenario."
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not save scenario.",
    );
    expect(submit).toBeDisabled();
  });

  it("preserves drafts for the same immutable input and resets for a new version", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={selectedVersion}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    const alphaRoad = screen.getByRole("checkbox", {
      name: "Alpha Road (edge-2)",
    });
    await user.click(alphaRoad);
    expect(alphaRoad).not.toBeChecked();

    rerender(
      <ScenarioEditor
        roadEdges={[...roadEdges]}
        resources={structuredClone(resources)}
        version={structuredClone(selectedVersion)}
        busy
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(alphaRoad).not.toBeChecked();

    rerender(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={{
          ...selectedVersion,
          id: "version-3",
          version: 3,
          roadClosures: [{ edgeId: "edge-2" }],
          weatherOverrides: [
            { windSpeedMps: 5, windDirectionDegrees: 90 },
          ],
          resourceOverrides: [],
        }}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("checkbox", { name: "Alpha Road (edge-2)" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Zulu Road (edge-9)" }),
    ).not.toBeChecked();
    expect(screen.getByLabelText("Wind speed (m/s)")).toHaveValue(5);
    expect(screen.getByLabelText("Wind direction (degrees)")).toHaveValue(90);
    expect(
      screen.getByRole("checkbox", { name: "crew-4 (engine)" }),
    ).toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();
  });

  it("resets a baseline draft only when observed resource availability changes", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    const crew = screen.getByRole("checkbox", { name: "crew-4 (engine)" });
    await user.click(crew);
    expect(crew).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeEnabled();

    rerender(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={structuredClone(resources)}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(crew).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeEnabled();

    rerender(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources.map((resource) =>
          resource.resourceId === "crew-4"
            ? { ...resource, available: false }
            : resource,
        )}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("checkbox", { name: "crew-4 (engine)" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();
  });

  it("orders resource replacements by deterministic code units", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const unicodeResources: SimulatedResource[] = [
      { ...resources[0], resourceId: "ä-team", available: true },
      { ...resources[1], resourceId: "z-team", available: true },
    ];
    render(
      <ScenarioEditor
        roadEdges={[]}
        resources={unicodeResources}
        version={null}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: "ä-team (crew)" }));
    await user.click(screen.getByRole("checkbox", { name: "z-team (engine)" }));
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [],
      weatherOverrides: [],
      resourceOverrides: [
        { resourceId: "z-team", available: false },
        { resourceId: "ä-team", available: false },
      ],
    });
  });

  it("visibly preserves every existing weather override by default", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={multiWeatherVersion}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    const existing = screen.getByRole("list", {
      name: "Existing weather overrides",
    });
    expect(
      Array.from(existing.children, (item) => item.textContent),
    ).toEqual(["12 m/s at 220°", "18 m/s at 270°"]);
    expect(screen.queryByLabelText("Wind speed (m/s)")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save scenario version" }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("checkbox", { name: "Alpha Road (edge-2)" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );
    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [{ edgeId: "edge-9" }],
      weatherOverrides: multiWeatherVersion.weatherOverrides,
      resourceOverrides: [{ resourceId: "crew-4", available: false }],
    });
  });

  it("explicitly clears every existing weather override", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={multiWeatherVersion}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Replace or clear weather overrides",
      }),
    );
    expect(screen.getByLabelText("Wind speed (m/s)")).toHaveValue(null);
    expect(screen.getByLabelText("Wind direction (degrees)")).toHaveValue(null);
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [{ edgeId: "edge-2" }, { edgeId: "edge-9" }],
      weatherOverrides: [],
      resourceOverrides: [{ resourceId: "crew-4", available: false }],
    });
  });

  it("explicitly replaces multiple weather overrides with one", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ScenarioEditor
        roadEdges={roadEdges}
        resources={resources}
        version={multiWeatherVersion}
        busy={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "Replace or clear weather overrides",
      }),
    );
    await user.type(screen.getByLabelText("Wind speed (m/s)"), "7");
    await user.type(screen.getByLabelText("Wind direction (degrees)"), "45");
    await user.click(
      screen.getByRole("button", { name: "Save scenario version" }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      roadClosures: [{ edgeId: "edge-2" }, { edgeId: "edge-9" }],
      weatherOverrides: [{ windSpeedMps: 7, windDirectionDegrees: 45 }],
      resourceOverrides: [{ resourceId: "crew-4", available: false }],
    });
  });
});
