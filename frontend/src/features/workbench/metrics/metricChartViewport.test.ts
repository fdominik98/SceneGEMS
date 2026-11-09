import { describe, expect, it } from "vitest";
import { clampTimeWindow, valueAtOrBefore, zoomTimeWindow } from "./metricChartViewport";

const base = { start: 0, end: 1000 };

describe("zoomTimeWindow", () => {
  it("zooms in around the anchor, which keeps its place", () => {
    const zoomed = zoomTimeWindow(base, base, 250, 0.5);
    expect(zoomed.end - zoomed.start).toBeCloseTo(500);
    expect((250 - zoomed.start) / (zoomed.end - zoomed.start)).toBeCloseTo(0.25);
  });

  it("never zooms out past the whole run", () => {
    const zoomed = zoomTimeWindow({ start: 100, end: 300 }, base, 200, 100);
    expect(zoomed).toEqual(base);
  });

  it("stops at the narrowest window", () => {
    const zoomed = zoomTimeWindow({ start: 400, end: 410 }, base, 405, 0.01);
    expect(zoomed.end - zoomed.start).toBeCloseTo(20);
  });
});

describe("clampTimeWindow", () => {
  it("moves a window that left the run back inside it", () => {
    expect(clampTimeWindow({ start: -50, end: 150 }, base)).toEqual({ start: 0, end: 200 });
    expect(clampTimeWindow({ start: 950, end: 1150 }, base)).toEqual({ start: 800, end: 1000 });
  });
});

describe("valueAtOrBefore", () => {
  const points = [
    { t: 0, y: 10 },
    { t: 15, y: 20 },
    { t: 30, y: 30 },
  ];

  it("gives the last point at or before the time", () => {
    expect(valueAtOrBefore(points, 20)).toEqual({ t: 15, y: 20 });
    expect(valueAtOrBefore(points, 30)).toEqual({ t: 30, y: 30 });
    expect(valueAtOrBefore(points, 99)).toEqual({ t: 30, y: 30 });
  });

  it("gives null before the first point", () => {
    expect(valueAtOrBefore(points, -1)).toBeNull();
    expect(valueAtOrBefore([], 5)).toBeNull();
  });
});
