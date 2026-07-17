/// <reference types="node" />

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const setup = readFileSync(resolve(process.cwd(), "e2e/replay-global-setup.ts"), "utf8");
const launcher = readFileSync(resolve(process.cwd(), "../scripts/replay-preview"), "utf8");
const transcript = launcher.replace(/\s+/g, " ");

describe("replay browser setup", () => {
  it("uses one isolated reset-before-start launcher and excludes the worker", () => {
    const isolation = transcript.indexOf('-p "$REPLAY_PROJECT"');
    const reset = transcript.indexOf('down --volumes --remove-orphans');
    const start = transcript.indexOf('up -d --force-recreate db api frontend');

    expect(transcript).toContain('REPLAY_PROJECT="wildfireops-replay-preview"');
    expect(isolation).toBeGreaterThanOrEqual(0);
    expect(reset).toBeGreaterThan(isolation);
    expect(start).toBeGreaterThan(reset);
    const startup = launcher.match(/compose up -d --force-recreate[^\n]*/)?.[0];
    expect(startup).toBe("compose up -d --force-recreate db api frontend");
    expect(setup).toContain("../../scripts/replay-preview");
    expect(setup).not.toContain('"DROP DATABASE');
    expect(setup).not.toContain('"compose"');
  });
});
