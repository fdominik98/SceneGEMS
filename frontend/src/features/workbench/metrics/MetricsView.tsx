import { useMemo } from "react";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { ActorNamesProvider } from "../monitor/actorNameFormat";
import { buildActorNameMap, formatRelationId } from "../monitor/actorNames";
import { MetricTimeSeriesChart } from "./MetricTimeSeriesChart";
import { seriesFromFrames, type MetricKey } from "./metricSeries";
import { collectRelationIds } from "./metricsRelations";

const CHARTS: { key: MetricKey; title: string; unit: string; accent: string; yDomain?: [number, number]; valueDecimals?: number }[] = [
  { key: "distanceByRelationId", title: "Distance", unit: "m", accent: "var(--accent)" },
  { key: "dcpaByRelationId", title: "DCPA", unit: "m", accent: "var(--chart-series-1)" },
  { key: "tcpaByRelationId", title: "TCPA", unit: "s", accent: "var(--chart-series-2)" },
  { key: "dsIndexByRelationId", title: "DS index", unit: "", accent: "var(--chart-series-3)", yDomain: [0, 1], valueDecimals: 3 },
];

interface MetricsViewProps {
  /** Every frame of the shown stream, sorted by time. */
  frames: SimulationFrame[];
  /** The play head (seconds). */
  cursor: number | null;
  relationId: string | null;
  onRelationIdChange: (id: string) => void;
  /** Moves the play head (a click on a chart). */
  onSeek?: (t: number) => void;
}

/**
 * The charts of a vessel pair's metrics over the whole stream, with the play head and the
 * values at it.
 */
export function MetricsView({ frames, cursor, relationId, onRelationIdChange, onSeek }: MetricsViewProps) {
  const relationOptions = useMemo(() => collectRelationIds(frames), [frames]);
  const latestActors = frames[frames.length - 1]?.actors;
  const actorNames = useMemo(() => buildActorNameMap(latestActors), [latestActors]);
  const activeRelation = relationId && relationOptions.includes(relationId) ? relationId : (relationOptions[0] ?? null);

  const series = useMemo(
    () => (activeRelation ? CHARTS.map((chart) => seriesFromFrames(frames, activeRelation, chart.key)) : []),
    [activeRelation, frames]
  );

  if (frames.length === 0) {
    return <p className="meta metrics-empty">No frames yet: the charts appear once trajectories are loaded.</p>;
  }

  if (!activeRelation) {
    return <p className="meta metrics-empty">No vessel pairs in this stream.</p>;
  }

  const pairLabel = formatRelationId(activeRelation, actorNames);

  return (
    <div className="metrics-section metrics-section--column">
      <div className="metrics-toolbar">
        <label>
          Pair
          <select value={activeRelation} onChange={(e) => onRelationIdChange(e.target.value)} aria-label="Vessel pair of the charts">
            {relationOptions.map((id) => (
              <option key={id} value={id}>
                {formatRelationId(id, actorNames)}
              </option>
            ))}
          </select>
        </label>
        <p className="meta metrics-hint">Click a chart to move the play head; Ctrl + wheel zooms the time axis.</p>
      </div>
      <ActorNamesProvider actors={latestActors}>
        <div className="metrics-grid metrics-grid--column">
          {CHARTS.map((chart, index) => (
            <MetricTimeSeriesChart
              key={chart.key}
              title={chart.title}
              unit={chart.unit}
              points={series[index] ?? []}
              cursor={cursor}
              seriesLabel={pairLabel}
              yDomain={chart.yDomain}
              valueDecimals={chart.valueDecimals}
              accentColor={chart.accent}
              onSeek={onSeek}
            />
          ))}
        </div>
      </ActorNamesProvider>
    </div>
  );
}
