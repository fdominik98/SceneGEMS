import { SIMULATION_JOB, simulationPayloadComponents } from "../../../domain/cluster/components";
import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { ReferenceGeofence } from "../connection/referenceGeofence";
import type { AsvSoftware, ControlLayer, GlobalSimulatorType, SimulationContext } from "../controls/simulationInitConfig";

/**
 * Where a workbench simulation runs. A setup a runner of the cluster's simulation job runs goes
 * there as one job, judged live by the COLREGS monitor in the job: on the kinematic layer (runner
 * kinematic), on ArduPilot SITL or Gazebo over the lockstep MAVLink adapters (runner ardupilot), or
 * on the custom controller in a Gazebo world the runner steps (runner gazebo_custom). Each runs
 * every vessel on replay, or USV Navigation on the own ship and replay on the others. Every other
 * setup is a live session on the master over the MQTT broker: real vessels and Mission Planner are
 * only ever run that way, and so are setups no runner takes (USV Navigation on a target ship,
 * mixed control layers, the weather a job does not apply). A plan names the components its job
 * needs, so the workbench counts the nodes that have them.
 */

export { SIMULATION_JOB };
/** The simulation job type, as every cluster plan submits it. */
export const KINEMATIC_SIMULATION_JOB = SIMULATION_JOB;
export type ArduPilotSimulationLayer = "ardupilot_sim" | "gazebo";
/** What a cluster run runs on the vessels: every one replays, or the own ship runs USV Navigation. */
export type RunMode = "replay" | "usv_navigation";

export interface SimulationVesselSetup {
  vesselId: string;
  context: SimulationContext;
  asvSoftware: AsvSoftware;
  controlLayer: ControlLayer;
  isOwnShip: boolean;
}

export interface SimulationSetup {
  simulatorType: GlobalSimulatorType;
  vessels: SimulationVesselSetup[];
  windVector: [number, number, number];
  waveAmplitude: number;
  /** The real-time factor: a live session's pace, and SITL's speedup in an ArduPilot job. */
  speedup: number;
}

export type KinematicRunPlan = {
  where: "cluster";
  jobType: typeof SIMULATION_JOB;
  runner: "kinematic";
  mode: RunMode;
  /** The vessel that runs USV Navigation; null for replay, or for the scene's own ship. */
  ownShipId: number | null;
  /** The components the job needs, every layer of every vessel's stack. */
  components: string[];
  summary: string;
};

export type ArduPilotRunPlan = {
  where: "cluster";
  jobType: typeof SIMULATION_JOB;
  runner: "ardupilot";
  simulationLayer: ArduPilotSimulationLayer;
  mode: RunMode;
  ownShipId: number | null;
  speedup: number;
  components: string[];
  summary: string;
};

export type GazeboCustomRunPlan = {
  where: "cluster";
  jobType: typeof SIMULATION_JOB;
  runner: "gazebo_custom";
  mode: RunMode;
  ownShipId: number | null;
  /** The wind of the world and of the controller's hulls, [east, north, up] m/s. */
  windVector: [number, number, number];
  components: string[];
  summary: string;
};

export type ClusterRunPlan = KinematicRunPlan | ArduPilotRunPlan | GazeboCustomRunPlan;

export type SimulationRunPlan = ClusterRunPlan | { where: "session"; reason: string };

const ARDUPILOT_LAYERS: Partial<Record<GlobalSimulatorType, ArduPilotSimulationLayer>> = {
  "ArduPilot Sim": "ardupilot_sim",
  Gazebo: "gazebo",
};

type ControlLayerOfPlan = "none" | "ardupilot" | "custom";

/** The run mode of vessels that all sit on one control layer: replay, or USV Navigation on the own ship alone; null when no runner takes it. */
function modeOf(vessels: readonly SimulationVesselSetup[]): Pick<KinematicRunPlan, "mode" | "ownShipId"> | null {
  const navigators = vessels.filter((vessel) => vessel.asvSoftware !== "replay");
  if (navigators.length === 0) {
    return { mode: "replay", ownShipId: null };
  }
  const ownShip = navigators[0];
  if (navigators.length === 1 && ownShip.isOwnShip && ownShip.asvSoftware === "usv_navigation") {
    const ownShipId = Number.parseInt(ownShip.vesselId, 10);
    return { mode: "usv_navigation", ownShipId: Number.isFinite(ownShipId) ? ownShipId : null };
  }
  return null;
}

function onControlLayer(vessels: readonly SimulationVesselSetup[], controlLayer: ControlLayerOfPlan): boolean {
  return vessels.every((vessel) => vessel.controlLayer === controlLayer);
}

const SUMMARIES: Record<ControlLayerOfPlan, Record<RunMode, string>> = {
  none: { replay: "every vessel replays its trajectory", usv_navigation: "USV Navigation steers the own ship, the others replay" },
  ardupilot: { replay: "every vessel replays its trajectory through ArduPilot", usv_navigation: "USV Navigation steers the own ship through ArduPilot, the others replay" },
  custom: { replay: "every vessel follows its trajectory with the custom controller", usv_navigation: "USV Navigation steers the own ship through the custom controller, the others replay" },
};

const MODE_ONLY = "On the cluster only the own ship may run USV Navigation; this setup runs as a live session.";

export function planSimulationRun(setup: SimulationSetup): SimulationRunPlan {
  const { vessels } = setup;
  if (vessels.some((vessel) => vessel.context === "real")) {
    return { where: "session", reason: "A real vessel joins only a live session over the MQTT broker." };
  }
  if (vessels.some((vessel) => vessel.asvSoftware === "mission_planner")) {
    return { where: "session", reason: "Mission Planner is flown from the desktop in a live session." };
  }
  if (vessels.length === 0) {
    return { where: "session", reason: "Load a scenario first." };
  }
  const arduPilotLayer = ARDUPILOT_LAYERS[setup.simulatorType];
  if (setup.simulatorType === "Gazebo" && onControlLayer(vessels, "custom")) {
    return planGazeboCustomRun(setup);
  }
  if (arduPilotLayer !== undefined) {
    return planArduPilotRun(setup, arduPilotLayer);
  }
  if (setup.simulatorType !== "Kinematic") {
    return { where: "session", reason: `${setup.simulatorType} has no cluster job yet, so it runs as a live session on the master.` };
  }
  if (setup.windVector.some((component) => component !== 0) || setup.waveAmplitude > 0) {
    return { where: "session", reason: "The kinematic layer has no wind or waves." };
  }
  const mode = onControlLayer(vessels, "none") ? modeOf(vessels) : null;
  if (mode === null) {
    return { where: "session", reason: MODE_ONLY };
  }
  return { where: "cluster", jobType: SIMULATION_JOB, runner: "kinematic", ...mode, components: simulationPayloadComponents({ runner: "kinematic", mode: mode.mode }), summary: SUMMARIES.none[mode.mode] };
}

/** Replay or USV Navigation on SITL or Gazebo runs as one job; the job's stack runs in calm weather. */
function planArduPilotRun(setup: SimulationSetup, simulationLayer: ArduPilotSimulationLayer): SimulationRunPlan {
  const mode = onControlLayer(setup.vessels, "ardupilot") ? modeOf(setup.vessels) : null;
  if (mode === null) {
    return {
      where: "session",
      reason: `On the cluster ${setup.simulatorType} runs replay on ArduPilot, with USV Navigation on the own ship only${setup.simulatorType === "Gazebo" ? ", or every vessel on the custom controller" : ""}; this setup runs as a live session.`,
    };
  }
  if (setup.windVector.some((component) => component !== 0) || setup.waveAmplitude > 0) {
    return { where: "session", reason: "The cluster's ArduPilot job runs in calm weather; with wind or waves the setup runs as a live session." };
  }
  return {
    where: "cluster",
    jobType: SIMULATION_JOB,
    runner: "ardupilot",
    simulationLayer,
    ...mode,
    components: simulationPayloadComponents({ runner: "ardupilot", simulation_layer: simulationLayer, mode: mode.mode }),
    speedup: Math.max(1, Math.round(setup.speedup)),
    summary: SUMMARIES.ardupilot[mode.mode],
  };
}

/** The custom controller on Gazebo runs as one job that steps the world itself, in the setup's wind. */
function planGazeboCustomRun(setup: SimulationSetup): SimulationRunPlan {
  const mode = modeOf(setup.vessels);
  if (mode === null) {
    return { where: "session", reason: MODE_ONLY };
  }
  if (setup.waveAmplitude > 0) {
    return { where: "session", reason: "The cluster's custom controller job takes the wind from the workbench, not the waves; with waves the setup runs as a live session." };
  }
  return {
    where: "cluster",
    jobType: SIMULATION_JOB,
    runner: "gazebo_custom",
    ...mode,
    windVector: [...setup.windVector],
    components: simulationPayloadComponents({ runner: "gazebo_custom", mode: mode.mode }),
    summary: SUMMARIES.custom[mode.mode],
  };
}

function liveMonitorFields(colregsConstraintsContent: string): Record<string, unknown> {
  return {
    monitor: "live",
    colregs_constraints_content: colregsConstraintsContent.trim().length > 0 ? colregsConstraintsContent : null,
    // The run's trajectories, monitored after the run when it ended before anyone watched it.
    include_trajectories: true,
  };
}

/** The simulation job's kinematic runner (cluster/node/jobs/simulation_runners/kinematic_runner.py) with the COLREGS monitor live, over the loaded trajectories. */
export function kinematicSimulationSubmission(plan: KinematicRunPlan, trajectories: Record<string, unknown>, colregsConstraintsContent: string): JobSubmission {
  const payload: Record<string, unknown> = { runner: plan.runner, mode: plan.mode, trajectories, ...liveMonitorFields(colregsConstraintsContent) };
  withOwnShip(payload, plan);
  // A failed run would fail the same way again: the workbench shows it at once.
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

/**
 * The simulation job's ardupilot runner (cluster/node/jobs/simulation_runners/ardupilot_runner.py): replay over the lockstep
 * MAVLink adapter with the COLREGS monitor live, the reference geofence placing the local frame
 * on SITL's map.
 */
export function arduPilotSimulationSubmission(
  plan: ArduPilotRunPlan,
  trajectories: Record<string, unknown>,
  geofence: ReferenceGeofence,
  colregsConstraintsContent: string
): JobSubmission {
  const payload: Record<string, unknown> = {
    runner: plan.runner,
    simulation_layer: plan.simulationLayer,
    mode: plan.mode,
    trajectories,
    geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
    speedup: plan.speedup,
    ...liveMonitorFields(colregsConstraintsContent),
  };
  withOwnShip(payload, plan);
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

/**
 * The simulation job's gazebo_custom runner (cluster/node/jobs/simulation_runners/gazebo_custom_runner.py): the custom
 * controller on a Gazebo world the runner steps, in the setup's wind, with the COLREGS monitor live.
 */
export function gazeboCustomSimulationSubmission(
  plan: GazeboCustomRunPlan,
  trajectories: Record<string, unknown>,
  geofence: ReferenceGeofence,
  colregsConstraintsContent: string
): JobSubmission {
  const payload: Record<string, unknown> = {
    runner: plan.runner,
    mode: plan.mode,
    trajectories,
    environment: { wind_vector: [...plan.windVector] },
    geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
    ...liveMonitorFields(colregsConstraintsContent),
  };
  withOwnShip(payload, plan);
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

function withOwnShip(payload: Record<string, unknown>, plan: ClusterRunPlan): void {
  if (plan.mode === "usv_navigation" && plan.ownShipId !== null) {
    payload.own_ship_id = plan.ownShipId;
  }
}

export interface SimulationJobInput {
  trajectories: Record<string, unknown>;
  colregsConstraintsContent: string;
  geofence: ReferenceGeofence;
}

/** The job a cluster plan submits. */
export function simulationSubmission(plan: ClusterRunPlan, input: SimulationJobInput): JobSubmission {
  if (plan.runner === "kinematic") {
    return kinematicSimulationSubmission(plan, input.trajectories, input.colregsConstraintsContent);
  }
  if (plan.runner === "gazebo_custom") {
    return gazeboCustomSimulationSubmission(plan, input.trajectories, input.geofence, input.colregsConstraintsContent);
  }
  return arduPilotSimulationSubmission(plan, input.trajectories, input.geofence, input.colregsConstraintsContent);
}

const LAYER_LABELS: Record<ArduPilotSimulationLayer, string> = { ardupilot_sim: "ArduPilot SITL", gazebo: "ArduPilot SITL on Gazebo" };

/** How the run panel says what a cluster plan runs. */
export function describeClusterPlan(plan: ClusterRunPlan): string {
  if (plan.runner === "kinematic") {
    return `Runs on the cluster as one kinematic job (${plan.summary}), judged by the COLREGS monitor as it runs.`;
  }
  if (plan.runner === "gazebo_custom") {
    const windy = plan.windVector.some((component) => component !== 0);
    return `Runs on the cluster as one Gazebo job with the custom controller (${plan.summary})${windy ? " in the setup's wind" : ""}, judged by the COLREGS monitor as it runs.`;
  }
  return (
    `Runs on the cluster as one ${LAYER_LABELS[plan.simulationLayer]} job (${plan.summary}) at ${plan.speedup}x real time, judged by the COLREGS monitor as it runs. ` +
    "SITL runs free, so the watch speed plays the arriving run in the browser."
  );
}

/**
 * Whether the watch speed paces the run on the node: the kinematic and the custom controller's runners
 * step their run themselves. SITL runs free at the job's speedup, so an ArduPilot run's watch speed
 * is the playback speed of the shown run in the browser instead.
 */
export function isPacedByWatchSpeed(plan: ClusterRunPlan): boolean {
  return plan.runner !== "ardupilot";
}
