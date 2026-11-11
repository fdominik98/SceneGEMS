import { attendedSetupComponents, SIMULATION_JOB, simulationPayloadComponents } from "../../../domain/cluster/components";
import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { ReferenceGeofence } from "../connection/referenceGeofence";
import type { AsvSystem, ControlLayer, GlobalSimulatorType, SimulationContext } from "../controls/simulationInitConfig";

/**
 * Where a workbench simulation runs. A setup a runner of the cluster's simulation job runs goes
 * there as one job, judged live by the COLREGS monitor in the job: on the kinematic layer (runner
 * kinematic), on ArduPilot SITL or Gazebo over the lockstep MAVLink adapters (runner ardupilot), or
 * on the custom controller in a Gazebo world the runner steps (runner gazebo_custom). Each runs
 * every vessel on replay, or USV Navigation on the own ship and replay on the others. A setup none
 * of them takes (Mission Planner, USV Navigation on a target ship, mixed control layers, the weather
 * a job does not apply) runs as an attended job (runner attended): the job brings the stack up and
 * waits for the operator's Start. Only a setup with a real vessel is still a live session on the
 * control node over the MQTT broker. A plan names the components its job needs, so the workbench
 * counts the worker nodes that have them.
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
  asvSystem: AsvSystem;
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
  /** The whole setup as the control node takes it (simulatorType, windVector, wave, simulationSpeed, connectionsByAgentId): what an attended job runs. */
  body?: Record<string, unknown>;
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

/** A run the operator starts by hand once the job's stack is up: the setup as it is, vessel by vessel. */
export type AttendedRunPlan = {
  where: "cluster";
  jobType: typeof SIMULATION_JOB;
  runner: "attended";
  /** The setup the job runs (SimulationSetup.body). */
  simulation: Record<string, unknown>;
  /** Why no unattended runner takes the setup. */
  reason: string;
  components: string[];
  summary: string;
};

/** The plans whose run needs no operator beside it. */
export type UnattendedRunPlan = KinematicRunPlan | ArduPilotRunPlan | GazeboCustomRunPlan;
export type ClusterRunPlan = UnattendedRunPlan | AttendedRunPlan;

export type SimulationRunPlan = ClusterRunPlan | { where: "session"; reason: string };

const ARDUPILOT_LAYERS: Partial<Record<GlobalSimulatorType, ArduPilotSimulationLayer>> = {
  "ArduPilot Sim": "ardupilot_sim",
  Gazebo: "gazebo",
};

type ControlLayerOfPlan = "none" | "ardupilot" | "custom";

/** The run mode of vessels that all sit on one control layer: replay, or USV Navigation on the own ship alone; null when no runner takes it. */
function modeOf(vessels: readonly SimulationVesselSetup[]): Pick<KinematicRunPlan, "mode" | "ownShipId"> | null {
  const navigators = vessels.filter((vessel) => vessel.asvSystem !== "replay");
  if (navigators.length === 0) {
    return { mode: "replay", ownShipId: null };
  }
  const ownShip = navigators[0];
  if (navigators.length === 1 && ownShip.isOwnShip && ownShip.asvSystem === "usv_navigation") {
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

/** The setup as an attended job, for a reason no unattended runner takes it; a live session when the setup's body is not known. */
function attended(setup: SimulationSetup, reason: string): SimulationRunPlan {
  if (setup.body === undefined) {
    return { where: "session", reason };
  }
  return {
    where: "cluster",
    jobType: SIMULATION_JOB,
    runner: "attended",
    simulation: setup.body,
    reason,
    components: attendedSetupComponents(setup.body),
    summary: setup.vessels.some((vessel) => vessel.asvSystem === "mission_planner") ? "you steer a vessel from Mission Planner" : "the setup as it is, vessel by vessel",
  };
}

/** Where the setup runs. Use planSimulationRun: this one names the setups no unattended runner takes as sessions. */
function planUnattendedRun(setup: SimulationSetup): SimulationRunPlan {
  const { vessels } = setup;
  if (vessels.some((vessel) => vessel.context === "real")) {
    return { where: "session", reason: "A real vessel joins only a live session over the MQTT broker." };
  }
  if (vessels.some((vessel) => vessel.asvSystem === "mission_planner")) {
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
    return { where: "session", reason: `${setup.simulatorType} has no cluster job yet, so it runs as a live session on the control node.` };
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

/**
 * Where the setup runs: as an unattended job where a runner takes it, as an attended job otherwise, and as a live
 * session on the control node only with a real vessel (or before a scenario is loaded).
 */
export function planSimulationRun(setup: SimulationSetup): SimulationRunPlan {
  const plan = planUnattendedRun(setup);
  if (plan.where === "cluster" || setup.vessels.length === 0 || setup.vessels.some((vessel) => vessel.context === "real")) {
    return plan;
  }
  return attended(setup, plan.reason);
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

/** The simulation job's kinematic runner (cluster/worker_node/jobs/simulation_runners/kinematic_runner.py) with the COLREGS monitor live, over the loaded trajectories. */
export function kinematicSimulationSubmission(plan: KinematicRunPlan, trajectories: Record<string, unknown>, colregsConstraintsContent: string): JobSubmission {
  const payload: Record<string, unknown> = { runner: plan.runner, mode: plan.mode, trajectories, ...liveMonitorFields(colregsConstraintsContent) };
  withOwnShip(payload, plan);
  // A failed run would fail the same way again: the workbench shows it at once.
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

/**
 * The simulation job's ardupilot runner (cluster/worker_node/jobs/simulation_runners/ardupilot_runner.py): replay over the lockstep
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
 * The simulation job's gazebo_custom runner (cluster/worker_node/jobs/simulation_runners/gazebo_custom_runner.py): the custom
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

function withOwnShip(payload: Record<string, unknown>, plan: UnattendedRunPlan): void {
  if (plan.mode === "usv_navigation" && plan.ownShipId !== null) {
    payload.own_ship_id = plan.ownShipId;
  }
}

export interface SimulationJobInput {
  trajectories: Record<string, unknown>;
  colregsConstraintsContent: string;
  geofence: ReferenceGeofence;
}

/**
 * The simulation job's attended runner (cluster/worker_node/jobs/simulation_runners/attended_runner.py): the setup as it is,
 * with the COLREGS monitor live. The job waits for the operator's Start.
 */
export function attendedSimulationSubmission(plan: AttendedRunPlan, trajectories: Record<string, unknown>, geofence: ReferenceGeofence, colregsConstraintsContent: string): JobSubmission {
  const payload: Record<string, unknown> = {
    runner: plan.runner,
    simulation: plan.simulation,
    trajectories,
    geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
    ...liveMonitorFields(colregsConstraintsContent),
  };
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

/** The job a cluster plan submits. */
export function simulationSubmission(plan: ClusterRunPlan, input: SimulationJobInput): JobSubmission {
  if (plan.runner === "attended") {
    return attendedSimulationSubmission(plan, input.trajectories, input.geofence, input.colregsConstraintsContent);
  }
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
  if (plan.runner === "attended") {
    return `Runs on the cluster as one attended job (${plan.summary}): the job brings the vessels up and waits for your Start. ${plan.reason}`;
  }
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
 * Whether the watch speed paces the run on the worker node: the kinematic and the custom controller's runners
 * step their run themselves. SITL runs free at the job's speedup, so an ArduPilot run's watch speed
 * is the playback speed of the shown run in the browser instead.
 */
export function isPacedByWatchSpeed(plan: ClusterRunPlan): boolean {
  return plan.runner !== "ardupilot" && plan.runner !== "attended"; // an attended run follows the setup's own speed
}
