import type { ActorKinematicState, SimulationFrame } from "../../domain/simulation/types";

/**
 * Builds per-actor polylines for the map: prefers server `trajectoriesByActorId` on the
 * current frame when present; otherwise stitches positions from `statesByActorId` across
 * buffered trajectory frames (so traces appear as chunks arrive).
 */
export function buildTrajectoryPathsByActor(
  frames: SimulationFrame[],
  currentFrame: SimulationFrame | null
): Record<string, ActorKinematicState[]> {
  const actors = currentFrame?.actors ?? [];
  const out: Record<string, ActorKinematicState[]> = {};

  for (const actor of actors) {
    const fromServer = currentFrame?.trajectoriesByActorId?.[actor.id];
    if (fromServer && fromServer.length >= 2) {
      out[actor.id] = fromServer;
      continue;
    }

    const points: ActorKinematicState[] = [];
    for (const f of frames) {
      const st = f.statesByActorId[actor.id];
      if (st) {
        points.push(st);
      }
    }
    if (points.length >= 2) {
      out[actor.id] = points;
    }
  }

  return out;
}
