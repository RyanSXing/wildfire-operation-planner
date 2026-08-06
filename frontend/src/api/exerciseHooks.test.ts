import { describe, expect, it } from "vitest";

import { selectCitedDetections } from "./exerciseHooks";

// Mirrors the live replay: the exercise cites a detection that the clustering
// placed in the incident NOT named "Park Fire".
const incidents = [
  {
    name: "Park Fire",
    detections: [
      { sourceName: "nasa_firms", sourceRecordId: "viirs-snpp-2024-us-line-226011" },
      { sourceName: "nasa_firms", sourceRecordId: "viirs-snpp-2024-us-line-226012" },
    ],
  },
  {
    name: "Incident b175eda3",
    detections: [
      { sourceName: "nasa_firms", sourceRecordId: "viirs-snpp-2024-us-line-225982" },
      { sourceName: "nasa_firms", sourceRecordId: "viirs-snpp-2024-us-line-225983" },
    ],
  },
];

describe("selectCitedDetections", () => {
  it("follows the cited identity rather than the incident name", () => {
    const cited = selectCitedDetections(incidents, [
      "nasa_firms:viirs-snpp-2024-us-line-225982",
    ]);

    expect(cited.map((item) => item.sourceRecordId)).toEqual([
      "viirs-snpp-2024-us-line-225982",
      "viirs-snpp-2024-us-line-225983",
    ]);
  });

  it("returns nothing when no incident carries the cited detection", () => {
    expect(selectCitedDetections(incidents, ["nasa_firms:absent"])).toEqual([]);
  });

  it("returns nothing when the checkpoint cites no detections", () => {
    expect(selectCitedDetections(incidents, [])).toEqual([]);
  });

  it("merges every incident that carries a cited detection", () => {
    const cited = selectCitedDetections(incidents, [
      "nasa_firms:viirs-snpp-2024-us-line-226011",
      "nasa_firms:viirs-snpp-2024-us-line-225982",
    ]);

    expect(cited).toHaveLength(4);
  });
});
