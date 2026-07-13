import type { SimulationFrame } from "../../domain/simulation/types";

export interface ActorPositionDelta {
  actorId: string;
  actorName: string;
  preview: { x: number; y: number } | null;
  simulation: { x: number; y: number } | null;
  distanceM: number | null;
}

export interface ScenarioDiffSummary {
  previewTimestamp: number | null;
  simulationTimestamp: number | null;
  actorDeltas: ActorPositionDelta[];
  ruleMismatchCount: number;
}

export function computeScenarioDiff(
  previewFrame: SimulationFrame | null,
  simulationFrame: SimulationFrame | null
): ScenarioDiffSummary {
  if (!previewFrame && !simulationFrame) {
    return {
      previewTimestamp: null,
      simulationTimestamp: null,
      actorDeltas: [],
      ruleMismatchCount: 0,
    };
  }

  const actorIds = new Set<string>();
  for (const a of previewFrame?.actors ?? []) actorIds.add(a.id);
  for (const a of simulationFrame?.actors ?? []) actorIds.add(a.id);

  const actorDeltas: ActorPositionDelta[] = [];
  for (const actorId of actorIds) {
    const previewActor = previewFrame?.actors.find((a) => a.id === actorId);
    const simActor = simulationFrame?.actors.find((a) => a.id === actorId);
    const previewState = previewFrame?.statesByActorId[actorId];
    const simState = simulationFrame?.statesByActorId[actorId];
    const previewPos = previewState ? { x: previewState.x, y: previewState.y } : null;
    const simPos = simState ? { x: simState.x, y: simState.y } : null;
    let distanceM: number | null = null;
    if (previewPos && simPos) {
      const dx = previewPos.x - simPos.x;
      const dy = previewPos.y - simPos.y;
      distanceM = Math.hypot(dx, dy);
    }
    actorDeltas.push({
      actorId,
      actorName: previewActor?.name ?? simActor?.name ?? actorId,
      preview: previewPos,
      simulation: simPos,
      distanceM,
    });
  }

  actorDeltas.sort((a, b) => (b.distanceM ?? 0) - (a.distanceM ?? 0));

  const previewRules = new Map(
    (previewFrame?.ruleResults ?? []).map((r) => [r.relationId, r.overallStatus])
  );
  let ruleMismatchCount = 0;
  for (const row of simulationFrame?.ruleResults ?? []) {
    const previewStatus = previewRules.get(row.relationId);
    if (previewStatus !== undefined && previewStatus !== row.overallStatus) {
      ruleMismatchCount += 1;
    }
  }

  return {
    previewTimestamp: previewFrame?.timestamp ?? null,
    simulationTimestamp: simulationFrame?.timestamp ?? null,
    actorDeltas,
    ruleMismatchCount,
  };
}
