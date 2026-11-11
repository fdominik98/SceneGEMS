/**
 * The simulation never invents trajectories: a scenario loaded from a bare scene holds its
 * initial scene only, and the trajectories come from a trajectory generator. The workflow says
 * so before it creates a simulation job.
 */
export const NO_TRAJECTORIES_MESSAGE =
  "Cannot simulate without trajectories: generate trajectories first (monitor-guided planner or straight) on the Trajectory Generation page, then load the result for simulation.";
