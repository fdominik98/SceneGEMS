import type { WorkerNodeView } from "./schemas";

/**
 * The component catalog as the console reads it (`cluster/fingerprints/components.py`). A worker node
 * offers components: the vessel stack layers campaigns run and the subsystems. A job needs
 * components: a simulation every layer of every vessel's stack, any other job type its subsystem
 * component. A worker node runs a job when it has slots for the job type and every component the job
 * needs is usable there (its images match the control node's release).
 */

export const SIMULATION_JOB = "simulation";

/** Every component in catalog order. */
export const COMPONENTS = [
  "asv_system/replay",
  "asv_system/usv_navigation",
  "asv_system/mission_planner",
  "control_layer/none",
  "control_layer/ardupilot",
  "control_layer/custom",
  "simulation_layer/kinematic",
  "simulation_layer/ardupilot_sim",
  "simulation_layer/gazebo",
  "design_space_exploration",
  "scene_generation",
  "trajectory_generation",
  "monitoring",
  "calibration",
] as const;

const COMPONENT_LABELS: Record<string, string> = {
  "asv_system/replay": "Replay",
  "asv_system/usv_navigation": "USV Navigation",
  "asv_system/mission_planner": "Mission Planner",
  "control_layer/none": "No control layer",
  "control_layer/ardupilot": "ArduPilot",
  "control_layer/custom": "Custom controller",
  "simulation_layer/kinematic": "Kinematic layer",
  "simulation_layer/ardupilot_sim": "ArduPilot SITL",
  "simulation_layer/gazebo": "Gazebo",
  design_space_exploration: "Design space exploration",
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  monitoring: "Monitoring",
  calibration: "Calibration",
};

/** The subsystem component of each job type but the simulation (`JOB_TYPE_COMPONENTS`). */
export const JOB_TYPE_COMPONENTS: Record<string, string> = {
  design_space_exploration: "design_space_exploration",
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

/** The control layer a stack section's simulation layer implies when it names none (`campaign_config.IMPLIED_CONTROL_LAYERS`). */
const IMPLIED_CONTROL_LAYERS: Record<string, string> = { kinematic: "none", ardupilot_sim: "ardupilot", gazebo: "ardupilot" };

/** Replay on the layers for every vessel, and USV Navigation for the own ship in mode usv_navigation. */
function layerComponents(controlLayer: string, simulationLayer: string, mode: unknown): string[] {
  const replay = ["asv_system/replay", `control_layer/${controlLayer}`, `simulation_layer/${simulationLayer}`];
  return orderedComponents(mode === "usv_navigation" ? [...replay, "asv_system/usv_navigation"] : replay);
}

/**
 * The components a campaign run needs, from its stack section (`stage_graph.run_stack_components`):
 * its simulation layer (kinematic when it names none) with the control layer it names (custom) or
 * implies, replay for every vessel, and USV Navigation for the own ship in mode usv_navigation.
 */
export function runStackComponents(stack: unknown): string[] {
  if (field(stack, "attended") === true) {
    return attendedSetupComponents(field(stack, "simulation"));
  }
  const layer = field(stack, "simulation_layer");
  const simulationLayer = typeof layer === "string" && layer in IMPLIED_CONTROL_LAYERS ? layer : "kinematic";
  const controlLayer = field(stack, "control_layer") === "custom" ? "custom" : IMPLIED_CONTROL_LAYERS[simulationLayer];
  return layerComponents(controlLayer, simulationLayer, field(stack, "mode"));
}

/** The simulation layer of the workbench's simulator names (`workbench_stack_mapping.simulation_layer_from_simulator_type`). */
const SIMULATOR_LAYERS: Record<string, string> = { kinematic: "kinematic", "ardupilot sim": "ardupilot_sim", gazebo: "gazebo" };

/**
 * The components an attended run needs, from the workbench's setup (`AttendedSimulationPayload.vessel_stacks`): the
 * simulation layer, and every vessel's ASV system and control layer (the layer's own when a vessel names none).
 */
export function attendedSetupComponents(simulation: unknown): string[] {
  const simulator = field(simulation, "simulatorType");
  const layer = SIMULATOR_LAYERS[typeof simulator === "string" ? simulator.toLowerCase() : ""] ?? "kinematic";
  const connections = field(simulation, "connectionsByAgentId");
  const components = [`simulation_layer/${layer}`];
  for (const connection of Object.values(typeof connections === "object" && connections !== null ? connections : {})) {
    const asvSystem = field(connection, "asvSystem");
    const controlLayer = field(connection, "controlLayer");
    components.push(`asv_system/${typeof asvSystem === "string" ? asvSystem : "replay"}`, `control_layer/${typeof controlLayer === "string" ? controlLayer : IMPLIED_CONTROL_LAYERS[layer]}`);
  }
  return orderedComponents(components);
}

/** The components a simulation job payload needs, by its runner (`simulation_job.required_components`). */
export function simulationPayloadComponents(payload: unknown): string[] {
  const runner = field(payload, "runner");
  if (runner === "attended") {
    return attendedSetupComponents(field(payload, "simulation"));
  }
  const layer = field(payload, "simulation_layer");
  const mode = field(payload, "mode");
  if (runner === "ardupilot" && typeof layer === "string") {
    return layerComponents("ardupilot", layer, mode);
  }
  if (runner === "gazebo_custom") {
    return layerComponents("custom", "gazebo", mode);
  }
  return layerComponents("none", "kinematic", mode);
}

/** The components a job of the type needs; a simulation's come from its payload, the kinematic replay when there is none. */
export function jobComponents(jobType: string, payload?: unknown): string[] {
  if (jobType === SIMULATION_JOB) {
    return simulationPayloadComponents(payload);
  }
  const subsystem = JOB_TYPE_COMPONENTS[jobType];
  return subsystem === undefined ? [] : [subsystem];
}

/** The worker node's components whose images match the control node's release. */
export function usableComponents(workerNode: WorkerNodeView): Set<string> {
  return new Set(workerNode.components.filter((entry) => entry.state === "usable").map((entry) => entry.component));
}

/** The worker node's components whose images differ from the release: unusable until the worker node is updated. */
export function staleComponents(workerNode: WorkerNodeView): string[] {
  return workerNode.components.filter((entry) => entry.state === "out_of_date").map((entry) => entry.component);
}

/** Every component of the worker node is out of date, so the control node leases it nothing. */
export function isWhollyOutOfDate(workerNode: WorkerNodeView): boolean {
  return workerNode.components.length > 0 && workerNode.components.every((entry) => entry.state === "out_of_date");
}

/** The worker node has slots for the job type and lists every component (usable or not). */
export function listsJob(workerNode: WorkerNodeView, jobType: string, components: readonly string[]): boolean {
  const listed = new Set(workerNode.components.map((entry) => entry.component));
  return (workerNode.slots[jobType]?.slots ?? 0) > 0 && components.every((component) => listed.has(component));
}

/** The worker node has slots for the job type and every component usable, as the control node's claim matches it. */
export function offersJob(workerNode: WorkerNodeView, jobType: string, components: readonly string[]): boolean {
  const usable = usableComponents(workerNode);
  return (workerNode.slots[jobType]?.slots ?? 0) > 0 && components.every((component) => usable.has(component));
}

/** Components in a sentence: "Replay, ArduPilot and Gazebo". */
export function describeComponents(components: readonly string[]): string {
  const labels = orderedComponents(components).map(componentLabel);
  return labels.length <= 1 ? (labels[0] ?? "") : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}
