import { describe, expect, it } from "vitest";

import { geometrySchema, jsonValueSchema } from "./types";

function nestedObject(depth: number): unknown {
  let value: unknown = "leaf";
  for (let index = 0; index < depth; index += 1) {
    value = { child: value };
  }
  return value;
}

function nestedGeometryCollection(depth: number): unknown {
  let geometry: unknown = {
    type: "Point",
    coordinates: [-121.6, 39.8],
  };
  for (let index = 0; index < depth; index += 1) {
    geometry = { type: "GeometryCollection", geometries: [geometry] };
  }
  return geometry;
}

describe("bounded JSON schemas", () => {
  it("rejects excessively nested JSON without throwing", () => {
    expect(() => jsonValueSchema.safeParse(nestedObject(80))).not.toThrow();
    expect(jsonValueSchema.safeParse(nestedObject(80)).success).toBe(false);
  });
});

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

  it("rejects excessively nested GeometryCollections without throwing", () => {
    expect(() =>
      geometrySchema.safeParse(nestedGeometryCollection(80)),
    ).not.toThrow();
    expect(
      geometrySchema.safeParse(nestedGeometryCollection(80)).success,
    ).toBe(false);
  });
});
