import { useEffect, useId, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { formatClock } from "../scene/encounterGeometry";
import { buildNiceScale, buildTimeScale, formatAxisTick, formatCompactTick, tickDecimals } from "./metricChartScale";
import { clampTimeWindow, valueAtOrBefore, zoomTimeWindow, type MetricSeriesPoint, type TimeWindow } from "./metricChartViewport";

export type { MetricSeriesPoint };

export interface MetricTimeSeriesChartProps {
  title: string;
  unit: string;
  /** The whole series, sorted by time. */
  points: MetricSeriesPoint[];
  /** The play head (seconds): the line is solid up to it and faint after it. */
  cursor: number | null;
  /** Names the series for assistive technology (the vessel pair). */
  seriesLabel: string;
  yDomain?: [number, number];
  valueDecimals?: number;
  accentColor?: string;
  /** A click on the plot moves the play head to that time. */
  onSeek?: (t: number) => void;
}

const HEIGHT = 132;
const MARGIN = { top: 8, right: 12, bottom: 22, left: 46 };
const ZOOM_IN_FACTOR = 0.8;
/** Pixels a press may move and still count as a click (seek) rather than a drag (pan). */
const CLICK_SLOP = 4;

function scale(value: number, domainMin: number, domainMax: number, rangeMin: number, rangeMax: number) {
  if (domainMax === domainMin) {
    return (rangeMin + rangeMax) / 2;
  }
  return rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
}

/** The container's width in pixels, so the chart draws at its real size with real font sizes. */
function useWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    setWidth(element.clientWidth);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) {
        setWidth((previous) => (Math.abs(previous - entry.contentRect.width) < 1 ? previous : entry.contentRect.width));
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/**
 * A compact chart of one metric over time: the whole series, solid up to the play head and faint
 * after it, the play head itself and the value there in the header. Ctrl + wheel (or a pinch)
 * zooms the time axis, a drag pans it while zoomed, a double-click resets it and a click moves
 * the play head.
 */
export function MetricTimeSeriesChart({
  title,
  unit,
  points,
  cursor,
  seriesLabel,
  yDomain,
  valueDecimals = 1,
  accentColor = "var(--accent)",
  onSeek,
}: MetricTimeSeriesChartProps) {
  const clipId = useId();
  const [hostRef, measuredWidth] = useWidth();
  const width = Math.max(measuredWidth, 200);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const pressRef = useRef<{ pointerId: number; startX: number; lastX: number; moved: boolean } | null>(null);
  const [hover, setHover] = useState<{ px: number; point: MetricSeriesPoint } | null>(null);

  const first = points[0];
  const last = points[points.length - 1];
  const startT = first?.t;
  const endT = last?.t;
  const base = useMemo<TimeWindow | null>(
    () => (startT !== undefined && endT !== undefined && endT > startT ? { start: startT, end: endT } : null),
    [endT, startT]
  );
  const [zoom, setZoom] = useState<TimeWindow | null>(null);
  // A zoom belongs to the series it was made on: another pair or run starts unzoomed, frames
  // arriving at the end of a live run keep it.
  const seriesKey = `${seriesLabel}@${startT ?? ""}`;
  const [zoomedSeries, setZoomedSeries] = useState(seriesKey);
  if (zoomedSeries !== seriesKey) {
    setZoomedSeries(seriesKey);
    setZoom(null);
  }
  const view = useMemo(() => (base ? (zoom ? clampTimeWindow(zoom, base) : base) : null), [base, zoom]);
  const zoomed = zoom !== null;

  const plotLeft = MARGIN.left;
  const plotRight = width - MARGIN.right;
  const plotTop = MARGIN.top;
  const plotBottom = HEIGHT - MARGIN.bottom;

  const yScale = useMemo(() => {
    if (yDomain) {
      return buildNiceScale(yDomain[0], yDomain[1], 2);
    }
    let min = Infinity;
    let max = -Infinity;
    for (const point of points) {
      min = Math.min(min, point.y);
      max = Math.max(max, point.y);
    }
    return buildNiceScale(min, max, 3);
  }, [points, yDomain]);
  const yDecimals = tickDecimals(yScale.ticks);
  const yAt = (y: number) => scale(y, yScale.min, yScale.max, plotBottom, plotTop);

  const xScale = useMemo(
    () => (view ? buildTimeScale(view.start, view.end, Math.max(2, Math.floor((plotRight - plotLeft) / 80))) : null),
    [plotLeft, plotRight, view]
  );
  const xAt = (t: number) => (view ? scale(t, view.start, view.end, plotLeft, plotRight) : plotLeft);

  // The line is the expensive part; the play head moves every frame, the line does not.
  const linePath = useMemo(() => {
    if (!view) {
      return "";
    }
    const parts: string[] = [];
    for (const point of points) {
      const x = scale(point.t, view.start, view.end, plotLeft, plotRight);
      const y = scale(point.y, yScale.min, yScale.max, plotBottom, plotTop);
      parts.push(`${parts.length === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
    }
    return parts.join("");
  }, [plotBottom, plotLeft, plotRight, plotTop, points, view, yScale]);

  const atCursor = cursor === null ? null : valueAtOrBefore(points, cursor);
  const shownValue = atCursor ?? (cursor === null ? last : null);
  const cursorX = cursor !== null && view && cursor >= view.start && cursor <= view.end ? xAt(cursor) : null;

  const pointAt = (clientX: number): { px: number; t: number } | null => {
    const svg = svgRef.current;
    if (!svg || !view) {
      return null;
    }
    const rect = svg.getBoundingClientRect();
    const px = Math.min(Math.max(clientX - rect.left, plotLeft), plotRight);
    return { px, t: scale(px, plotLeft, plotRight, view.start, view.end) };
  };

  // Ctrl + wheel and pinches zoom; a plain wheel keeps scrolling the panel. A native listener,
  // because React's wheel listener is passive and cannot keep the page from zooming.
  // The SVG exists only while there is a plot, so the listener is attached when it appears.
  const hasPlot = points.length > 0 && view !== null;
  const zoomRef = useRef({ base, view, pointAt });
  useEffect(() => {
    zoomRef.current = { base, view, pointAt };
  });
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      const { base: currentBase, view: currentView, pointAt: at } = zoomRef.current;
      if (!(event.ctrlKey || event.metaKey) || !currentBase || !currentView) {
        return;
      }
      event.preventDefault();
      const anchor = at(event.clientX);
      if (!anchor) {
        return;
      }
      const next = zoomTimeWindow(currentView, currentBase, anchor.t, event.deltaY < 0 ? ZOOM_IN_FACTOR : 1 / ZOOM_IN_FACTOR);
      setZoom(next.start === currentBase.start && next.end === currentBase.end ? null : next);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [hasPlot]);

  const onPointerDown = (event: ReactPointerEvent<SVGRectElement>) => {
    if (event.button !== 0) {
      return;
    }
    pressRef.current = { pointerId: event.pointerId, startX: event.clientX, lastX: event.clientX, moved: false };
  };

  const onPointerMove = (event: ReactPointerEvent<SVGRectElement>) => {
    const at = pointAt(event.clientX);
    if (at && points.length > 0) {
      const nearest = points[Math.max(0, nearestIndex(points, at.t))]!;
      setHover({ px: xAt(nearest.t), point: nearest });
    }
    const press = pressRef.current;
    if (!press || press.pointerId !== event.pointerId) {
      return;
    }
    if (!press.moved && Math.abs(event.clientX - press.startX) < CLICK_SLOP) {
      return;
    }
    if (!press.moved) {
      press.moved = true;
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (zoomed && base && view) {
      const dt = ((press.lastX - event.clientX) / Math.max(1, plotRight - plotLeft)) * (view.end - view.start);
      setZoom(clampTimeWindow({ start: view.start + dt, end: view.end + dt }, base));
    }
    press.lastX = event.clientX;
  };

  const onPointerUp = (event: ReactPointerEvent<SVGRectElement>) => {
    const press = pressRef.current;
    if (!press || press.pointerId !== event.pointerId) {
      return;
    }
    pressRef.current = null;
    if (press.moved) {
      event.currentTarget.releasePointerCapture(event.pointerId);
      return;
    }
    const at = pointAt(event.clientX);
    if (at && onSeek) {
      onSeek(at.t);
    }
  };

  const valueText = shownValue ? `${formatAxisTick(shownValue.y, valueDecimals)}${unit ? ` ${unit}` : ""}` : "-";
  const heading = unit ? `${title} (${unit})` : title;

  return (
    <div className="metrics-chart-panel">
      <div className="metrics-chart-header">
        <h3 className="metrics-chart-title">{heading}</h3>
        <div className="metrics-chart-header-actions">
          {zoomed ? (
            <button type="button" className="link-btn metrics-chart-reset-btn" onClick={() => setZoom(null)} title={`Show the whole run on the ${title} chart`}>
              Whole run
            </button>
          ) : null}
          <span className="metrics-chart-latest" title={cursor === null ? "Latest value" : "Value at the play head"}>
            {valueText}
          </span>
        </div>
      </div>
      <div className="metrics-chart-plot" ref={hostRef}>
      {points.length === 0 ? (
        <p className="meta metrics-chart-empty">Not reported for this pair.</p>
      ) : !view || !xScale ? (
        <p className="meta metrics-chart-empty">One sample at {formatClock(points[0]!.t)}: the chart fills once there are trajectories.</p>
      ) : (
        <svg
          ref={svgRef}
          className={`metrics-chart-svg${zoomed ? " metrics-chart-svg--zoomed" : ""}`}
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="img"
          aria-label={`${title} over time for ${seriesLabel}`}
        >
          <defs>
            <clipPath id={`${clipId}-plot`}>
              <rect x={plotLeft} y={plotTop - 4} width={plotRight - plotLeft} height={plotBottom - plotTop + 8} />
            </clipPath>
            <clipPath id={`${clipId}-past`}>
              <rect x={plotLeft} y={plotTop - 4} width={Math.max(0, (cursorX ?? (cursor !== null && view && cursor > view.end ? plotRight : plotLeft)) - plotLeft)} height={plotBottom - plotTop + 8} />
            </clipPath>
          </defs>

          <rect x={plotLeft} y={plotTop} width={plotRight - plotLeft} height={plotBottom - plotTop} className="metrics-chart-plot-bg" />

          {yScale.ticks.map((tick) => (
            <g key={`y-${tick}`}>
              <line x1={plotLeft} y1={yAt(tick)} x2={plotRight} y2={yAt(tick)} className="metrics-chart-grid-line" />
              <text x={plotLeft - 6} y={yAt(tick)} className="metrics-chart-tick" textAnchor="end" dominantBaseline="middle">
                {formatCompactTick(tick, yDecimals)}
              </text>
            </g>
          ))}

          {xScale.ticks.map((tick) => (
            <text key={`x-${tick}`} x={xAt(tick)} y={plotBottom + 15} className="metrics-chart-tick" textAnchor="middle">
              {formatClock(tick)}
            </text>
          ))}

          <g clipPath={`url(#${clipId}-plot)`}>
            <path d={linePath} fill="none" stroke={accentColor} strokeWidth={1.5} strokeLinejoin="round" className="metrics-chart-line metrics-chart-line--ahead" />
            {cursor !== null ? (
              <path d={linePath} fill="none" stroke={accentColor} strokeWidth={2} strokeLinejoin="round" clipPath={`url(#${clipId}-past)`} className="metrics-chart-line" />
            ) : null}
            {cursorX !== null ? <line x1={cursorX} y1={plotTop} x2={cursorX} y2={plotBottom} className="metrics-chart-cursor" /> : null}
            {cursorX !== null && atCursor ? (
              <circle cx={xAt(atCursor.t)} cy={yAt(atCursor.y)} r={3.5} fill={accentColor} stroke="var(--chart-point-ring)" strokeWidth={1.5} />
            ) : null}
            {hover ? (
              <>
                <line x1={hover.px} y1={plotTop} x2={hover.px} y2={plotBottom} className="metrics-chart-crosshair" />
                <circle cx={hover.px} cy={yAt(hover.point.y)} r={4} fill={accentColor} stroke="var(--chart-hover-ring)" strokeWidth={1.5} />
              </>
            ) : null}
          </g>

          <rect
            x={plotLeft}
            y={plotTop}
            width={plotRight - plotLeft}
            height={plotBottom - plotTop}
            className="metrics-chart-interaction-layer"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => {
              pressRef.current = null;
            }}
            onPointerLeave={() => setHover(null)}
            onDoubleClick={() => setZoom(null)}
          />

          {hover ? (
            <g className="metrics-chart-tooltip" pointerEvents="none">
              <rect x={Math.min(hover.px + 8, plotRight - 96)} y={plotTop + 2} width={92} height={32} rx={4} className="metrics-chart-tooltip-box" />
              <text x={Math.min(hover.px + 14, plotRight - 90)} y={plotTop + 15} className="metrics-chart-tooltip-label">
                {formatClock(hover.point.t)}
              </text>
              <text x={Math.min(hover.px + 14, plotRight - 90)} y={plotTop + 29} className="metrics-chart-tooltip-label">
                {formatAxisTick(hover.point.y, valueDecimals)}
                {unit ? ` ${unit}` : ""}
              </text>
            </g>
          ) : null}
        </svg>
      )}
      </div>
    </div>
  );
}

/** The index of the point nearest to `t` (points sorted by time). */
function nearestIndex(points: MetricSeriesPoint[], t: number): number {
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid]!.t < t) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  if (lo > 0 && Math.abs(points[lo - 1]!.t - t) <= Math.abs(points[lo]!.t - t)) {
    return lo - 1;
  }
  return lo;
}
