import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { formatRelationId } from "../monitor/actorNameFormat";
import { buildNiceScale, formatAxisTick } from "./metricChartScale";
import {
  computeBaseDomain,
  dataDeltaFromPixelDelta,
  isViewportZoomed,
  panViewport,
  pixelToData,
  zoomViewportAt,
  type ChartDomain,
  type MetricSeriesPoint,
} from "./metricChartViewport";

export type { MetricSeriesPoint };

export interface MetricTimeSeriesChartProps {
  title: string;
  unit: string;
  points: MetricSeriesPoint[];
  relationId: string;
  yDomain?: [number, number];
  yDecimals?: number;
  valueDecimals?: number;
  accentColor?: string;
}

const CHART_WIDTH = 400;
const CHART_HEIGHT = 200;
const MARGIN = { top: 14, right: 14, bottom: 36, left: 48 };
const ZOOM_IN_FACTOR = 0.82;
const ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR;

function scaleLinear(value: number, domainMin: number, domainMax: number, rangeMin: number, rangeMax: number) {
  if (domainMax === domainMin) {
    return (rangeMin + rangeMax) / 2;
  }
  const ratio = (value - domainMin) / (domainMax - domainMin);
  return rangeMin + ratio * (rangeMax - rangeMin);
}

function clientToSvg(svg: SVGSVGElement, clientX: number, clientY: number) {
  const rect = svg.getBoundingClientRect();
  return {
    x: ((clientX - rect.left) / rect.width) * CHART_WIDTH,
    y: ((clientY - rect.top) / rect.height) * CHART_HEIGHT,
  };
}

function buildChartGeometry(domain: ChartDomain, points: MetricSeriesPoint[]) {
  const plotWidth = CHART_WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
  const plotBottom = MARGIN.top + plotHeight;
  const plotRight = MARGIN.left + plotWidth;

  const xScale = buildNiceScale(domain.xMin, domain.xMax, 5);
  const yScale = buildNiceScale(domain.yMin, domain.yMax, 5);

  const xAt = (t: number) => scaleLinear(t, xScale.min, xScale.max, MARGIN.left, plotRight);
  const yAt = (y: number) => scaleLinear(y, yScale.min, yScale.max, plotBottom, MARGIN.top);

  const linePath = points
    .map((point, index) => {
      const x = xAt(point.t);
      const y = yAt(point.y);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  const areaPath =
    points.length > 0
      ? `${linePath} L ${xAt(points[points.length - 1]!.t).toFixed(2)} ${plotBottom} L ${xAt(points[0]!.t).toFixed(2)} ${plotBottom} Z`
      : "";

  const lastPoint = points[points.length - 1]!;
  const lastX = xAt(lastPoint.t);
  const lastY = yAt(lastPoint.y);

  return {
    plotWidth,
    plotHeight,
    plotBottom,
    plotRight,
    xScale,
    yScale,
    linePath,
    areaPath,
    lastPoint,
    lastX,
    lastY,
  };
}

export function MetricTimeSeriesChart({
  title,
  unit,
  points,
  relationId,
  yDomain,
  yDecimals = 1,
  valueDecimals = 1,
  accentColor = "#38bdf8",
}: MetricTimeSeriesChartProps) {
  const gradientId = useId();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panRef = useRef<{ pointerId: number; lastX: number; lastY: number } | null>(null);

  const baseDomain = useMemo(() => computeBaseDomain(points, yDomain), [points, yDomain]);
  const [viewport, setViewport] = useState<ChartDomain | null>(null);
  const [hover, setHover] = useState<{ px: number; py: number; t: number; y: number } | null>(null);

  useEffect(() => {
    setViewport(null);
    setHover(null);
  }, [baseDomain, points, yDomain]);

  const activeDomain = viewport ?? baseDomain;
  const chart = useMemo(
    () => (activeDomain ? buildChartGeometry(activeDomain, points) : null),
    [activeDomain, points]
  );

  const zoomed = baseDomain && activeDomain ? isViewportZoomed(activeDomain, baseDomain) : false;

  const resetZoom = useCallback(() => {
    setViewport(null);
    setHover(null);
  }, []);

  const applyZoom = useCallback(
    (clientX: number, clientY: number, zoomIn: boolean) => {
      if (!svgRef.current || !baseDomain || !activeDomain || !chart) {
        return;
      }
      const { x: px, y: py } = clientToSvg(svgRef.current, clientX, clientY);
      if (
        px < MARGIN.left ||
        px > chart.plotRight ||
        py < MARGIN.top ||
        py > chart.plotBottom
      ) {
        return;
      }
      const anchor = pixelToData(
        px,
        py,
        activeDomain,
        MARGIN.left,
        chart.plotRight,
        MARGIN.top,
        chart.plotBottom
      );
      const factor = zoomIn ? ZOOM_IN_FACTOR : ZOOM_OUT_FACTOR;
      setViewport(zoomViewportAt(activeDomain, baseDomain, anchor, factor));
    },
    [activeDomain, baseDomain, chart]
  );

  const onWheel = useCallback(
    (event: ReactWheelEvent<SVGRectElement>) => {
      event.preventDefault();
      event.stopPropagation();
      applyZoom(event.clientX, event.clientY, event.deltaY < 0);
    },
    [applyZoom]
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent<SVGRectElement>) => {
      if (!zoomed || !activeDomain || !baseDomain || !chart) {
        return;
      }
      event.currentTarget.setPointerCapture(event.pointerId);
      panRef.current = { pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY };
    },
    [activeDomain, baseDomain, chart, zoomed]
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<SVGRectElement>) => {
      if (!svgRef.current || !activeDomain || !chart) {
        return;
      }

      const { x: px, y: py } = clientToSvg(svgRef.current, event.clientX, event.clientY);
      const inPlot =
        px >= MARGIN.left &&
        px <= chart.plotRight &&
        py >= MARGIN.top &&
        py <= chart.plotBottom;

      if (inPlot) {
        const data = pixelToData(
          px,
          py,
          activeDomain,
          MARGIN.left,
          chart.plotRight,
          MARGIN.top,
          chart.plotBottom
        );
        setHover({ px, py, t: data.x, y: data.y });
      } else {
        setHover(null);
      }

      const pan = panRef.current;
      if (!pan || pan.pointerId !== event.pointerId || !baseDomain) {
        return;
      }

      const deltaPxX = event.clientX - pan.lastX;
      const deltaPxY = event.clientY - pan.lastY;
      pan.lastX = event.clientX;
      pan.lastY = event.clientY;

      const { deltaX, deltaY } = dataDeltaFromPixelDelta(
        deltaPxX,
        deltaPxY,
        activeDomain,
        chart.plotWidth,
        chart.plotHeight
      );
      setViewport(panViewport(activeDomain, baseDomain, deltaX, deltaY));
    },
    [activeDomain, baseDomain, chart]
  );

  const onPointerUp = useCallback((event: React.PointerEvent<SVGRectElement>) => {
    if (panRef.current?.pointerId === event.pointerId) {
      panRef.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  if (!chart || !activeDomain) {
    return (
      <div className="metrics-chart-panel">
        <div className="metrics-chart-header">
          <h3 className="metrics-chart-title">{title}</h3>
        </div>
        <p className="meta metrics-chart-empty">No data points</p>
      </div>
    );
  }

  const latestValue = chart.lastPoint.y;
  const yAxisLabel = unit ? `${title} (${unit})` : title;
  const nearestPoint = hover
    ? points.reduce<(typeof points)[number] | null>((best, point) => {
        if (!best) {
          return point;
        }
        return Math.abs(point.t - hover.t) < Math.abs(best.t - hover.t) ? point : best;
      }, null)
    : null;

  return (
    <div className="metrics-chart-panel">
      <div className="metrics-chart-header">
        <div className="metrics-chart-heading">
          <h3 className="metrics-chart-title">{title}</h3>
        </div>
        <div className="metrics-chart-header-actions">
          {zoomed ? (
            <button
              type="button"
              className="metrics-chart-reset-btn"
              onClick={resetZoom}
              aria-label={`Reset zoom on ${title} chart`}
            >
              Reset zoom
            </button>
          ) : null}
          <span className="metrics-chart-latest" title="Latest value at playhead">
            {formatAxisTick(latestValue, valueDecimals)}
            {unit ? ` ${unit}` : ""}
          </span>
        </div>
      </div>
      <svg
        ref={svgRef}
        className={`metrics-chart-svg${zoomed ? " metrics-chart-svg--zoomed" : ""}`}
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label={`${title} over time for relation ${formatRelationId(relationId)}`}
      >
        <title>{`${title}: ${formatRelationId(relationId)}`}</title>

        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accentColor} stopOpacity={0.28} />
            <stop offset="100%" stopColor={accentColor} stopOpacity={0.02} />
          </linearGradient>
          <clipPath id={`${gradientId}-plot`}>
            <rect
              x={MARGIN.left}
              y={MARGIN.top}
              width={chart.plotWidth}
              height={chart.plotHeight}
            />
          </clipPath>
        </defs>

        <rect
          x={MARGIN.left}
          y={MARGIN.top}
          width={chart.plotWidth}
          height={chart.plotHeight}
          className="metrics-chart-plot-bg"
        />

        {chart.yScale.ticks.map((tick) => {
          const y = scaleLinear(tick, chart.yScale.min, chart.yScale.max, chart.plotBottom, MARGIN.top);
          return (
            <g key={`y-grid-${tick}`}>
              <line
                x1={MARGIN.left}
                y1={y}
                x2={chart.plotRight}
                y2={y}
                className="metrics-chart-grid-line"
              />
              <text
                x={MARGIN.left - 8}
                y={y}
                className="metrics-chart-tick metrics-chart-tick--y"
                textAnchor="end"
                dominantBaseline="middle"
              >
                {formatAxisTick(tick, yDecimals)}
              </text>
            </g>
          );
        })}

        {chart.xScale.ticks.map((tick) => {
          const x = scaleLinear(tick, chart.xScale.min, chart.xScale.max, MARGIN.left, chart.plotRight);
          return (
            <g key={`x-grid-${tick}`}>
              <line
                x1={x}
                y1={MARGIN.top}
                x2={x}
                y2={chart.plotBottom}
                className="metrics-chart-grid-line metrics-chart-grid-line--vertical"
              />
              <text
                x={x}
                y={chart.plotBottom + 16}
                className="metrics-chart-tick metrics-chart-tick--x"
                textAnchor="middle"
              >
                {formatAxisTick(tick, 0)}
              </text>
            </g>
          );
        })}

        <line
          x1={MARGIN.left}
          y1={chart.plotBottom}
          x2={chart.plotRight}
          y2={chart.plotBottom}
          className="metrics-chart-axis"
        />
        <line
          x1={MARGIN.left}
          y1={MARGIN.top}
          x2={MARGIN.left}
          y2={chart.plotBottom}
          className="metrics-chart-axis"
        />

        <g clipPath={`url(#${gradientId}-plot)`}>
          {chart.areaPath ? (
            <path d={chart.areaPath} fill={`url(#${gradientId})`} stroke="none" />
          ) : null}

          <path
            d={chart.linePath}
            fill="none"
            stroke={accentColor}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className="metrics-chart-line"
          />

          <circle
            cx={chart.lastX}
            cy={chart.lastY}
            r={4}
            fill={accentColor}
            stroke="#0f172a"
            strokeWidth={1.5}
            className="metrics-chart-endpoint"
          />

          {hover && nearestPoint ? (
            <>
              <line
                x1={hover.px}
                y1={MARGIN.top}
                x2={hover.px}
                y2={chart.plotBottom}
                className="metrics-chart-crosshair"
              />
              <line
                x1={MARGIN.left}
                y1={scaleLinear(
                  nearestPoint.y,
                  chart.yScale.min,
                  chart.yScale.max,
                  chart.plotBottom,
                  MARGIN.top
                )}
                x2={chart.plotRight}
                y2={scaleLinear(
                  nearestPoint.y,
                  chart.yScale.min,
                  chart.yScale.max,
                  chart.plotBottom,
                  MARGIN.top
                )}
                className="metrics-chart-crosshair metrics-chart-crosshair--horizontal"
              />
              <circle
                cx={scaleLinear(
                  nearestPoint.t,
                  chart.xScale.min,
                  chart.xScale.max,
                  MARGIN.left,
                  chart.plotRight
                )}
                cy={scaleLinear(
                  nearestPoint.y,
                  chart.yScale.min,
                  chart.yScale.max,
                  chart.plotBottom,
                  MARGIN.top
                )}
                r={5}
                className="metrics-chart-hover-point"
                fill={accentColor}
                stroke="#f8fafc"
                strokeWidth={1.5}
              />
            </>
          ) : null}
        </g>

        <rect
          x={MARGIN.left}
          y={MARGIN.top}
          width={chart.plotWidth}
          height={chart.plotHeight}
          className="metrics-chart-interaction-layer"
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setHover(null)}
          onDoubleClick={resetZoom}
        />

        {hover && nearestPoint ? (
          <g className="metrics-chart-tooltip" pointerEvents="none">
            <rect
              x={Math.min(hover.px + 10, chart.plotRight - 108)}
              y={Math.max(MARGIN.top + 4, hover.py - 34)}
              width={104}
              height={30}
              rx={4}
              className="metrics-chart-tooltip-box"
            />
            <text
              x={Math.min(hover.px + 16, chart.plotRight - 102)}
              y={Math.max(MARGIN.top + 16, hover.py - 20)}
              className="metrics-chart-tooltip-label"
            >
              t={formatAxisTick(nearestPoint.t, 1)}s
            </text>
            <text
              x={Math.min(hover.px + 16, chart.plotRight - 102)}
              y={Math.max(MARGIN.top + 28, hover.py - 8)}
              className="metrics-chart-tooltip-label"
            >
              {formatAxisTick(nearestPoint.y, valueDecimals)}
              {unit ? ` ${unit}` : ""}
            </text>
          </g>
        ) : null}

        <text
          x={(MARGIN.left + chart.plotRight) / 2}
          y={CHART_HEIGHT - 6}
          className="metrics-chart-axis-label"
          textAnchor="middle"
        >
          Time (s)
        </text>

        <text
          x={12}
          y={(MARGIN.top + chart.plotBottom) / 2}
          className="metrics-chart-axis-label metrics-chart-axis-label--y"
          textAnchor="middle"
          transform={`rotate(-90, 12, ${(MARGIN.top + chart.plotBottom) / 2})`}
        >
          {yAxisLabel}
        </text>
      </svg>
    </div>
  );
}
