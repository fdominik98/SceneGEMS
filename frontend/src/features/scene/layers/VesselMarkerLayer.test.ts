import { describe, expect, it } from "vitest";
import { getVesselMarkerScale } from "./vesselMarkerScale";

describe("getVesselMarkerScale", () => {
  it("keeps at least half vessel dimensions at neutral zoom", () => {
    expect(getVesselMarkerScale(100, 20, 1)).toEqual([50, 10, 1]);
  });

  it("stays at minimum size when zoomed out moderately", () => {
    expect(getVesselMarkerScale(100, 20, 0.5)).toEqual([50, 10, 1]);
  });

  it("grows once zoomed out enough to exceed the minimum size", () => {
    expect(getVesselMarkerScale(100, 20, 0.1)).toEqual([75, 15, 1]);
  });
});
