import { SIMULATION_JOB, simulationPayloadComponents } from "../../../domain/cluster/components";
import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { ReferenceGeofence } from "../connection/referenceGeofence";
import type { AsvSoftware, ControlLayer, GlobalSimulatorType, SimulationContext } from "../controls/simulationInitConfig";

/**
 * Where a workbench simulation runs. A setup a runner of the cluster's simulation job runs goes
 * there as one job, judged live by the COLREGS monitor in the job: kinematic replay or USV
 * Navigation on the kinematic layer (runner kinematic), or replay on ArduPilot SITL or Gazebo over
 * the lockstep MAVLink adapter (runner ardupilot). Every other setup is a live session on the
 * master over the MQTT broker: real vessels and Mission Planner are only ever run that way, and the
 * stacks no runner runs yet (the custom controller, USV Navigation on ArduPilot) are run that way for now.
 * A plan names the components its job needs, so the workbench counts the nodes that have them.
 */

export { SIMULATION_JOB };
/** The simulation job type, as every cluster plan submits it. */
export const KINEMATIC_SIMULATION_JOB = SIMULATION_JOB;
export type ArduPilotSimulationLayer = "ardupilot_sim" | "gazebo";

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
  mode: "replay" | "usv_navigation";
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
  speedup: number;
  components: string[];
  summary: string;
};

export type ClusterRunPlan = KinematicRunPlan | ArduPilotRunPlan;

export type SimulationRunPlan = ClusterRunPlan | { where: "session"; reason: string };

const ARDUPILOT_LAYERS: Partial<Record<GlobalSimulatorType, ArduPilotSimulationLayer>> = {
  "ArduPilot Sim": "ardupilot_sim",
  Gazebo: "gazebo",
};

function isReplayOnKinematic(vessel: SimulationVesselSetup): boolean {
  return vessel.asvSoftware === "replay" && vessel.controlLayer === "none";
}

function isReplayOnArduPilot(vessel: SimulationVesselSetup): boolean {
  return vessel.asvSoftware === "replay" && vessel.controlLayer === "ardupilot";
}

export function planSimulationRun(setup: SimulationSetup): SimulationRunPlan {
  const { vessels } = setup;
  if (vessels.some((vessel) => vessel.context === "real")) {
    return { where: "session", reason: "A real vessel joins only a live session over the MQTT broker." };
  }
  if (vessels.some((vessel) => vessel.asvSoftware === "mission_planner")) {
    return { where: "session", reason: "Mission Planner is flown from the desktop in a live session." };
  }
  const arduPilotLayer = ARDUPILOT_LAYERS[setup.simulatorType];
  if (arduPilotLayer !== undefined) {
    return planArduPilotRun(setup, arduPilotLayer);
  }
  if (setup.simulatorType !== "Kinematic") {
    return { where: "session", reason: `${setup.simulatorType} has no cluster job yet, so it runs as a live session on the master.` };
  }
  if (setup.windVector.some((component) => component !== 0) || setup.waveAmplitude > 0) {
    return { where: "session", reason: "The kinematic layer has no wind or waves." };
  }
  if (vessels.length === 0) {
    return { where: "session", reason: "Load a scenario first." };
  }
  if (vessels.every(isReplayOnKinematic)) {
    return { where: "cluster", ...kinematicPlan("replay"), ownShipId: null, summary: "every vessel replays its trajectory" };
  }
  const navigators = vessels.filter((vessel) => !isReplayOnKinematic(vessel));
  const ownShip = navigators[0];
  if (
    navigators.length === 1 &&
    ownShip.isOwnShip &&
    ownShip.asvSoftware === "usv_navigation" &&
    ownShip.controlLayer === "none"
  ) {
    const ownShipId = Number.parseInt(ownShip.vesselId, 10);
    return {
      where: "cluster",
      ...kinematicPlan("usv_navigation"),
      ownShipId: Number.isFinite(ownShipId) ? ownShipId : null,
      summary: "USV Navigation steers the own ship, the others replay",
    };
  }
  return { where: "session", reason: "On the cluster only the own ship may run USV Navigation; this setup runs as a live session." };
}

function kinematicPlan(mode: KinematicRunPlan["mode"]): Pick<KinematicRunPlan, "jobType" | "runner" | "mode" | "components"> {
  return { jobType: SIMULATION_JOB, runner: "kinematic", mode, components: simulationPayloadComponents({ runner: "kinematic", mode }) };
}

/** Replay on SITL or Gazebo runs as one job; the job's stack runs in calm weather. */
function planArduPilotRun(setup: SimulationSetup, simulationLayer: ArduPilotSimulationLayer): SimulationRunPlan {
  if (setup.vessels.length === 0) {
    return { where: "session", reason: "Load a scenario first." };
  }
  if (!setup.vessels.every(isReplayOnArduPilot)) {
    return { where: "session", reason: `On the cluster ${setup.simulatorType} runs replay on ArduPilot only; this setup runs as a live session.` };
  }
  if (setup.windVector.some((component) => component !== 0) || setup.waveAmplitude > 0) {
    return { where: "session", reason: "The cluster's ArduPilot job runs in calm weather; with wind or waves the setup runs as a live session." };
  }
  return {
    where: "cluster",
    jobType: SIMULATION_JOB,
    runner: "ardupilot",
    simulationLayer,
    components: simulationPayloadComponents({ runner: "ardupilot", simulation_layer: simulationLayer }),
    speedup: Math.max(1, Math.round(setup.speedup)),
    summary: "every vessel replays its trajectory through ArduPilot",
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
  if (plan.mode === "usv_navigation" && plan.ownShipId !== null) {
    payload.own_ship_id = plan.ownShipId;
  }
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
    trajectories,
    geofence: { latitude: geofence.latitude, longitude: geofence.longitude, radius_meters: geofence.radius_meters },
    speedup: plan.speedup,
    ...liveMonitorFields(colregsConstraintsContent),
  };
  return { job_type: plan.jobType, payload, max_attempts: 1 };
}

export interface SimulationJobInput {
  trajectories: Record<string, unknown>;
  colregsConstraintsContent: string;
  geofence: ReferenceGeofence;
}

/** The job a cluster plan submits. */
export function simulationSubmission(plan: ClusterRunPlan, input: SimulationJobInput): JobSubmission {
  return plan.runner === "kinematic"
    ? kinematicSimulationSubmission(plan, input.trajectories, input.colregsConstraintsContent)
    : arduPilotSimulationSubmission(plan, input.trajectories, input.geofence, input.colregsConstraintsContent);
}

const LAYER_LABELS: Record<ArduPilotSimulationLayer, string> = { ardupilot_sim: "ArduPilot SITL", gazebo: "ArduPilot SITL on Gazebo" };

/** How the run panel says what a cluster plan runs. */
export function describeClusterPlan(plan: ClusterRunPlan): string {
  if (plan.runner === "kinematic") {
    return `Runs on the cluster as one kinematic job (${plan.summary}), judged by the COLREGS monitor as it runs.`;
  }
  return `Runs on the cluster as one ${LAYER_LABELS[plan.simulationLayer]} job (${plan.summary}) at ${plan.speedup}x real time, judged by the COLREGS monitor as it runs.`;
}

/** Whether the watch speed paces the run; SITL runs free at the job's speedup instead. */
export function isPacedByWatchSpeed(plan: ClusterRunPlan): boolean {
  return plan.runner === "kinematic";
}
