import { describeComponents, isWhollyOutOfDate, JOB_TYPE_COMPONENTS, offersJob, runStackComponents, SIMULATION_JOB } from "../../domain/cluster/components";
import type { WorkerNodeView } from "../../domain/cluster/schemas";
import { QUEUE_DEPTH_DEFAULTS } from "./wizard/wizardState";

/**
 * What a campaign needs from the cluster and which worker nodes give it. It reads a campaign config as
 * the wizard builds it or as the control node stores it (`execution.runs`, `trajectories.generator`,
 * `resources.worker_nodes` and `required_labels`), so the wizard and the campaign page judge the same
 * way. A worker node counts the way the control node's stall check counts it (`WorkerNodeAvailability.runs`):
 * online, carrying every required label, selected when the campaign names worker nodes, with slots for
 * the job type and every component the job needs up to date (the campaign pins the control node's
 * fingerprints). Every run is a simulation job; its components are the layers of its vessels' stacks.
 */

/** Every run is simulated by the one simulation job type; the name stays for the wizard's queue caps. */
export const KINEMATIC_JOB = SIMULATION_JOB;

/** The job type of each queued stage, as `assurance/pipeline/stage_graph.py` STAGE_JOB_TYPES. */
export const STAGE_JOB_TYPES: Record<string, string> = {
  explore_design_space: "design_space_exploration",
  generate_scene: "scene_generation",
  generate_trajectories: "trajectory_generation",
  simulate: SIMULATION_JOB,
  monitor: "monitoring.post_hoc",
  calibrate: "calibration.deviation",
};

/** The job type that simulates a run of this stack section: the simulation, whatever the stack (`runStackComponents` tells the stacks apart). */
export function simulationJobType(stack: unknown): string {
  void stack;
  return SIMULATION_JOB;
}

const LAYER_WHERE: Record<string, string> = {
  "simulation_layer/kinematic": "on the kinematic layer",
  "simulation_layer/ardupilot_sim": "on ArduPilot SITL",
  "simulation_layer/gazebo": "on Gazebo",
};

/** Where runs with these components are simulated ("on Gazebo", "on the custom controller with Gazebo", "on the kinematic layer with USV Navigation"). */
function simulatedWhere(components: readonly string[]): string {
  const layer = components.find((component) => component.startsWith("simulation_layer/"));
  const layerWhere = (layer !== undefined ? LAYER_WHERE[layer] : undefined) ?? "on the kinematic layer";
  const where = components.includes("control_layer/custom") ? `on the custom controller with ${layerWhere.replace(/^on /, "")}` : layerWhere;
  return components.includes("asv_system/usv_navigation") ? `${where} with USV Navigation` : where;
}

const CAPABILITY_LABELS: Record<string, string> = {
  design_space_exploration: "Design space exploration",
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
  "monitoring.post_hoc": "Post hoc monitoring",
  "calibration.deviation": "Repeat calibration",
};

/** A job type as a capability name ("Simulation"). */
export function capabilityLabel(jobType: string): string {
  return CAPABILITY_LABELS[jobType] ?? jobType;
}

/** The config's run defaults (`RunConfig`). */
const DEFAULT_MONITOR = "post_hoc";
const DEFAULT_REPEATS = 1;

export interface RequiredCapability {
  /** The job type a worker node must have slots for. */
  jobType: string;
  /** The components a worker node must have up to date: the subsystem's, or a run's vessel stack layers. */
  components: string[];
  /** The queue depth stage of its jobs. */
  stage: string;
  /** Why the campaign needs it, in plain words. */
  reason: string;
}

interface RunLike {
  name?: unknown;
  stack?: unknown;
  monitor?: unknown;
  repeats?: unknown;
}

function runsOf(config: Record<string, unknown>): RunLike[] {
  const execution = config.execution as { runs?: unknown } | undefined;
  return Array.isArray(execution?.runs) ? (execution.runs as RunLike[]) : [];
}

function runName(run: RunLike, index: number): string {
  return typeof run.name === "string" && run.name.trim() ? run.name.trim() : `run ${index + 1}`;
}

function listed(names: string[]): string {
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The chain a format 1 config runs whole; the design space exploration came later and is never implied. */
const CHAIN_ORDER = ["scene_generation", "trajectory_generation", "simulation"];

/** The steps a config runs: its `steps` (format 2), else the whole chain (format 1). */
function stepsOf(config: Record<string, unknown>): string[] {
  return Array.isArray(config.steps) ? config.steps.filter((step): step is string => typeof step === "string") : CHAIN_ORDER;
}

function monitorOf(config: Record<string, unknown>, section: string): unknown {
  return (config[section] as { monitor?: unknown } | undefined)?.monitor;
}

/** How a reason names a trajectory generator; the stored id `monitor_driven_rrt` predates the planner's name. */
const GENERATOR_NAMES: Record<string, string> = { monitor_driven_rrt: "monitor-guided planner" };

function generatorName(generator: string): string {
  return GENERATOR_NAMES[generator] ?? generator.replace(/_/g, " ");
}

function subsystemNeed(stage: string, reason: string): RequiredCapability {
  const jobType = STAGE_JOB_TYPES[stage];
  return { jobType, components: [JOB_TYPE_COMPONENTS[jobType]], stage, reason };
}

/** The job types the campaign's cases run, in pipeline order, each with the components it needs and why; the runs give one need per distinct set of components. */
export function requiredCapabilities(config: Record<string, unknown>): RequiredCapability[] {
  const steps = stepsOf(config);
  const runs = steps.includes("simulation") ? runsOf(config) : [];
  const generator = (config.trajectories as { generator?: unknown } | undefined)?.generator;
  const required: RequiredCapability[] = [];
  if (steps.includes("design_space_exploration")) {
    required.push(subsystemNeed("explore_design_space", "The design space exploration finds the FECs the campaign runs."));
  }
  if (steps.includes("scene_generation")) {
    required.push(subsystemNeed("generate_scene", "Every case starts with a generated scene."));
  }
  if (steps.includes("trajectory_generation")) {
    required.push(
      subsystemNeed("generate_trajectories", typeof generator === "string" ? `Every case plans its trajectories (${generatorName(generator)}).` : "Every case plans its trajectories.")
    );
  }
  const runComponents = runs.map((run) => runStackComponents(run.stack));
  const sets = [...new Map(runComponents.map((components) => [components.join(","), components])).values()];
  for (const components of sets) {
    const key = components.join(",");
    const names = runs.map((run, index) => (runComponents[index].join(",") === key ? runName(run, index) : null)).filter((name): name is string => name !== null);
    const where = simulatedWhere(components);
    required.push({
      jobType: SIMULATION_JOB,
      components,
      stage: "simulate",
      reason:
        sets.length > 1
          ? `${listed(names)} ${names.length === 1 ? "is" : "are"} simulated ${where}.`
          : runs.length === 1
            ? `The run is simulated ${where}.`
            : `Each of the ${runs.length} runs is simulated ${where}.`,
    });
  }
  const judged: string[] = [];
  if (steps.includes("scene_generation") && monitorOf(config, "scene_generation") === "post_hoc") {
    judged.push("the generated scenes");
  }
  if (steps.includes("trajectory_generation") && monitorOf(config, "trajectories") === "post_hoc") {
    judged.push("the planned trajectories");
  }
  judged.push(...runs.map((run, index) => ((run.monitor ?? DEFAULT_MONITOR) === "post_hoc" ? runName(run, index) : null)).filter((name): name is string => name !== null));
  if (judged.length > 0) {
    required.push(subsystemNeed("monitor", `The post hoc monitor judges ${listed(judged)}.`));
  }
  const repeated = runs.map((run, index) => (Number(run.repeats ?? DEFAULT_REPEATS) > 1 ? runName(run, index) : null)).filter((name): name is string => name !== null);
  if (repeated.length > 0) {
    required.push(subsystemNeed("calibrate", `The repeats of ${listed(repeated)} are compared.`));
  }
  return required;
}

/** Why a worker node cannot take the campaign's jobs now, or an empty list when it can. */
export function workerNodeProblems(workerNode: WorkerNodeView, labels: Readonly<Record<string, string>>): string[] {
  const problems: string[] = [];
  if (workerNode.status !== "online") {
    problems.push(workerNode.status === "draining" ? "Draining: it takes no new jobs." : "Offline.");
  }
  if (isWhollyOutOfDate(workerNode)) {
    problems.push("Out of date: the images of all its components differ from the control node's release.");
  }
  const missing = Object.entries(labels).filter(([key, value]) => workerNode.labels[key] !== value);
  if (missing.length > 0) {
    problems.push(`Lacks the label${missing.length === 1 ? "" : "s"} ${missing.map(([key, value]) => `${key}=${value}`).join(", ")}.`);
  }
  return problems;
}

/** The worker nodes a campaign may use: every worker node, or the selected ones. */
export interface WorkerNodeSelection {
  /** Worker node ids, or null for every worker node (also those that join later). */
  workerNodes: readonly string[] | null;
  labels: Readonly<Record<string, string>>;
}

export interface CapabilityCoverage {
  capability: RequiredCapability;
  /** The campaign's usable worker nodes with slots for its job type and its components up to date. */
  workerNodes: WorkerNodeView[];
  /** Their slots for the job type. */
  slots: number;
}

export interface ResourcePlan {
  required: RequiredCapability[];
  coverage: CapabilityCoverage[];
  /** Required capabilities no usable worker node of the campaign offers: the campaign cannot start. */
  missing: RequiredCapability[];
  /** The campaign's worker nodes that can take jobs now. */
  usable: WorkerNodeView[];
  /** Selected worker node ids the control node does not list. */
  unknownWorkerNodes: string[];
}

export function isSelected(workerNode: WorkerNodeView, selection: WorkerNodeSelection): boolean {
  return selection.workerNodes === null || selection.workerNodes.includes(workerNode.worker_node_id);
}

export function planResources(required: readonly RequiredCapability[], workerNodes: readonly WorkerNodeView[], selection: WorkerNodeSelection): ResourcePlan {
  const usable = workerNodes.filter((workerNode) => isSelected(workerNode, selection) && workerNodeProblems(workerNode, selection.labels).length === 0);
  const coverage = required.map((capability) => {
    const offering = usable.filter((workerNode) => offersJob(workerNode, capability.jobType, capability.components));
    return { capability, workerNodes: offering, slots: offering.reduce((total, workerNode) => total + workerNode.slots[capability.jobType].slots, 0) };
  });
  const known = new Set(workerNodes.map((workerNode) => workerNode.worker_node_id));
  return {
    required: [...required],
    coverage,
    missing: coverage.filter((entry) => entry.workerNodes.length === 0).map((entry) => entry.capability),
    usable,
    unknownWorkerNodes: selection.workerNodes === null ? [] : selection.workerNodes.filter((id) => !known.has(id)),
  };
}

/** Slots per job type over the worker nodes that can take the campaign's jobs now. */
export function slotsByJobType(workerNodes: readonly WorkerNodeView[], labels: Readonly<Record<string, string>> = {}): Record<string, number> {
  const slots: Record<string, number> = {};
  for (const workerNode of workerNodes) {
    if (workerNodeProblems(workerNode, labels).length > 0) {
      continue;
    }
    for (const [jobType, usage] of Object.entries(workerNode.slots)) {
      slots[jobType] = (slots[jobType] ?? 0) + usage.slots;
    }
  }
  return slots;
}

/**
 * The queue caps of full usage: each stage may hold as many queued jobs as the cluster has slots
 * for its job type, never fewer than the config's default. A new case starts only while every
 * stage is below its cap, so with caps below the slot count a large cluster waits for work. The
 * simulate stage counts the slots of the simulation job types the runs use (the simulation).
 */
export function fullUsageQueueDepth(slots: Readonly<Record<string, number>>, simulationJobTypes: readonly string[] = [SIMULATION_JOB]): Record<string, number> {
  const slotsOf = (stage: string) =>
    stage === "simulate" ? [...new Set(simulationJobTypes)].reduce((total, jobType) => total + (slots[jobType] ?? 0), 0) : (slots[STAGE_JOB_TYPES[stage]] ?? 0);
  return Object.fromEntries(Object.entries(QUEUE_DEPTH_DEFAULTS).map(([stage, depth]) => [stage, Math.max(depth, slotsOf(stage))]));
}

/** The simulation job types among a plan's required capabilities. */
export function simulationJobTypesOf(required: readonly RequiredCapability[]): string[] {
  const types = [...new Set(required.filter((capability) => capability.stage === "simulate").map((capability) => capability.jobType))];
  return types.length > 0 ? types : [SIMULATION_JOB];
}

function stringsOf(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"));
}

/** The plan of a stored campaign config: its runs, and the worker nodes and labels of its `resources` (no worker nodes: every worker node). */
export function planOfConfig(config: Record<string, unknown>, workerNodes: readonly WorkerNodeView[]): ResourcePlan {
  const resources = (config.resources ?? {}) as { worker_nodes?: unknown; required_labels?: unknown };
  const named = Array.isArray(resources.worker_nodes) ? resources.worker_nodes.filter((id): id is string => typeof id === "string") : [];
  return planResources(requiredCapabilities(config), workerNodes, { workerNodes: named.length > 0 ? named : null, labels: stringsOf(resources.required_labels) });
}

/**
 * What a plan says, as text: the needs, the ids of the worker nodes covering each with their slots, the
 * missing needs, the usable and the unknown worker nodes. Plans with the same key show the same, whatever
 * the worker nodes' heartbeats changed in their views (`last_seen_at`, slots in use). Null has "".
 */
export function planKey(plan: ResourcePlan | null): string {
  if (plan === null) {
    return "";
  }
  return JSON.stringify({
    required: plan.required,
    coverage: plan.coverage.map((entry) => [needKey(entry.capability), entry.workerNodes.map((workerNode) => workerNode.worker_node_id), entry.slots]),
    missing: plan.missing.map(needKey),
    usable: plan.usable.map((workerNode) => workerNode.worker_node_id),
    unknown: plan.unknownWorkerNodes,
  });
}

/** Why the campaign cannot start, or null when every required capability has a usable worker node. */
export function startBlocker(plan: ResourcePlan | null): string | null {
  if (plan === null) {
    return "The cluster's machines are not known yet.";
  }
  if (plan.missing.length === 0) {
    return null;
  }
  const names = plan.missing.map(needLabel);
  return `No usable machine of the campaign runs ${listed(names)}.`;
}

/** A need's key: its stage and components, since a campaign whose runs mix stacks has one simulation need per component set. */
export function needKey(capability: RequiredCapability): string {
  return `${capability.stage}:${capability.components.join(",")}`;
}

/** A need in a sentence: the job type, and for a simulation the components it needs ("simulation with Replay, ArduPilot and Gazebo"). */
export function needLabel(capability: RequiredCapability): string {
  const name = capabilityLabel(capability.jobType).toLowerCase();
  return capability.stage === "simulate" ? `${name} with ${describeComponents(capability.components)}` : name;
}
