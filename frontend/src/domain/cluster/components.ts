import type { NodeView } from "./schemas";

/**
 * The component catalog as the console reads it (`cluster/fingerprints/components.py`). A node
 * offers components: the vessel stack layers campaigns run and the subsystems. A job needs
 * components: a simulation every layer of every vessel's stack, any other job type its subsystem
 * component. A node runs a job when it has slots for the job type and every component the job
 * needs is usable there (its images match the master's release).
 */

export const SIMULATION_JOB = "simulation";

/** Every component in catalog order. */
export const COMPONENTS = [
  "asv_software/replay",
  "asv_software/usv_navigation",
  "control_layer/none",
  "control_layer/ardupilot",
  "control_layer/custom",
  "simulation_layer/kinematic",
  "simulation_layer/ardupilot_sim",
  "simulation_layer/gazebo",
  "scene_generation",
  "trajectory_generation",
  "monitoring",
  "calibration",
] as const;

const COMPONENT_LABELS: Record<string, string> = {
  "asv_software/replay": "Replay",
  "asv_software/usv_navigation": "USV Navigation",
  "control_layer/none": "No control layer",
  "control_layer/ardupilot": "ArduPilot",
  "control_layer/custom": "Custom controller",
  "simulation_layer/kinematic": "Kinematic layer",
  "simulation_layer/ardupilot_sim": "ArduPilot SITL",
  "simulation_layer/gazebo": "Gazebo",
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  monitoring: "Monitoring",
  calibration: "Calibration",
};

/** The subsystem component of each job type but the simulation (`JOB_TYPE_COMPONENTS`). */
export const JOB_TYPE_COMPONENTS: Record<string, string> = {
  scene_generation: "scene_generation",
  trajectory_generation: "trajectory_generation",
  "monitoring.post_hoc": "monitoring",
  "calibration.deviation": "calibration",
};

/** A component as the operator reads it ("ArduPilot SITL"); an unknown id as it is. */
export function componentLabel(component: string): string {
  return COMPONENT_LABELS[component] ?? component;
}

/** The distinct components in catalog order, unknown ones last. */
export function orderedComponents(components: Iterable<string>): string[] {
  const order = (component: string) => {
    const index = (COMPONENTS as readonly string[]).indexOf(component);
    return index === -1 ? COMPONENTS.length : index;
  };
  return [...new Set(components)].sort((a, b) => order(a) - order(b) || a.localeCompare(b));
}

function field(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>)[key] : undefined;
}

const KINEMATIC_REPLAY = ["asv_software/replay", "control_layer/none", "simulation_layer/kinematic"];

function kinematicComponents(mode: unknown): string[] {
  return orderedComponents(mode === "usv_navigation" ? [...KINEMATIC_REPLAY, "asv_software/usv_navigation"] : KINEMATIC_REPLAY);
}

function ardupilotComponents(layer: string): string[] {
  return ["asv_software/replay", "control_layer/ardupilot", `simulation_layer/${layer}`];
}

/**
 * The components a campaign run needs, from its stack section (`stage_graph.run_stack_components`):
 * replay on ArduPilot for an ArduPilot layer, else the kinematic layer with replay, and USV
 * Navigation for the own ship in mode usv_navigation.
 */
export function runStackComponents(stack: unknown): string[] {
  const layer = field(stack, "simulation_layer");
  if (layer === "ardupilot_sim" || layer === "gazebo") {
    return ardupilotComponents(layer);
  }
  return kinematicComponents(field(stack, "mode"));
}

/** The components a simulation job payload needs, by its runner (`simulation_job.required_components`). */
export function simulationPayloadComponents(payload: unknown): string[] {
  const layer = field(payload, "simulation_layer");
  if (field(payload, "runner") === "ardupilot" && typeof layer === "string") {
    return ardupilotComponents(layer);
  }
  return kinematicComponents(field(payload, "mode"));
}

/** The components a job of the type needs; a simulation's come from its payload, the kinematic replay when there is none. */
export function jobComponents(jobType: string, payload?: unknown): string[] {
  if (jobType === SIMULATION_JOB) {
    return simulationPayloadComponents(payload);
  }
  const subsystem = JOB_TYPE_COMPONENTS[jobType];
  return subsystem === undefined ? [] : [subsystem];
}

/** The node's components whose images match the master's release. */
export function usableComponents(node: NodeView): Set<string> {
  return new Set(node.components.filter((entry) => entry.state === "usable").map((entry) => entry.component));
}

/** The node's components whose images differ from the release: unusable until the node is updated. */
export function staleComponents(node: NodeView): string[] {
  return node.components.filter((entry) => entry.state === "out_of_date").map((entry) => entry.component);
}

/** Every component of the node is out of date, so the master leases it nothing. */
export function isWhollyOutOfDate(node: NodeView): boolean {
  return node.components.length > 0 && node.components.every((entry) => entry.state === "out_of_date");
}

/** The node has slots for the job type and lists every component (usable or not). */
export function listsJob(node: NodeView, jobType: string, components: readonly string[]): boolean {
  const listed = new Set(node.components.map((entry) => entry.component));
  return (node.slots[jobType]?.slots ?? 0) > 0 && components.every((component) => listed.has(component));
}

/** The node has slots for the job type and every component usable, as the master's claim matches it. */
export function offersJob(node: NodeView, jobType: string, components: readonly string[]): boolean {
  const usable = usableComponents(node);
  return (node.slots[jobType]?.slots ?? 0) > 0 && components.every((component) => usable.has(component));
}

/** Components in a sentence: "Replay, ArduPilot and Gazebo". */
export function describeComponents(components: readonly string[]): string {
  const labels = orderedComponents(components).map(componentLabel);
  return labels.length <= 1 ? (labels[0] ?? "") : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}
