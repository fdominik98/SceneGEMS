/**
 * The name of each job type as people read it, the same on the Cluster page's slots, in the wizard's
 * resources and in the workbench's notices. A job type the console does not know shows as its id.
 */
const JOB_TYPE_LABELS: Record<string, string> = {
  design_space_exploration: "Design space exploration",
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
  "monitoring.post_hoc": "Post hoc monitoring",
  "calibration.deviation": "Repeat calibration",
};

export function jobTypeLabel(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType;
}
