import type { NodeView } from "../../domain/cluster/schemas";
import { QUEUE_DEPTH_DEFAULTS } from "./wizard/wizardState";

/**
 * What a campaign needs from the cluster and which nodes give it. It reads a campaign config as
 * the wizard builds it or as the master stores it (`execution.runs`, `trajectories.generator`,
 * `resources.nodes` and `required_labels`), so the wizard and the campaign page judge the same
 * way. A node counts the way the master's stall check counts it (`NodeAvailability.runs`):
 * online, up to date (the campaign pins the master's fingerprints), carrying every required label,
 * selected when the campaign names nodes, and offering the job type.
 */

export const KINEMATIC_JOB = "simulation.kinematic";
export const ARDUPILOT_SIM_JOB = "simulation.ardupilot_sim";
export const GAZEBO_JOB = "simulation.gazebo";

/** The job type of each queued stage, as `assurance/pipeline/stage_graph.py` STAGE_JOB_TYPES; a run on an ArduPilot stack simulates with `simulationJobType`. */
export const STAGE_JOB_TYPES: Record<string, string> = {
  generate_scene: "scene_generation",
  generate_trajectories: "trajectory_generation",
  simulate: KINEMATIC_JOB,
  monitor: "monitoring.post_hoc",
  calibrate: "calibration.deviation",
};

/** The job type of each ArduPilot layer (`stage_graph.ARDUPILOT_LAYER_JOB_TYPES`). */
const ARDUPILOT_LAYER_JOBS: Record<string, string> = { ardupilot_sim: ARDUPILOT_SIM_JOB, gazebo: GAZEBO_JOB };

/** The job type that simulates a run of this stack section (`stage_graph.simulation_job_type`): by the ArduPilot layer, else kinematic. */
export function simulationJobType(stack: unknown): string {
  const layer = typeof stack === "object" && stack !== null ? (stack as { simulation_layer?: unknown }).simulation_layer : undefined;
  return (typeof layer === "string" ? ARDUPILOT_LAYER_JOBS[layer] : undefined) ?? KINEMATIC_JOB;
}

const SIMULATED_WHERE: Record<string, string> = { [ARDUPILOT_SIM_JOB]: "on ArduPilot SITL", [GAZEBO_JOB]: "on Gazebo" };

const CAPABILITY_LABELS: Record<string, string> = {
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  "simulation.kinematic": "Kinematic simulation",
  "simulation.ardupilot_sim": "ArduPilot SITL simulation",
  "simulation.gazebo": "Gazebo simulation",
  "monitoring.post_hoc": "Post hoc monitoring",
  "calibration.deviation": "Repeat calibration",
};

/** A job type as a capability name ("Kinematic simulation"). */
export function capabilityLabel(jobType: string): string {
  return CAPABILITY_LABELS[jobType] ?? jobType;
}

/** The config's run defaults (`RunConfig`). */
const DEFAULT_MONITOR = "post_hoc";
const DEFAULT_REPEATS = 1;

export interface RequiredCapability {
  /** The job type a node must offer. */
  jobType: string;
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

const CHAIN_ORDER = ["scene_generation", "trajectory_generation", "simulation"];

/** The steps a config runs: its `steps` (format 2), else the whole chain (format 1). */
function stepsOf(config: Record<string, unknown>): string[] {
  return Array.isArray(config.steps) ? config.steps.filter((step): step is string => typeof step === "string") : CHAIN_ORDER;
}

function monitorOf(config: Record<string, unknown>, section: string): unknown {
  return (config[section] as { monitor?: unknown } | undefined)?.monitor;
}

/** The job types the campaign's cases run, in pipeline order, each with why it is needed. */
export function requiredCapabilities(config: Record<string, unknown>): RequiredCapability[] {
  const steps = stepsOf(config);
  const runs = steps.includes("simulation") ? runsOf(config) : [];
  const generator = (config.trajectories as { generator?: unknown } | undefined)?.generator;
  const required: RequiredCapability[] = [];
  if (steps.includes("scene_generation")) {
    required.push({ jobType: STAGE_JOB_TYPES.generate_scene, stage: "generate_scene", reason: "Every case starts with a generated scene." });
  }
  if (steps.includes("trajectory_generation")) {
    required.push({
      jobType: STAGE_JOB_TYPES.generate_trajectories,
      stage: "generate_trajectories",
      reason: typeof generator === "string" ? `Every case plans its trajectories (${generator.replace(/_/g, " ")}).` : "Every case plans its trajectories.",
    });
  }
  const simulators = [...new Set(runs.map((run) => simulationJobType(run.stack)))];
  for (const jobType of simulators) {
    const names = runs.map((run, index) => (simulationJobType(run.stack) === jobType ? runName(run, index) : null)).filter((name): name is string => name !== null);
    const where = SIMULATED_WHERE[jobType] ?? "on the kinematic layer";
    required.push({
      jobType,
      stage: "simulate",
      reason:
        simulators.length > 1
          ? `${listed(names)} ${names.length === 1 ? "is" : "are"} simulated ${where}.`
          : runs.length === 1
            ? `The run is simulated${jobType !== KINEMATIC_JOB ? ` ${where}` : ""}.`
            : `Each of the ${runs.length} runs is simulated${jobType !== KINEMATIC_JOB ? ` ${where}` : ""}.`,
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
    required.push({ jobType: STAGE_JOB_TYPES.monitor, stage: "monitor", reason: `The post hoc monitor judges ${listed(judged)}.` });
  }
  const repeated = runs.map((run, index) => (Number(run.repeats ?? DEFAULT_REPEATS) > 1 ? runName(run, index) : null)).filter((name): name is string => name !== null);
  if (repeated.length > 0) {
    required.push({ jobType: STAGE_JOB_TYPES.calibrate, stage: "calibrate", reason: `The repeats of ${listed(repeated)} are compared.` });
  }
  return required;
}

/** Why a node cannot take the campaign's jobs now, or an empty list when it can. */
export function nodeProblems(node: NodeView, labels: Readonly<Record<string, string>>): string[] {
  const problems: string[] = [];
  if (node.status !== "online") {
    problems.push(node.status === "draining" ? "Draining: it takes no new jobs." : "Offline.");
  }
  if (node.out_of_date) {
    problems.push("Out of date: its images differ from the master's release.");
  }
  const missing = Object.entries(labels).filter(([key, value]) => node.labels[key] !== value);
  if (missing.length > 0) {
    problems.push(`Lacks the label${missing.length === 1 ? "" : "s"} ${missing.map(([key, value]) => `${key}=${value}`).join(", ")}.`);
  }
  return problems;
}

/** The nodes a campaign may use: every node, or the selected ones. */
export interface NodeSelection {
  /** Node ids, or null for every node (also those that join later). */
  nodes: readonly string[] | null;
  labels: Readonly<Record<string, string>>;
}

export interface CapabilityCoverage {
  capability: RequiredCapability;
  /** The campaign's usable nodes that offer it. */
  nodes: NodeView[];
  /** Their slots for the job type. */
  slots: number;
}

export interface ResourcePlan {
  required: RequiredCapability[];
  coverage: CapabilityCoverage[];
  /** Required capabilities no usable node of the campaign offers: the campaign cannot start. */
  missing: RequiredCapability[];
  /** The campaign's nodes that can take jobs now. */
  usable: NodeView[];
  /** Selected node ids the master does not list. */
  unknownNodes: string[];
}

export function isSelected(node: NodeView, selection: NodeSelection): boolean {
  return selection.nodes === null || selection.nodes.includes(node.node_id);
}

export function planResources(required: readonly RequiredCapability[], nodes: readonly NodeView[], selection: NodeSelection): ResourcePlan {
  const usable = nodes.filter((node) => isSelected(node, selection) && nodeProblems(node, selection.labels).length === 0);
  const coverage = required.map((capability) => {
    const offering = usable.filter((node) => (node.capabilities[capability.jobType]?.slots ?? 0) > 0);
    return { capability, nodes: offering, slots: offering.reduce((total, node) => total + node.capabilities[capability.jobType].slots, 0) };
  });
  const known = new Set(nodes.map((node) => node.node_id));
  return {
    required: [...required],
    coverage,
    missing: coverage.filter((entry) => entry.nodes.length === 0).map((entry) => entry.capability),
    usable,
    unknownNodes: selection.nodes === null ? [] : selection.nodes.filter((id) => !known.has(id)),
  };
}

/** Slots per job type over the nodes that can take the campaign's jobs now. */
export function slotsByJobType(nodes: readonly NodeView[], labels: Readonly<Record<string, string>> = {}): Record<string, number> {
  const slots: Record<string, number> = {};
  for (const node of nodes) {
    if (nodeProblems(node, labels).length > 0) {
      continue;
    }
    for (const [jobType, usage] of Object.entries(node.capabilities)) {
      slots[jobType] = (slots[jobType] ?? 0) + usage.slots;
    }
  }
  return slots;
}

/**
 * The queue caps of full usage: each stage may hold as many queued jobs as the cluster has slots
 * for its job type, never fewer than the config's default. A new case starts only while every
 * stage is below its cap, so with caps below the slot count a large cluster waits for work. The
 * simulate stage counts the slots of every simulation job type the runs use (kinematic by default).
 */
export function fullUsageQueueDepth(slots: Readonly<Record<string, number>>, simulationJobTypes: readonly string[] = [KINEMATIC_JOB]): Record<string, number> {
  const slotsOf = (stage: string) =>
    stage === "simulate" ? simulationJobTypes.reduce((total, jobType) => total + (slots[jobType] ?? 0), 0) : (slots[STAGE_JOB_TYPES[stage]] ?? 0);
  return Object.fromEntries(Object.entries(QUEUE_DEPTH_DEFAULTS).map(([stage, depth]) => [stage, Math.max(depth, slotsOf(stage))]));
}

/** The simulation job types among a plan's required capabilities. */
export function simulationJobTypesOf(required: readonly RequiredCapability[]): string[] {
  const types = required.filter((capability) => capability.stage === "simulate").map((capability) => capability.jobType);
  return types.length > 0 ? types : [KINEMATIC_JOB];
}

function stringsOf(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"));
}

/** The plan of a stored campaign config: its runs, and the nodes and labels of its `resources` (no nodes: every node). */
export function planOfConfig(config: Record<string, unknown>, nodes: readonly NodeView[]): ResourcePlan {
  const resources = (config.resources ?? {}) as { nodes?: unknown; required_labels?: unknown };
  const named = Array.isArray(resources.nodes) ? resources.nodes.filter((id): id is string => typeof id === "string") : [];
  return planResources(requiredCapabilities(config), nodes, { nodes: named.length > 0 ? named : null, labels: stringsOf(resources.required_labels) });
}

/** Why the campaign cannot start, or null when every required capability has a usable node. */
export function startBlocker(plan: ResourcePlan | null): string | null {
  if (plan === null) {
    return "The cluster's machines are not known yet.";
  }
  if (plan.missing.length === 0) {
    return null;
  }
  const names = plan.missing.map((capability) => capabilityLabel(capability.jobType).toLowerCase());
  return `No usable machine of the campaign runs ${listed(names)}.`;
}
