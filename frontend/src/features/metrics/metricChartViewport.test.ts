import { describe, expect, it } from "vitest";
import {
  clampViewport,
  computeBaseDomain,
  isViewportZoomed,
  panViewport,
  zoomViewportAt,
} from "./metricChartViewport";

const points = [
  { t: 0, y: 100 },
  { t: 50, y: 200 },
  { t: 100, y: 150 },
];

describe("metricChartViewport", () => {
  it("builds a base domain from series points", () => {
    const base = computeBaseDomain(points);
    expect(base).not.toBeNull();
    expect(base!.xMin).toBeLessThanOrEqual(0);
    expect(base!.xMax).toBeGreaterThanOrEqual(100);
  });

  it("zooms in around an anchor", () => {
    const base = computeBaseDomain(points)!;
    const zoomed = zoomViewportAt(base, base, { x: 50, y: 150 }, 0.5);
    expect(span(zoomed)).toBeLessThan(span(base));
  });

  it("pans within base bounds", () => {
    const base = computeBaseDomain(points)!;
    const zoomed = zoomViewportAt(base, base, { x: 50, y: 150 }, 0.4);
    const panned = panViewport(zoomed, base, -5, 10);
    expect(panned.xMin).toBeGreaterThanOrEqual(base.xMin);
    expect(panned.xMax).toBeLessThanOrEqual(base.xMax);
  });

  it("detects when viewport differs from base", () => {
    const base = computeBaseDomain(points)!;
    const zoomed = zoomViewportAt(base, base, { x: 50, y: 150 }, 0.5);
    expect(isViewportZoomed(zoomed, base)).toBe(true);
    expect(isViewportZoomed(clampViewport(base, base), base)).toBe(false);
  });
});

function span(domain: { xMin: number; xMax: number; yMin: number; yMax: number }) {
  return domain.xMax - domain.xMin + domain.yMax - domain.yMin;
}
