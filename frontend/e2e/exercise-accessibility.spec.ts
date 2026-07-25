import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 1000 } });

/** Tabs until the accessible name matches, proving the control is reachable. */
async function tabTo(page: Page, name: string | RegExp, limit = 60): Promise<number> {
  const matches = (value: string) =>
    typeof name === "string" ? value === name : name.test(value);
  for (let presses = 1; presses <= limit; presses += 1) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const element = document.activeElement;
      // Only real controls count. Reading innerText off <body> would match any
      // text on the page and report reachability that does not exist.
      if (
        !(element instanceof HTMLElement) ||
        !element.matches(
          "a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])",
        )
      ) {
        return "";
      }
      return (element.getAttribute("aria-label") ?? element.innerText ?? "").trim();
    });
    if (matches(focused)) {
      return presses;
    }
  }
  throw new Error(`never reached ${String(name)} within ${limit} tab presses`);
}

function focusRing(page: Page) {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (!(element instanceof HTMLElement)) {
      return null;
    }
    const style = getComputedStyle(element);
    return {
      width: style.outlineWidth,
      style: style.outlineStyle,
      color: style.outlineColor,
    };
  });
}

test("the exercise is operable with the keyboard alone", async ({ page }) => {
  await page.goto("/");

  // 1 — start the exercise without touching the mouse.
  await tabTo(page, /I understand/);
  const ring = await focusRing(page);
  expect(ring?.style).not.toBe("none");
  expect(Number.parseFloat(ring?.width ?? "0")).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");

  // 2 — choose an objective from the keyboard.
  await expect(
    page.getByRole("dialog", { name: "Choose an objective" }),
  ).toBeVisible();
  await tabTo(page, /Protect critical services/);
  await page.keyboard.press("Enter");

  const dock = page.getByRole("region", { name: "Next step" });
  await expect(dock.getByRole("button", { name: "Generate the plan" })).toBeVisible();

  // 3 — every map marker is a real button with a plain-language name, so the
  // plot is reachable rather than being a mouse-only surface.
  const markerNames = await page.evaluate(() =>
    [...document.querySelectorAll("button.wf-marker")].map((element) => ({
      name: element.getAttribute("aria-label") ?? "",
      tabbable: element.tabIndex >= 0,
    })),
  );
  expect(markerNames.length).toBeGreaterThan(0);
  for (const marker of markerNames) {
    expect(marker.name).not.toBe("");
    expect(marker.name).not.toMatch(/^(exercise-|census-place-|osm-)/);
    expect(marker.tabbable).toBe(true);
  }

  // 4 — generate a plan, then dismiss the briefing, all from the keyboard.
  await tabTo(page, "Generate the plan");
  await page.keyboard.press("Enter");
  const briefing = page.getByRole("dialog", { name: "Initial allocation" });
  await expect(briefing).toBeVisible();
  // The briefing moves focus to its own action rather than stranding it behind.
  await expect(
    briefing.getByRole("button", { name: "Review the plan" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(briefing).toBeHidden();

  // 5 — the drawer tabs are operable by keyboard.
  await tabTo(page, "Evidence");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab", { name: "Evidence" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("a modal briefing actually confines focus", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "I understand — start the exercise" })
    .click();
  await page
    .getByRole("dialog", { name: "Choose an objective" })
    .getByRole("button", { name: /Protect critical services/ })
    .click();
  await page.getByRole("button", { name: "Generate the plan" }).click();

  const briefing = page.getByRole("dialog", { name: "Initial allocation" });
  await expect(briefing).toBeVisible();

  // aria-modal="true" is a promise: nothing behind the veil may be reachable.
  for (const region of ["Exercise progress", "Checkpoint details", "Next step"]) {
    await expect(page.getByLabel(region)).toHaveAttribute("inert", "");
  }

  // Tabbing right around the dialog must never land outside it.
  for (let press = 0; press < 12; press += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(
      () => !!document.activeElement?.closest(".wf-brief"),
    );
    expect(inside).toBe(true);
  }
});

test("opening a panel moves focus into it and gives it back on Escape", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "I understand — start the exercise" })
    .click();

  // The objective dialog opens on its own, so focus has to arrive with it.
  await expect(
    page.getByRole("dialog", { name: "Choose an objective" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Choose an objective" })).toBeFocused();

  await page
    .getByRole("dialog", { name: "Choose an objective" })
    .getByRole("button", { name: /Protect critical services/ })
    .click();

  const change = page.getByRole("button", { name: "Change objective" });
  await change.click();
  await expect(
    page.getByRole("heading", { name: "Change the objective" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  // Focus returns to the control that opened the panel rather than the body.
  await expect(change).toBeFocused();
});

test("Escape closes the topmost layer", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "I understand — start the exercise" })
    .click();
  const objectives = page.getByRole("dialog", { name: "Choose an objective" });
  await objectives
    .getByRole("button", { name: /Protect critical services/ })
    .click();

  // Re-opening the objective picker is a dismissable layer; Escape must close
  // it without abandoning the exercise underneath.
  await page.getByRole("button", { name: "Change objective" }).click();
  await expect(objectives).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(objectives).toBeHidden();
  await expect(
    page.getByRole("region", { name: "Next step" }),
  ).toBeVisible();
});

test.describe("with reduced motion", () => {
  test("no content is left hidden by a suppressed animation", async ({ page }) => {
    // Emulated per page rather than through test.use: the fixture form was
    // silently not reaching the page, so the whole assertion passed vacuously.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    expect(
      await page.evaluate(
        () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "I understand — start the exercise" })
      .click();
    await page
      .getByRole("dialog", { name: "Choose an objective" })
      .getByRole("button", { name: /Protect critical services/ })
      .click();
    await page.getByRole("button", { name: "Generate the plan" }).click();

    const briefing = page.getByRole("dialog", { name: "Initial allocation" });
    await expect(briefing).toBeVisible();

    // Several surfaces animate in from opacity:0. If the animation is removed
    // but the starting state survives, the content disappears entirely — the
    // failure mode that matters most for a reduced-motion user.
    const hidden = await page.evaluate(() => {
      const selectors = [
        ".wf-brief",
        ".wf-brief__item",
        ".wf-dock",
        ".wf-panel",
        ".wf-veil",
      ];
      return selectors.flatMap((selector) =>
        [...document.querySelectorAll(selector)]
          .map((element) => ({
            selector,
            opacity: Number.parseFloat(getComputedStyle(element).opacity),
          }))
          .filter((entry) => entry.opacity < 0.99),
      );
    });
    expect(hidden).toEqual([]);

    // And nothing is still animating.
    const running = await page.evaluate(
      () =>
        document
          .getAnimations()
          .filter((animation) => animation.playState === "running").length,
    );
    expect(running).toBe(0);
  });
});
