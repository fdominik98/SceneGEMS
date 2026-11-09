import type { SimulationFrame } from "../../../domain/simulation/types";
import type { MetricSeriesPoint } from "./metricChartViewport";

export type MetricKey = "distanceByRelationId" | "dcpaByRelationId" | "tcpaByRelationId" | "dsIndexByRelationId";

/** A metric of one pair over the frames; frames that do not report it are left out rather than drawn as 0. */
export function seriesFromFrames(frames: SimulationFrame[], relationId: string, key: MetricKey): MetricSeriesPoint[] {
  const points: MetricSeriesPoint[] = [];
  for (const frame of frames) {
    const value = frame.metrics?.[key]?.[relationId];
    if (typeof value === "number" && Number.isFinite(value)) {
      points.push({ t: frame.timestamp, y: value });
    }
  }
  return points;
}
