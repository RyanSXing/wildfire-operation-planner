import { describe, expect, it } from "vitest";

import { geometrySchema } from "./types";

describe("geometrySchema", () => {
  it("rejects unknown or structurally incomplete GeoJSON geometry", () => {
    expect(geometrySchema.safeParse({ type: "Point" }).success).toBe(false);
    expect(
      geometrySchema.safeParse({
        type: "Polygon",
        coordinates: [[[-121.6]]],
      }).success,
    ).toBe(false);
    expect(
      geometrySchema.safeParse({
        type: "FutureGeometry",
        coordinates: [-121.6, 39.8],
      }).success,
    ).toBe(false);
  });

  it("accepts standard geometry shapes and preserves forward-compatible members", () => {
    const result = geometrySchema.parse({
      type: "Point",
      coordinates: [-121.6, 39.8],
      bbox: [-121.6, 39.8, -121.6, 39.8],
      vendorMetadata: { quality: "reviewed" },
    });

    expect(result).toMatchObject({
      type: "Point",
      coordinates: [-121.6, 39.8],
      vendorMetadata: { quality: "reviewed" },
    });
  });

  it("validates nested standard GeometryCollection members", () => {
    const result = geometrySchema.parse({
      type: "GeometryCollection",
      geometries: [
        { type: "Point", coordinates: [-121.6, 39.8] },
        {
          type: "GeometryCollection",
          geometries: [
            {
              type: "LineString",
              coordinates: [
                [-121.6, 39.8],
                [-121.5, 39.9],
              ],
            },
          ],
        },
      ],
      vendorMetadata: { quality: "reviewed" },
    });

    expect(result.type).toBe("GeometryCollection");
    expect(result).toHaveProperty("vendorMetadata.quality", "reviewed");
    expect(
      geometrySchema.safeParse({
        type: "GeometryCollection",
        geometries: [{ type: "Banana", coordinates: [0] }],
      }).success,
    ).toBe(false);
  });
});
