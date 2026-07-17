import { expect, test } from "@playwright/test";

test("an operator can decide the Park Fire replay recommendation", async ({ page }) => {
  await page.goto("/");

  const queue = page.getByRole("complementary", { name: "Incident queue" });
  const incidents = queue.getByRole("button");
  await expect(incidents).not.toHaveCount(0);
  await incidents.first().click();
  await expect(incidents.first()).toHaveAttribute("aria-pressed", "true");

  await expect(page.getByRole("region", { name: "Incident overview" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Risk explanation" })).toContainText(/Score[1-9]/);
  const assets = page.getByRole("region", { name: "Exposed assets" });
  await expect(assets).toContainText(/Kindcommunity/i);
  await expect(assets).toContainText(/Population[1-9]/);
  await expect(page.getByRole("region", { name: "Source provenance" })).toContainText(/Observed/);
  const sourceFreshness = page.getByRole("region", { name: "Source freshness" });
  await expect(sourceFreshness).toContainText(/Sources fresh/i);
  await expect(sourceFreshness).toContainText("nasa_firms");
  await expect(sourceFreshness).toContainText("noaa_ncei");
  await expect(sourceFreshness).toContainText("Fresh");

  const planning = page.getByRole("region", { name: "Scenario planning" });
  await planning.getByRole("button", { name: "Create baseline and generate recommendation" }).click();
  await expect(planning.getByRole("form", { name: "Scenario version editor" })).toBeVisible();

  const editor = planning.getByRole("form", { name: "Scenario version editor" });
  const closures = editor.getByRole("checkbox");
  expect(await closures.count()).toBeGreaterThan(0);
  await closures.first().check();
  await editor.getByRole("button", { name: "Save scenario version" }).click();
  await expect(planning).toContainText("Active scenario version 2");
  await planning.getByRole("button", { name: "Generate recommendation for version 2" }).click();
  await expect(page.getByRole("region", { name: "Scenario outcome comparison" })).toBeVisible();

  const decisions = page.getByRole("region", { name: "Recommendation decision controls" });
  await decisions.getByRole("button", { name: "Approve recommendation" }).click();
  await page.getByLabel("Decision note").fill("Stage resources for replay exercise");
  await page.getByRole("button", { name: "Submit approve decision" }).click();

  await page.getByText("Audit history", { exact: true }).click();
  const events = page.getByRole("list", { name: "Audit events" });
  await expect(events).toContainText("Stage resources for replay exercise");
  await events.getByRole("button", { name: /^View details for / }).first().click();
  const provenance = page.getByRole("region", { name: "Audit provenance" });
  await expect(provenance).toContainText("Stage resources for replay exercise");
  await expect(provenance).toContainText(/Source versions/);
});
