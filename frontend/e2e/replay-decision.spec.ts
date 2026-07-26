import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

// Three planning round trips through the real solver do not fit in Playwright's
// 30s default; the individual expectations keep their own tighter timeouts.
test.describe.configure({ timeout: 150_000 });

test("an operator can decide the Park Fire replay recommendation", async ({ page }) => {
  // The decision exercise owns "/"; the live command centre is at /monitor.
  await page.goto("/monitor");

  // The rail ranks incidents; picking one drives everything else.
  const rail = page.getByRole("navigation", { name: "Incident queue" });
  const incidents = rail.getByRole("button");
  await expect(incidents).not.toHaveCount(0);
  const scores = (await rail.locator(".wf-incident__score").allTextContents()).map(
    Number,
  );
  expect(scores).toHaveLength(await incidents.count());
  const highestRisk = incidents.nth(scores.indexOf(Math.max(...scores)));
  await highestRisk.click();
  await expect(highestRisk).toHaveAttribute("aria-pressed", "true");

  const drawer = page.getByRole("complementary", { name: "Incident details" });
  const dock = page.getByRole("region", { name: "Next step" });

  // Before any planning the command bar offers exactly one action.
  await expect(page.getByText("OBSERVING")).toBeVisible();
  await expect(dock).toContainText("Ready to plan");

  // Evidence is where the machine vocabulary lives.
  await drawer.getByRole("tab", { name: "Evidence" }).click();
  await expect(
    drawer.getByRole("region", { name: "Risk explanation" }),
  ).toContainText(/Priority score/);
  await expect(
    drawer.getByRole("region", { name: "Source provenance" }),
  ).toContainText(/detections/);
  await expect(
    drawer.getByRole("region", { name: "Source freshness" }),
  ).toContainText(/nasa_firms/);

  // Exposed places and units are reachable without touching the map.
  await drawer.getByRole("tab", { name: "Resources" }).click();
  await expect(drawer).toContainText(/EXPOSED PLACES/i);

  // 1 — baseline.
  await drawer.getByRole("tab", { name: "Plan" }).click();
  await dock.getByRole("button", { name: "Create the baseline plan" }).click();
  await expect(page.getByText("PLAN READY")).toBeVisible({ timeout: 30_000 });
  await expect(dock).toContainText(/Covers/);

  // The plan reads in plain language: no solver status, no raw identifiers.
  const planPanel = drawer.getByRole("tabpanel");
  await expect(planPanel).toContainText("WHAT THE PLAN DOES");
  await expect(planPanel).toContainText(
    /best allocation the planner could find|allocation works/,
  );
  const planText = await planPanel.innerText();
  expect(planText).not.toMatch(/OPTIMAL|FEASIBLE/);
  expect(planText).not.toMatch(
    /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/,
  );

  // 2 — branch the scenario by closing a road.
  const scenario = page.getByRole("dialog", { name: "Scenario assumptions" });
  await dock.getByRole("button", { name: "Adjust the scenario" }).click();
  await expect(scenario).toBeVisible();

  const editor = scenario.getByRole("form", { name: "Scenario version editor" });
  const firstClosure = editor
    .getByRole("group", { name: "Road closures" })
    .getByRole("checkbox")
    .first();
  await expect(firstClosure).toHaveCount(1);
  await firstClosure.check();
  await editor.getByRole("button", { name: "Save scenario version" }).click();
  await expect(scenario).toBeHidden();

  // 3 — plan again against the branch and compare against the baseline.
  await dock.getByRole("button", { name: "Generate the plan" }).click();
  await expect(dock).toContainText(/Covers/, { timeout: 30_000 });
  await expect(planPanel).toContainText("ASSUMPTIONS THIS PLAN USED");
  // The closure is named, never shown as an edge hash.
  await expect(planPanel).toContainText(/is closed/);
  expect(await planPanel.innerText()).not.toMatch(/osm-[0-9a-f]{16}/);
  await expect(planPanel).toContainText("AGAINST THE BASELINE");

  // 4 — record a decision with a note.
  //
  // Rejecting rather than approving, deliberately. Approving dispatches the
  // unit for good, so it can only ever succeed once per seeded database and
  // makes the spec unrepeatable. Rejection records the same decision, note and
  // audit event without consuming a resource, so this runs green every time.
  // The approval path is covered by DecisionDialog.test.tsx.
  const decision = page.getByRole("dialog", {
    name: "Recommendation decision controls",
  });
  await expect(decision).toBeVisible();
  await decision.getByRole("button", { name: "Reject recommendation" }).click();
  await page.getByLabel("Decision note").fill("Stage resources for replay exercise");
  await page.getByRole("button", { name: "Submit reject decision" }).click();

  // The command bar is what reports the outcome here: recording a decision
  // closes the decision panel, so its own confirmation section is gone by the
  // time the state settles.
  await expect(dock).toContainText("Decision recorded", { timeout: 30_000 });
  await expect(page.getByText("DECIDED")).toBeVisible();

  // 5 — the decision is in the audit trail.
  await dock.getByRole("button", { name: "View audit" }).click();
  await page.getByText("Audit history", { exact: true }).click();
  const events = page.getByRole("list", { name: "Audit events" });
  const approval = events
    .getByRole("listitem")
    .filter({ hasText: "Stage resources for replay exercise" });
  await expect(approval).toHaveCount(1);
  await approval.getByRole("button", { name: /^View details for / }).click();
  await expect(
    page.getByRole("region", { name: "Audit provenance" }),
  ).toContainText(/Observed|allocation|approve/);
});

test("planning is locked, and says so, while a replay frame is showing", async ({
  page,
}) => {
  await page.goto("/monitor");
  const dock = page.getByRole("region", { name: "Next step" });
  await expect(dock).toContainText("Ready to plan");

  const slider = page.getByRole("slider", { name: /Replay position/ });
  // An incident without two ordered snapshots has no usable replay range; the
  // control is disabled rather than absent, and planning stays available.
  if (await slider.isDisabled()) {
    await expect(dock).toContainText("Ready to plan");
    return;
  }

  await slider.fill("0");
  await expect(page.getByText("REPLAY")).toBeVisible();
  await expect(dock).toContainText("You are looking at a replay frame");
  await expect(
    dock.getByRole("button", { name: "Create the baseline plan" }),
  ).toHaveCount(0);

  await dock.getByRole("button", { name: "Return to current" }).click();
  await expect(dock).toContainText("Ready to plan");
});
