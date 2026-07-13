import type { SimulationFrame } from "../../domain/simulation/types";

export function collectRelationIds(frames: SimulationFrame[]): string[] {
  const ids = new Set<string>();
  for (const frame of frames) {
    for (const ctx of frame.situationContexts) {
      ids.add(ctx.relationId);
    }
    for (const row of frame.ruleResults) {
      ids.add(row.relationId);
    }
    if (frame.metrics?.distanceByRelationId) {
      for (const key of Object.keys(frame.metrics.distanceByRelationId)) {
        ids.add(key);
      }
    }
  }
  return Array.from(ids).sort((a, b) => a.localeCompare(b));
}

export function pickDefaultRelationId(frames: SimulationFrame[]): string | null {
  const ids = collectRelationIds(frames);
  if (ids.length === 0) return null;
  const ownShipPair = ids.find((id) => id.includes("own_ship"));
  return ownShipPair ?? ids[0] ?? null;
}
