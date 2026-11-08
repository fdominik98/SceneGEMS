/**
 * The simulation never invents trajectories: a scenario loaded from a bare scene holds its
 * initial scene only, and the trajectories come from a trajectory generator. This is the
 * workflow's side of the backend's refusal, so the user is told before anything is sent.
 */
export const NO_TRAJECTORIES_MESSAGE =
  "Cannot simulate without trajectories: generate trajectories first (monitor-guided planner or straight) on the Trajectory Generation page, then load the result for simulation.";

/**
 * The reason a simulation cannot start on the loaded scenario, or null when it can.
 *
 * `trajectoryLength` is the span in seconds the backend reported when it loaded the
 * scenario. Null means no report yet, which is left to the backend to judge.
 */
export function missingTrajectoriesReason(trajectoryLength: number | null): string | null {
  return trajectoryLength !== null && trajectoryLength <= 0 ? NO_TRAJECTORIES_MESSAGE : null;
}
