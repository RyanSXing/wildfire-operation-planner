import { expect, test, type Locator, type Page } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

test("an operator completes the Park Fire decision exercise end to end", async ({
  page,
}) => {
  await page.goto("/");

  // 1 — introduction, safety statement, and provenance disclosure.
  await expect(
    page.getByRole("heading", { name: "Park Fire decision exercise" }),
  ).toBeVisible();
  await expect(page.getByText(/Do not use for emergency/i)).toBeVisible();
  await expect(page.getByText(/Invented for training/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "source" }).first(),
  ).toHaveAttribute("href", /census\.gov|openstreetmap\.org/);

  // 2 — session creation.
  await page
    .getByRole("button", { name: "I understand — start the exercise" })
    .click();

  const rail = page.getByRole("navigation", { name: "Exercise progress" });
  await expect(rail).toContainText("Choose an objective");
  await expect(page.getByText("SITUATION")).toBeVisible();

  // 3 — objective selection, stated with its trade-off.
  const objectives = page.getByRole("dialog", { name: "Choose an objective" });
  await expect(objectives).toContainText("Trade-off:");
  await objectives
    .getByRole("button", { name: /Protect critical services/ })
    .click();

  // 4 — initial allocation checkpoint.
  await expect(rail).toContainText("Initial allocation");
  await generatePlan(page);

  // Scarcity is surfaced immediately: one bus cannot cover two evacuations.
  const firstBriefing = page.getByRole("dialog", { name: "Initial allocation" });
  await expect(firstBriefing).toContainText("Evacuate Chico city is uncovered");
  await expect(firstBriefing).toContainText("Evacuation bus 1");
  await dismissBriefing(firstBriefing);

  const drawer = page.getByRole("complementary", { name: "Checkpoint details" });
  await expect(drawer).toContainText("Evacuate Paradise town");
  await expect(drawer).toContainText("Support Adventist Health Feather River");
  // Identifiers from the API must never reach the operator.
  await expect(drawer).not.toContainText("exercise-bus-1");
  await expect(drawer).not.toContainText("evacuate-paradise");

  // The planner cannot cover Chico with one bus; the reason must be explained.
  await expect(drawer).toContainText("Evacuate Chico city is uncovered");

  // The fire itself has to be on the plot, drawn from the satellite detections
  // the checkpoint cites as its provenance.
  const legend = page.getByLabel("Plot legend");
  await expect(legend).toContainText("Fire detection (satellite)");
  const detectionCount = await page.evaluate(async () => {
    const list = await (await fetch("/api/incidents")).json();
    const details = await Promise.all(
      list.items.map(async (item: { id: string }) =>
        (await fetch(`/api/incidents/${item.id}`)).json(),
      ),
    );
    return details.reduce(
      (total: number, incident: { detections: unknown[] }) =>
        total + incident.detections.length,
      0,
    );
  });
  expect(detectionCount).toBeGreaterThan(0);

  await continueToNextCheckpoint(page);

  // 5 — cascading disruption, announced as an explained change set.
  await expect(rail).toContainText("Cascading disruption");
  await generatePlan(page);
  const briefing = page.getByRole("dialog", { name: /Cascading disruption/ });
  await expect(briefing).toBeVisible();
  await expect(briefing).toContainText("The wind shifted");
  await expect(briefing).toContainText(/is closed/);
  await expect(briefing).toContainText(/New task:/);
  await expect(briefing).toContainText(/is uncovered/);
  await dismissBriefing(briefing);

  await continueToNextCheckpoint(page);

  // 6 — shelter field report checkpoint.
  await expect(rail).toContainText("Shelter field report");
  await generatePlan(page);
  const fieldBriefing = page.getByRole("dialog", {
    name: /Shelter field report/,
  });
  await expect(fieldBriefing).toBeVisible();
  await dismissBriefing(fieldBriefing);

  // 7 — the bus override workflow.
  const override = page.getByRole("dialog", { name: "Field report override" });
  await expect(override).toContainText(
    "Move evacuees to CARD Community Center",
  );
  await expect(override).toContainText(/shelter capacity pressure/i);
  const unit = override.getByRole("combobox");
  await expect(unit).toContainText("Evacuation bus 1");
  await override
    .getByRole("button", { name: "Apply the override and replan" })
    .click();

  const overrideBriefing = page.getByRole("dialog", {
    name: /Shelter field report/,
  });
  await expect(overrideBriefing).toBeVisible();
  await expect(overrideBriefing).toContainText("Your override");
  await dismissBriefing(overrideBriefing);

  // 8 — named approval with a written decision note.
  const approval = page.getByRole("dialog", { name: "Approve the plan" });
  await expect(approval).toContainText("uncovered");
  const approve = approval.getByRole("button", { name: "Approve and record" });
  await expect(approve).toBeDisabled();
  await approval.getByLabel("YOUR NAME").fill("R. Xing");
  await approval
    .getByLabel("WHY THIS PLAN")
    .fill(
      "Accepted the shelter field report over the solver's ranking; Chico stays uncovered pending mutual aid.",
    );
  await expect(approve).toBeEnabled();
  await approve.click();

  // 9 — audit timeline and debrief.
  await page.getByRole("button", { name: "Open the debrief" }).click();
  const debrief = page.getByRole("main");
  await expect(
    page.getByRole("heading", { name: "Debrief", exact: true }),
  ).toBeVisible();
  await expect(debrief).toContainText("Accepted the shelter field report");
  await expect(debrief).toContainText("Exercise started");
  await expect(debrief).toContainText("Objective chosen");
  await expect(debrief).toContainText("Operator override applied");
  await expect(debrief).toContainText("Plan approved");
  await expect(debrief).toContainText("R. Xing");
  await expect(debrief).toContainText("Move evacuees to CARD Community Center");

  // 10 — read-only planning sandbox, available only after completion.
  await page.getByRole("tab", { name: "Planning sandbox" }).click();
  await expect(debrief).toContainText("Nothing here is recorded");

  // Every control is built from the options the API advertises, so these labels
  // can only be right if the metadata was actually read.
  const options = await page.evaluate(async () => {
    const response = await fetch("/api/exercises/park-fire-decision");
    const body: {
      sandbox: {
        closureEdgeIds: string[];
        windPresets: { key: string }[];
        priorityPresets: { key: string; multiplier: number }[];
      };
    } = await response.json();
    return body.sandbox;
  });
  expect(options.windPresets.length).toBeGreaterThan(0);
  const weather = page.getByLabel("WEATHER ASSUMPTION");
  for (const preset of options.windPresets) {
    await expect(weather).toContainText(preset.key.replace(/-/g, " "), {
      ignoreCase: true,
    });
  }
  for (const preset of options.priorityPresets) {
    await expect(debrief).toContainText(`×${preset.multiplier}`);
  }
  // The one corridor the exercise can close is named, not shown as a hash.
  expect(options.closureEdgeIds).toHaveLength(1);
  await expect(debrief).toContainText("Close Nunneley Road");

  // A priority set on one checkpoint must not be sent with another; the server
  // rejects the whole request for a task id it does not recognise.
  const checkpoint = page.getByLabel("CHECKPOINT");
  await checkpoint.selectOption({ label: "Cascading disruption" });
  await page
    .getByLabel("Clear Nunneley Road corridor")
    .selectOption({ label: "Urgent (×3)" });
  await checkpoint.selectOption({ label: "Field report" });

  await page.getByRole("button", { name: "Run this what-if" }).click();
  const result = page.getByRole("region", { name: "What-if result" });
  await expect(result).toBeVisible();
  await expect(result).toContainText("tasks covered");
  await expect(result).toContainText("objective score");

  // Taking a unit out of service is the sandbox's headline control, and it
  // drives the solver down explanation paths the guided run never reaches.
  await page.getByLabel("Evacuation bus 1", { exact: true }).check();
  await page.getByRole("button", { name: "Run this what-if" }).click();
  await expect(result).toContainText("is uncovered");

  // No solver identifier may reach the screen on any of those paths.
  const rendered = await result.innerText();
  expect(rendered).not.toMatch(/exercise-(bus|engine|medical|road-crew)-\d/);
  expect(rendered).not.toMatch(
    /evacuate-(chico|paradise)|shelter-capacity-transport|protect-[a-z-]+|clear-primary-corridor/,
  );
  expect(rendered).not.toMatch(/osm-[0-9a-f]{16}/);
  expect(rendered).not.toMatch(/task\.uncovered|resource-contention:|compatibility:/);

  // The signed decision is untouched by sandbox exploration.
  await page.getByRole("tab", { name: "What you decided" }).click();
  await expect(debrief).toContainText("Accepted the shelter field report");
});

test("the live monitor stays reachable on its own route", async ({ page }) => {
  await page.goto("/monitor");
  await expect(
    page.getByRole("navigation", { name: "Incident queue" }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Next step" })).toBeVisible();
});

async function dismissBriefing(briefing: Locator): Promise<void> {
  await briefing.getByRole("button", { name: "Review the plan" }).click();
  await expect(briefing).toBeHidden();
}

async function generatePlan(page: Page): Promise<void> {
  const dock = page.getByRole("region", { name: "Next step" });
  const generate = dock.getByRole("button", { name: "Generate the plan" });
  await generate.click();
  await expect(generate).toBeHidden({ timeout: 30_000 });
}

async function continueToNextCheckpoint(page: Page): Promise<void> {
  const dock = page.getByRole("region", { name: "Next step" });
  await dock.getByRole("button", { name: "Continue" }).click();
  await expect(
    dock.getByRole("button", { name: "Generate the plan" }),
  ).toBeVisible({ timeout: 30_000 });
}
