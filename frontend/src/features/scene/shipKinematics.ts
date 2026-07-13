import type { ActorKinematicState } from "../../domain/simulation/types";

export function getVelocityComponents(state: ActorKinematicState, scale = 3): { dx: number; dy: number } {
  return {
    dx: Math.cos(state.heading) * state.speed * scale,
    dy: Math.sin(state.heading) * state.speed * scale,
  };
}

export function getRenderHeading(state: ActorKinematicState): number {
  if (Math.abs(state.speed) < 1e-9) {
    return state.heading;
  }
  const { dx, dy } = getVelocityComponents(state, 1);
  return Math.atan2(dy, dx);
}
