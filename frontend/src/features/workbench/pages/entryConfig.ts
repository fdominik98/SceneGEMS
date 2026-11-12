import { formatLocalDateTime } from "../../../domain/localDateTime";
import { stringify } from "yaml";
import type { CampaignConfigFormat2, ConfigArtifactRef, InputItemSource, StepMonitor } from "../../../domain/cluster/campaignApi";
import type { ArtifactRef, CampaignOrigin } from "../../../domain/cluster/schemas";
import type { DesignSpaceSection } from "../../../domain/designSpace/designSpaceConfig";
import type { TrajectoryGenerationParamsWire } from "../../../domain/simulation/wireTypes";
import type { ClusterRunPlan } from "../cluster/simulationJobs";
import { defaultReferenceGeofence, type ReferenceGeofence } from "../connection/referenceGeofence";
import type { WorkbenchPage } from "./workbenchTarget";

/**
 * The config of a workbench entry (design doc 6.3): format 3 with one step, the page's input as
 * a functional scenario or an item, the step's monitor post-hoc so the page gets the monitor's
 * frames, the frames kept, and a fresh campaign seed so two runs of the same input differ.
 */

export const WORKBENCH_ORIGIN: Record<WorkbenchPage, CampaignOrigin> = {
  designSpaceExploration: "design_space_exploration",
  sceneGeneration: "scene_generation",
  trajectoryGeneration: "trajectory_generation",
  simulation: "simulation",
};

/** Campaign seeds are 31-bit (campaign_config.MAX_SEED). */
export const MAX_ENTRY_SEED = 2 ** 31 - 1;

export function newEntrySeed(random: () => number = Math.random): number {
  return Math.min(MAX_ENTRY_SEED, Math.floor(random() * (MAX_ENTRY_SEED + 1)));
}

/** A functional scenario's name in the config: no slash (its class id is `scenario/<name>`), 1 to 200 characters. */
export function scenarioInputName(label: string, taken: ReadonlySet<string> = new Set()): string {
  const base = label.replace(/\.problem$/i, "").replace(/[/\\]+/g, "_").trim().slice(0, 190) || "scenario";
  let name = base;
  for (let n = 2; taken.has(name); n += 1) {
    name = `${base}_${n}`;
  }
  return name;
}

/** The class id the control node gives a functional scenario of the input. */
export function scenarioClassId(name: string): string {
  return `scenario/${name}`;
}

/** How long a trajectory job waits for its search beyond the search's own timeout (as `workbenchJobs.ts`). */
const TRAJECTORY_REPLY_MARGIN_S = 120;
const DEFAULT_TRAJECTORY_TIMEOUT_S = 1800;

/** The wire keys of the search the config takes (`campaign_config.SEARCH_PARAM_KEYS`); the generator and the timespan have fields of their own. */
const SEARCH_PARAM_KEYS = [
  "timeStep",
  "timeout",
  "maxIterations",
  "directionThreshold",
  "bestRandomNodesK",
  "previewInterval",
  "includeMonitorResults",
] as const;

export interface DomainInput {
  colregsConstraintsContent: string;
  vesselTypesContent: string;
  obstacleTypesContent: string;
}

/** An artifact reference as the config writes it. */
export function configRef(ref: Pick<ArtifactRef, "sha256" | "size_bytes" | "kind" | "media_type" | "pointer">, overrides: Partial<ConfigArtifactRef> = {}): ConfigArtifactRef {
  return {
    sha256: ref.sha256,
    size_bytes: ref.size_bytes,
    kind: ref.kind,
    media_type: ref.media_type,
    pointer: ref.pointer ?? null,
    ...overrides,
  };
}

function entryPolicy(seed: number) {
  return { keep_frames: true, seed };
}

export interface DesignSpaceEntryInput {
  name: string;
  /** The metamodel and the well-formedness constraints. */
  specification: string;
  scope: string;
  /** Null for every FEC. */
  maxFecs: number | null;
  timeoutSeconds: number;
  seed: number;
}

/**
 * Design space exploration alone: no input and no scope (the FECs come from the exploration),
 * the specification inline. The exploration's FECs are closed at once and the entry completes.
 */
export function designSpaceEntryConfig(input: DesignSpaceEntryInput): CampaignConfigFormat2 {
  const section: DesignSpaceSection = {
    specification: input.specification,
    scope: input.scope.trim(),
    max_fecs: input.maxFecs === null ? null : Math.max(1, Math.round(input.maxFecs)),
    timeout_s: Math.max(1, Math.round(input.timeoutSeconds)),
  };
  return {
    format: 3,
    name: input.name,
    steps: ["design_space_exploration"],
    design_space_exploration: section,
    policy: entryPolicy(input.seed),
  };
}

export interface SceneEntryInput {
  name: string;
  scenarios: { name: string; ref: ConfigArtifactRef }[];
  domain: DomainInput;
  timeoutSeconds: number;
  enforceLowTcpa: boolean;
  seed: number;
  /** Post-hoc gives the page the monitored scene; none when no worker node monitors, so the case does not wait for it. */
  monitor?: StepMonitor;
}

/** Scene generation: one case per functional scenario (a batch is one entry with a scenario per row). */
export function sceneEntryConfig(input: SceneEntryInput): CampaignConfigFormat2 {
  return {
    format: 3,
    name: input.name,
    steps: ["scene_generation"],
    input: {
      functional_scenarios: input.scenarios.map((scenario) => ({ name: scenario.name, ref: scenario.ref, quota: 1, failure_budget: 0 })),
    },
    domain: {
      colregs_constants: input.domain.colregsConstraintsContent,
      vessel_types: input.domain.vesselTypesContent,
      obstacle_types: input.domain.obstacleTypesContent,
      scene_generation_timeout_s: Math.max(1, Math.round(input.timeoutSeconds)),
      enforce_low_tcpa: input.enforceLowTcpa,
    },
    scene_generation: { monitor: input.monitor ?? "post_hoc" },
    policy: entryPolicy(input.seed),
  };
}

export interface EntryItem {
  name: string;
  ref: ConfigArtifactRef;
  source: InputItemSource;
}

export interface TrajectoryEntryInput {
  name: string;
  scene: EntryItem;
  colregsConstraintsContent: string;
  params: TrajectoryGenerationParamsWire;
  seed: number;
  monitor?: StepMonitor;
}

/** The trajectories section: the straight generator takes its timespan, the search its wire parameters. */
export function trajectoriesSection(params: TrajectoryGenerationParamsWire, monitor: StepMonitor = "post_hoc"): Record<string, unknown> {
  if (params.generator === "straight") {
    return { generator: "straight", timespan_s: params.timespan, monitor };
  }
  const search: Record<string, number | boolean> = {};
  for (const key of SEARCH_PARAM_KEYS) {
    const value = params[key];
    if (typeof value === "number" || typeof value === "boolean") {
      search[key] = value;
    }
  }
  const searchTimeout = typeof params.timeout === "number" && params.timeout > 0 ? params.timeout : null;
  return {
    generator: "monitor_driven_rrt",
    params: search,
    timeout_s: searchTimeout === null ? DEFAULT_TRAJECTORY_TIMEOUT_S : searchTimeout + TRAJECTORY_REPLY_MARGIN_S,
    monitor,
  };
}

/** Trajectory generation over one scene item. */
export function trajectoryEntryConfig(input: TrajectoryEntryInput): CampaignConfigFormat2 {
  return {
    format: 3,
    name: input.name,
    steps: ["trajectory_generation"],
    input: { items: [input.scene] },
    domain: { colregs_constants: input.colregsConstraintsContent },
    trajectories: trajectoriesSection(input.params, input.monitor),
    policy: entryPolicy(input.seed),
  };
}

export interface SimulationEntryInput {
  name: string;
  trajectories: EntryItem;
  plan: ClusterRunPlan;
  colregsConstraintsContent: string;
  seed: number;
  /** The reference area of an ArduPilot run (the Connections page's); the workbench default when absent. */
  geofence?: ReferenceGeofence;
}

/**
 * The run's stack section (`campaign_config.KinematicStackConfig`, `ArdupilotStackConfig`, `CustomStackConfig`) for the plan the
 * workbench made of the setup. A campaign run steers the scene's own ship, as the plan does.
 */
export function simulationStack(plan: ClusterRunPlan, geofence: ReferenceGeofence = defaultReferenceGeofence): Record<string, unknown> {
  if (plan.runner === "attended") {
    // `campaign_config.AttendedStackConfig`: the setup as it is; only a workbench entry may have one
    return {
      attended: true,
      simulation: plan.simulation,
      geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
      ...(plan.broker ? { broker: plan.broker } : {}),
    };
  }
  if (plan.runner === "kinematic") {
    return { simulation_layer: "kinematic", mode: plan.mode };
  }
  if (plan.runner === "gazebo_custom") {
    return { simulation_layer: "gazebo", control_layer: "custom", mode: plan.mode };
  }
  return {
    simulation_layer: plan.simulationLayer,
    mode: plan.mode,
    speedup: plan.speedup,
    geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
  };
}

/** The run's environment section: the custom controller's wind; none for the stacks that run calm. */
export function simulationEnvironment(plan: ClusterRunPlan): Record<string, unknown> | null {
  return plan.runner === "gazebo_custom" && plan.windVector.some((component) => component !== 0) ? { wind_vector: [...plan.windVector] } : null;
}

/** A run over one trajectory item on the kinematic layer, on ArduPilot SITL or Gazebo, or on the custom controller with Gazebo, judged live by the COLREGS monitor as the workbench watches it. */
export function simulationEntryConfig(input: SimulationEntryInput): CampaignConfigFormat2 {
  return {
    format: 3,
    name: input.name,
    steps: ["simulation"],
    input: { items: [input.trajectories] },
    domain: { colregs_constants: input.colregsConstraintsContent },
    execution: {
      runs: [runOf(input)],
    },
    policy: entryPolicy(input.seed),
  };
}

function runOf(input: SimulationEntryInput): Record<string, unknown> {
  const environment = simulationEnvironment(input.plan);
  return { stack: simulationStack(input.plan, input.geofence), ...(environment !== null ? { environment } : {}), monitor: "live" };
}

/** The YAML the create route takes. */
export function toConfigYaml(config: CampaignConfigFormat2): string {
  return stringify(config, { lineWidth: 0 });
}

/** A short name for an entry: what ran, on what, and when, in the local time every page shows. */
export function entryName(what: string, on: string, at: Date = new Date()): string {
  return `${what}: ${on} (${formatLocalDateTime(at, "minute")})`.slice(0, 256);
}
