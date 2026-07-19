import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  incidentDetailSchema,
  incidentTimelineSchema,
} from "../../api/types";
import {
  incidentDetailResponse,
  incidentTimelineResponse,
} from "../../test/fixtures";
import { IncidentDetails } from "./IncidentDetails";

const incident = incidentDetailSchema.parse(incidentDetailResponse);
const timeline = incidentTimelineSchema.parse(incidentTimelineResponse);

describe("IncidentDetails", () => {
  it("puts the incident priority and planning action before collapsed evidence", async () => {
    const user = userEvent.setup();
    render(
      <IncidentDetails
        incident={incident}
        visualizedRisk={incident.risk}
        riskContext="Current snapshot"
      >
        <section aria-label="Planning child">Next planning action</section>
      </IncidentDetails>,
    );

    const overview = screen.getByRole("region", { name: "Incident overview" });
    expectDefinition(overview, "Priority score", "82");
    expect(overview).toHaveTextContent(
      "Top driver: Population exposure contributed 27.6 points.",
    );

    const planning = screen.getByRole("region", { name: "Planning child" });
    const riskDisclosure = screen.getByText("Risk evidence").closest("details");
    if (!riskDisclosure) {
      throw new Error("Expected risk evidence to use a details disclosure");
    }
    expect(riskDisclosure).not.toHaveAttribute("open");
    expect(
      planning.compareDocumentPosition(riskDisclosure) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("2 NASA FIRMS detections")).toBeVisible();
    expect(screen.getByText("2 exposed assets")).toBeVisible();
    expect(screen.getByText("1 simulated resource")).toBeVisible();

    await user.click(screen.getByText("Risk evidence"));
    expect(
      screen.getByRole("region", { name: "Risk explanation" }),
    ).toBeVisible();
  });

  it("renders complete current risk evidence, provenance, assets, and simulation context", async () => {
    const user = userEvent.setup();
    render(
      <IncidentDetails
        incident={incident}
        visualizedRisk={incident.risk}
        riskContext="Current snapshot"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Decision workspace" }),
    ).toBeVisible();

    const overview = screen.getByRole("region", { name: "Incident overview" });
    expect(within(overview).getByText("Redwood Creek")).toBeVisible();
    expect(within(overview).getByText("active")).toBeVisible();
    expect(within(overview).getByText("Fresh")).toBeVisible();
    expect(
      within(overview).getByText("First observed 2024-07-24 17:18:00 UTC"),
    ).toBeVisible();
    expect(
      within(overview).getByText("Last observed 2024-07-24 18:18:00 UTC"),
    ).toBeVisible();

    await user.click(summaryFor("Risk evidence"));
    const risk = screen.getByRole("region", { name: "Risk explanation" });
    expectHeadingContext(risk, "Risk explanation", "Current snapshot");
    expect(within(risk).getByText("82")).toBeVisible();
    expect(within(risk).getByText("risk-v1")).toBeVisible();

    const factors = within(risk).getByRole("list", { name: "Risk factors" });
    expect(within(factors).getAllByRole("listitem")).toHaveLength(2);

    const populationFactor = listItemForHeading(
      factors,
      "population_exposure",
    );
    await user.click(within(populationFactor).getByText("Raw evidence"));
    expect(populationFactor).toHaveTextContent('"exposed_population": 1184');
    expect(populationFactor).toHaveTextContent(
      '"nearest_distance_meters": 7200',
    );
    expectDefinition(populationFactor, "Normalized value", "0.92");
    expectDefinition(populationFactor, "Weight", "0.3");
    expectDefinition(populationFactor, "Contribution", "27.6");
    expect(populationFactor).not.toHaveTextContent("[object Object]");

    const windFactor = listItemForHeading(factors, "wind_alignment");
    await user.click(within(windFactor).getByText("Raw evidence"));
    expect(windFactor).toHaveTextContent('"speed_mps": 12.4');
    expectDefinition(windFactor, "Normalized value", "0.8");
    expectDefinition(windFactor, "Weight", "0.3");
    expectDefinition(windFactor, "Contribution", "24");

    await user.click(within(risk).getByText("Detailed model configuration"));
    const configuration = within(risk).getByRole("heading", {
      name: "Model configuration",
    }).parentElement?.parentElement;
    if (!configuration) {
      throw new Error("Expected model configuration disclosure");
    }
    expect(configuration).toHaveTextContent(
      '"fire_freshness_seconds": 21600',
    );
    expect(configuration).toHaveTextContent('"population": 0.3');
    expect(configuration).not.toHaveTextContent("[object Object]");

    await user.click(summaryFor("Source provenance"));
    const provenance = screen.getByRole("region", {
      name: "Source provenance",
    });
    await user.click(within(provenance).getByText("Source versions"));
    expect(provenance).toHaveTextContent('"source_name": "nasa_firms"');
    expect(provenance).toHaveTextContent(
      '"source_version": "viirs-2024-07-24"',
    );
    expect(provenance).toHaveTextContent(
      '"latest_observed_at": "2024-07-24T18:18:00Z"',
    );
    expect(provenance).toHaveTextContent("fire-801");
    expect(provenance).toHaveTextContent("Observed 2024-07-24 18:18:00 UTC");
    const firstDetection = within(provenance).getAllByRole("listitem")[0];
    expectDefinition(firstDetection, "Confidence", "0.91");
    expect(provenance).not.toHaveTextContent("[object Object]");

    await user.click(summaryFor("Exposed assets"));
    const assets = screen.getByRole("region", { name: "Exposed assets" });
    expectHeadingContext(assets, "Exposed assets", "Current snapshot");
    expect(within(assets).getAllByRole("listitem")).toHaveLength(2);
    const forestRanch = listItemForHeading(assets, "Forest Ranch");
    expectDefinition(forestRanch, "Kind", "community");
    expectDefinition(forestRanch, "Distance", "7,200 m");
    expectDefinition(forestRanch, "Bearing", "315°");
    expectDefinition(forestRanch, "Population", "1,184");
    expectDefinition(forestRanch, "Source", "census");
    expectDefinition(forestRanch, "Version", "2023-acs5");
    const clinic = listItemForHeading(assets, "Pine Junction Clinic");
    expectDefinition(clinic, "Capacity", "36");

    await user.click(summaryFor("Simulated resources"));
    const resources = screen.getByRole("region", {
      name: "Simulated resources",
    });
    expectHeadingContext(resources, "Simulated resources", "Current snapshot");
    expect(within(resources).getByText("Simulated")).toBeVisible();
    const engine = listItemForHeading(resources, "engine");
    expectDefinition(engine, "Capabilities", "medical, water");
    expectDefinition(engine, "Capacity", "4");
    expectDefinition(engine, "Status", "available");
    expectDefinition(engine, "Availability", "Available");

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("labels replay risk separately while assets and resources remain current", async () => {
    const user = userEvent.setup();
    render(
      <IncidentDetails
        incident={incident}
        visualizedRisk={timeline.items[0].risk}
        riskContext="Replay frame"
      />,
    );

    await user.click(summaryFor("Risk evidence"));
    const risk = screen.getByRole("region", { name: "Risk explanation" });
    expectHeadingContext(risk, "Risk explanation", "Replay frame");
    expect(within(risk).getByText("70")).toBeVisible();
    await user.click(within(risk).getByText("Detailed model configuration"));
    expect(within(risk).getByText("Current snapshot")).toBeVisible();

    await user.click(summaryFor("Exposed assets"));
    await user.click(summaryFor("Simulated resources"));
    const assets = screen.getByRole("region", { name: "Exposed assets" });
    const resources = screen.getByRole("region", {
      name: "Simulated resources",
    });
    expectHeadingContext(assets, "Exposed assets", "Current snapshot");
    expectHeadingContext(resources, "Simulated resources", "Current snapshot");
    expect(within(assets).queryByText("Replay frame")).not.toBeInTheDocument();
    expect(within(resources).queryByText("Replay frame")).not.toBeInTheDocument();
  });

  it("renders explicit empty states for factors, assets, resources, and detections", async () => {
    const user = userEvent.setup();
    const emptyIncident = {
      ...incident,
      detections: [],
      exposedAssets: [],
      simulatedResources: [],
    };
    const emptyRisk = { ...incident.risk, contributions: [] };

    render(
      <IncidentDetails
        incident={emptyIncident}
        visualizedRisk={emptyRisk}
        riskContext="Current snapshot"
      />,
    );

    await user.click(summaryFor("Risk evidence"));
    await user.click(summaryFor("Exposed assets"));
    await user.click(summaryFor("Simulated resources"));
    await user.click(summaryFor("Source provenance"));
    expect(screen.getByText("No risk factors are available.")).toBeVisible();
    expect(screen.getByText("No exposed assets are available.")).toBeVisible();
    expect(
      screen.getByText("No simulated resources are available."),
    ).toBeVisible();
    expectHeadingContext(
      screen.getByRole("region", { name: "Simulated resources" }),
      "Simulated resources",
      "Current snapshot",
    );
    expect(
      screen.getByText("No detection provenance is available."),
    ).toBeVisible();
  });

  it("renders a planning child before the technical evidence", () => {
    render(
      <IncidentDetails
        incident={incident}
        visualizedRisk={incident.risk}
        riskContext="Current snapshot"
      >
        <section aria-label="Planning child">Planning workspace</section>
      </IncidentDetails>,
    );

    const resources = summaryFor("Simulated resources").closest("details");
    const planning = screen.getByRole("region", { name: "Planning child" });

    expect(planning).toHaveTextContent("Planning workspace");
    if (!resources) {
      throw new Error("Expected simulated resources disclosure");
    }
    expect(
      planning.compareDocumentPosition(resources) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

function listItemForHeading(container: HTMLElement, name: string): HTMLElement {
  const item = within(container).getByRole("heading", { name }).closest("li");
  if (!item) {
    throw new Error(`Expected ${name} to be inside a list item`);
  }
  return item;
}

function expectDefinition(
  container: HTMLElement,
  term: string,
  value: string,
): void {
  const termElement = within(container).getByText(term, { selector: "dt" });
  expect(termElement.nextElementSibling).toHaveTextContent(value);
}

function expectHeadingContext(
  container: HTMLElement,
  headingName: string,
  context: string,
): void {
  const heading = within(container).getByRole("heading", { name: headingName });
  expect(heading.nextElementSibling).toHaveTextContent(
    new RegExp(`^${context}$`),
  );
}

function summaryFor(label: string): HTMLElement {
  const summary = screen
    .getAllByText(label)
    .find((element) => element.closest("summary") !== null)
    ?.closest("summary");
  if (!summary) {
    throw new Error(`Expected a summary labeled ${label}`);
  }
  return summary;
}
