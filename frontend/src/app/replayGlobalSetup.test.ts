/// <reference types="node" />

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const setup = readFileSync(resolve(process.cwd(), "e2e/replay-global-setup.ts"), "utf8");
const transcript = setup.replace(/\s+/g, " ");
const startups = [...transcript.matchAll(/dockerCompose\(\s*"up"\s*,([^;]+)\);/g)];

describe("replay browser setup", () => {
  it("stops the worker before rebuilding the replay database without starting it", () => {
    const workerStop = transcript.search(
      /dockerCompose\(\s*"stop"\s*,\s*"api"\s*,\s*"frontend"\s*,\s*"worker"\s*\)/,
    );
    const databaseReset = transcript.indexOf(
      '"DROP DATABASE IF EXISTS wildfireops WITH (FORCE);"',
    );

    expect(workerStop).toBeGreaterThanOrEqual(0);
    expect(databaseReset).toBeGreaterThan(workerStop);
    expect(startups).not.toHaveLength(0);
    expect(startups.every(([, command]) => !command.includes('"worker"'))).toBe(true);
  });
});
