import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const stylesheet = readFileSync(resolve(process.cwd(), "src/App.css"), "utf8");

describe("disclosure target size", () => {
  it("gives operational disclosure summaries a 44px target", () => {
    expect(stylesheet).toMatch(
      /\.decision-workspace__disclosure > summary,\n\.scenario-planning-panel__road-catalog > summary \{[^}]*min-height: 44px;/,
    );
  });
});
