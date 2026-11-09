export interface MetricSeriesPoint {
  t: number;
  y: number;
}

/** The stretch of time a chart shows, in seconds. */
export interface TimeWindow {
  start: number;
  end: number;
}

/** The narrowest view a zoom reaches, as a share of the whole run. */
const MIN_WINDOW_FRACTION = 0.02;

/** A view moved and shrunk into `base`, at least the narrowest zoom wide. */
export function clampTimeWindow(view: TimeWindow, base: TimeWindow): TimeWindow {
  const baseSpan = Math.max(base.end - base.start, 1e-9);
  const span = Math.min(baseSpan, Math.max(view.end - view.start, baseSpan * MIN_WINDOW_FRACTION));
  const start = Math.min(Math.max(view.start, base.start), base.end - span);
  return { start, end: start + span };
}

/** The view zoomed by `factor` (below 1 zooms in) around the time `anchor`, which stays where it is. */
export function zoomTimeWindow(view: TimeWindow, base: TimeWindow, anchor: number, factor: number): TimeWindow {
  const span = view.end - view.start;
  const ratio = span > 0 ? (anchor - view.start) / span : 0.5;
  const nextSpan = span * factor;
  return clampTimeWindow({ start: anchor - ratio * nextSpan, end: anchor + (1 - ratio) * nextSpan }, base);
}

/** The last point at or before `t` (points sorted by time), or null when every point is later. */
export function valueAtOrBefore(points: MetricSeriesPoint[], t: number): MetricSeriesPoint | null {
  if (points.length === 0 || points[0]!.t > t) {
    return null;
  }
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (points[mid]!.t <= t) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return points[lo]!;
}
