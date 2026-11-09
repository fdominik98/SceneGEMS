import { describe, expect, it } from "vitest";
import { buildNiceScale, buildTimeScale, formatAxisTick, formatCompactTick, tickDecimals } from "./metricChartScale";

describe("tickDecimals", () => {
  it("gives the decimals that keep the ticks of a padded flat scale apart", () => {
    const ticks = buildNiceScale(0, 0, 5).ticks;
    const decimals = tickDecimals(ticks);
    const labels = ticks.map((tick) => formatAxisTick(tick, decimals));
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("uses no decimals for whole steps", () => {
    expect(tickDecimals([0, 500, 1000])).toBe(0);
    expect(tickDecimals([0, 0.05, 0.1])).toBe(2);
  });
});

describe("buildTimeScale", () => {
  it("puts the ticks on whole minutes for a run of about 18 minutes", () => {
    const scale = buildTimeScale(0, 1065, 5);
    expect(scale.min).toBe(0);
    expect(scale.max).toBe(1065);
    expect(scale.ticks).toEqual([0, 300, 600, 900]);
  });

  it("keeps the domain and starts at the first step inside it", () => {
    const scale = buildTimeScale(7, 70, 4);
    expect(scale.ticks).toEqual([30, 60]);
    expect(scale.ticks.every((tick) => tick >= 7 && tick <= 70)).toBe(true);
  });

  it("gives one tick for a single instant", () => {
    expect(buildTimeScale(30, 30).ticks).toEqual([30]);
  });
});

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
    expect(formatAxisTick(12.5, 3)).toBe("12.5");
  });

  it("keeps the zeros of large whole numbers", () => {
    expect(formatAxisTick(20000, 0)).toBe("20000");
    expect(formatAxisTick(15000, 1)).toBe("15000");
  });
});

describe("formatCompactTick", () => {
  it("abbreviates thousands from 10000 on", () => {
    expect(formatCompactTick(20000)).toBe("20k");
    expect(formatCompactTick(12500, 4)).toBe("12.5k");
    expect(formatCompactTick(5000)).toBe("5000");
    expect(formatCompactTick(-0.25, 2)).toBe("-0.25");
  });
});
