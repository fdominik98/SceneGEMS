import { describe, expect, it } from "vitest";
import { buildNiceScale, formatAxisTick } from "./metricChartScale";

describe("buildNiceScale", () => {
  it("produces evenly spaced ticks across the domain", () => {
    const scale = buildNiceScale(12, 87, 5);
    expect(scale.min).toBeLessThanOrEqual(12);
    expect(scale.max).toBeGreaterThanOrEqual(87);
    expect(scale.ticks.length).toBeGreaterThanOrEqual(3);
    const step = scale.ticks[1]! - scale.ticks[0]!;
    for (let i = 1; i < scale.ticks.length; i++) {
      expect(scale.ticks[i]! - scale.ticks[i - 1]!).toBeCloseTo(step, 5);
    }
  });

  it("pads a flat series", () => {
    const scale = buildNiceScale(5, 5, 4);
    expect(scale.min).toBeLessThan(5);
    expect(scale.max).toBeGreaterThan(5);
  });
});

describe("formatAxisTick", () => {
  it("formats integers without trailing decimals", () => {
    expect(formatAxisTick(120)).toBe("120");
  });

  it("trims trailing zeros from fractional values", () => {
    expect(formatAxisTick(12.5, 1)).toBe("12.5");
  });
});
