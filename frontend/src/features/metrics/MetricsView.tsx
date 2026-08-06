import { useMemo } from "react";
import type { SimulationFrame } from "../../domain/simulation/types";
import { formatRelationId } from "../monitor/actorNameFormat";
import { MetricTimeSeriesChart } from "./MetricTimeSeriesChart";
import { collectRelationIds } from "./metricsRelations";

type MetricKey = keyof NonNullable<SimulationFrame["metrics"]>;

function seriesFromFrames(
  frames: SimulationFrame[],
  relationId: string,
  key: MetricKey
) {
  return frames.map((f) => ({
    t: f.timestamp,
    y: (f.metrics?.[key] as Record<string, number> | undefined)?.[relationId] ?? 0,
  }));
}

interface MetricsViewProps {
  frames: SimulationFrame[];
  relationId: string | null;
  onRelationIdChange: (id: string) => void;
}

export function MetricsView({ frames, relationId, onRelationIdChange }: MetricsViewProps) {

  const relationOptions = useMemo(() => collectRelationIds(frames), [frames]);
  const activeRelation =
    relationId && relationOptions.includes(relationId)
      ? relationId
      : (relationOptions[0] ?? null);

  const distance = useMemo(
    () => (activeRelation ? seriesFromFrames(frames, activeRelation, "distanceByRelationId") : []),
    [frames, activeRelation]
  );
  const dcpa = useMemo(
    () => (activeRelation ? seriesFromFrames(frames, activeRelation, "dcpaByRelationId") : []),
    [frames, activeRelation]
  );
  const tcpa = useMemo(
    () => (activeRelation ? seriesFromFrames(frames, activeRelation, "tcpaByRelationId") : []),
    [frames, activeRelation]
  );
  const ds = useMemo(
    () => (activeRelation ? seriesFromFrames(frames, activeRelation, "dsIndexByRelationId") : []),
    [frames, activeRelation]
  );

  if (frames.length === 0) {
    return (
      <p className="meta metrics-empty">No trajectory frames yet: metrics appear after playback data arrives.</p>
    );
  }

  if (!activeRelation) {
    return <p className="meta metrics-empty">No COLREGS relations in the current stream.</p>;
  }

  const latest = frames[frames.length - 1];
  const metrics = latest?.metrics;

  return (
    <div className="metrics-section metrics-section--column">
      <div className="toolbar-row metrics-toolbar">
        <label>
          Relation
          <select
            value={activeRelation}
            onChange={(e) => onRelationIdChange(e.target.value)}
            aria-label="Select relation for metrics"
          >
            {relationOptions.map((id) => (
              <option key={id} value={id}>
                {formatRelationId(id)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <table className="metrics-values-table" aria-label="Latest metric values">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Distance</td>
            <td>{metrics?.distanceByRelationId?.[activeRelation]?.toFixed(1) ?? "-"}</td>
          </tr>
          <tr>
            <td>DCPA</td>
            <td>{metrics?.dcpaByRelationId?.[activeRelation]?.toFixed(1) ?? "-"}</td>
          </tr>
          <tr>
            <td>TCPA</td>
            <td>{metrics?.tcpaByRelationId?.[activeRelation]?.toFixed(1) ?? "-"}</td>
          </tr>
          <tr>
            <td>DS index</td>
            <td>{metrics?.dsIndexByRelationId?.[activeRelation]?.toFixed(3) ?? "-"}</td>
          </tr>
        </tbody>
      </table>
      <div className="metrics-grid metrics-grid--column">
        <MetricTimeSeriesChart
          title="Distance"
          unit="m"
          points={distance}
          relationId={activeRelation}
        />
        <MetricTimeSeriesChart
          title="DCPA"
          unit="m"
          points={dcpa}
          relationId={activeRelation}
          accentColor="#22d3ee"
        />
        <MetricTimeSeriesChart
          title="TCPA"
          unit="s"
          points={tcpa}
          relationId={activeRelation}
          accentColor="#a78bfa"
        />
        <MetricTimeSeriesChart
          title="DS index"
          unit=""
          points={ds}
          relationId={activeRelation}
          yDomain={[0, 1]}
          yDecimals={2}
          valueDecimals={3}
          accentColor="#fbbf24"
        />
      </div>
    </div>
  );
}
