import { buildNiceScale } from "./metricChartScale";

export interface ChartDomain {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

export interface MetricSeriesPoint {
  t: number;
  y: number;
}

const MIN_VIEWPORT_FRACTION = 0.04;

function span(min: number, max: number): number {
  return Math.max(max - min, 1e-9);
}

function clampRange(
  min: number,
  max: number,
  boundMin: number,
  boundMax: number,
  minSpan: number
): [number, number] {
  let lo = min;
  let hi = max;
  let range = span(lo, hi);

  if (range < minSpan) {
    const center = (lo + hi) / 2;
    lo = center - minSpan / 2;
    hi = center + minSpan / 2;
    range = minSpan;
  }

  if (lo < boundMin) {
    hi += boundMin - lo;
    lo = boundMin;
  }
  if (hi > boundMax) {
    lo -= hi - boundMax;
    hi = boundMax;
  }

  range = span(lo, hi);
  if (range < minSpan) {
    if (boundMax - boundMin <= minSpan) {
      return [boundMin, boundMax];
    }
    if (lo <= boundMin) {
      return [boundMin, boundMin + minSpan];
    }
    return [boundMax - minSpan, boundMax];
  }

  lo = Math.max(boundMin, lo);
  hi = Math.min(boundMax, hi);
  return [lo, hi];
}

export function computeBaseDomain(
  points: MetricSeriesPoint[],
  fixedYDomain?: [number, number]
): ChartDomain | null {
  if (points.length === 0) {
    return null;
  }

  const yValues = points.map((p) => p.y);
  const tValues = points.map((p) => p.t);
  const yScale = fixedYDomain
    ? buildNiceScale(fixedYDomain[0], fixedYDomain[1], 5)
    : buildNiceScale(Math.min(...yValues), Math.max(...yValues), 5);
  const xScale = buildNiceScale(Math.min(...tValues), Math.max(...tValues), 5);

  return {
    xMin: xScale.min,
    xMax: xScale.max,
    yMin: yScale.min,
    yMax: yScale.max,
  };
}

export function clampViewport(viewport: ChartDomain, base: ChartDomain): ChartDomain {
  const minXSpan = span(base.xMin, base.xMax) * MIN_VIEWPORT_FRACTION;
  const minYSpan = span(base.yMin, base.yMax) * MIN_VIEWPORT_FRACTION;
  const [xMin, xMax] = clampRange(
    viewport.xMin,
    viewport.xMax,
    base.xMin,
    base.xMax,
    minXSpan
  );
  const [yMin, yMax] = clampRange(
    viewport.yMin,
    viewport.yMax,
    base.yMin,
    base.yMax,
    minYSpan
  );
  return { xMin, xMax, yMin, yMax };
}

export function zoomViewportAt(
  viewport: ChartDomain,
  base: ChartDomain,
  anchor: { x: number; y: number },
  factor: number
): ChartDomain {
  const xRange = span(viewport.xMin, viewport.xMax);
  const yRange = span(viewport.yMin, viewport.yMax);
  const newXRange = xRange * factor;
  const newYRange = yRange * factor;

  const xRatio = (anchor.x - viewport.xMin) / xRange;
  const yRatio = (anchor.y - viewport.yMin) / yRange;

  return clampViewport(
    {
      xMin: anchor.x - xRatio * newXRange,
      xMax: anchor.x + (1 - xRatio) * newXRange,
      yMin: anchor.y - yRatio * newYRange,
      yMax: anchor.y + (1 - yRatio) * newYRange,
    },
    base
  );
}

export function panViewport(
  viewport: ChartDomain,
  base: ChartDomain,
  deltaX: number,
  deltaY: number
): ChartDomain {
  return clampViewport(
    {
      xMin: viewport.xMin + deltaX,
      xMax: viewport.xMax + deltaX,
      yMin: viewport.yMin + deltaY,
      yMax: viewport.yMax + deltaY,
    },
    base
  );
}

export function pixelToData(
  px: number,
  py: number,
  domain: ChartDomain,
  plotLeft: number,
  plotRight: number,
  plotTop: number,
  plotBottom: number
): { x: number; y: number } {
  const xRatio = (px - plotLeft) / span(plotLeft, plotRight);
  const yRatio = (py - plotTop) / span(plotTop, plotBottom);
  return {
    x: domain.xMin + xRatio * span(domain.xMin, domain.xMax),
    y: domain.yMax - yRatio * span(domain.yMin, domain.yMax),
  };
}

export function dataDeltaFromPixelDelta(
  deltaPxX: number,
  deltaPxY: number,
  domain: ChartDomain,
  plotWidth: number,
  plotHeight: number
): { deltaX: number; deltaY: number } {
  return {
    deltaX: (-deltaPxX / plotWidth) * span(domain.xMin, domain.xMax),
    deltaY: (deltaPxY / plotHeight) * span(domain.yMin, domain.yMax),
  };
}

export function isViewportZoomed(viewport: ChartDomain, base: ChartDomain, epsilon = 1e-6): boolean {
  return (
    Math.abs(viewport.xMin - base.xMin) > epsilon ||
    Math.abs(viewport.xMax - base.xMax) > epsilon ||
    Math.abs(viewport.yMin - base.yMin) > epsilon ||
    Math.abs(viewport.yMax - base.yMax) > epsilon
  );
}
