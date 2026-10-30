import { describe, expect, it } from "vitest";
import {
  arduPilotSimulationSubmission,
  describeClusterPlan,
  isPacedByWatchSpeed,
  kinematicSimulationSubmission,
  planSimulationRun,
  simulationSubmission,
  type ClusterRunPlan,
  type SimulationRunPlan,
  type SimulationSetup,
  type SimulationVesselSetup,
} from "./simulationJobs";

const GEOFENCE = { latitude: 57.7, longitude: 11.9, radius_meters: 2000 };

function vessel(vesselId: string, overrides: Partial<SimulationVesselSetup> = {}): SimulationVesselSetup {
  return { vesselId, context: "simulation", asvSoftware: "replay", controlLayer: "none", isOwnShip: vesselId === "0", ...overrides };
}

function setup(vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}): SimulationSetup {
  return { simulatorType: "Kinematic", vessels, windVector: [0, 0, 0], waveAmplitude: 0, speedup: 1, ...overrides };
}

describe("where a simulation runs", () => {
  it("runs a kinematic replay on the cluster", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1")]))).toMatchObject({ where: "cluster", jobType: "simulation.kinematic", mode: "replay", ownShipId: null });
  });

  it("runs USV Navigation on the own ship on the cluster", () => {
    const plan = planSimulationRun(setup([vessel("0", { asvSoftware: "usv_navigation" }), vessel("1")]));
    expect(plan).toMatchObject({ where: "cluster", mode: "usv_navigation", ownShipId: 0 });
  });

  it("keeps real vessels and Mission Planner in a live session", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { context: "real", controlLayer: "real_vessel" })]))).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(planSimulationRun(setup([vessel("0", { asvSoftware: "mission_planner" })], { simulatorType: "ArduPilot Sim" }))).toMatchObject({ where: "session", reason: expect.stringContaining("Mission Planner") });
  });

  it("runs replay on ArduPilot SITL and Gazebo on the cluster at the setup's speedup", () => {
    const onArduPilot = [vessel("0", { controlLayer: "ardupilot" }), vessel("1", { controlLayer: "ardupilot" })];
    expect(planSimulationRun(setup(onArduPilot, { simulatorType: "ArduPilot Sim", speedup: 5 }))).toMatchObject({
      where: "cluster",
      jobType: "simulation.ardupilot_sim",
      simulationLayer: "ardupilot_sim",
      speedup: 5,
    });
    expect(planSimulationRun(setup(onArduPilot, { simulatorType: "Gazebo", speedup: 0.4 }))).toMatchObject({ where: "cluster", jobType: "simulation.gazebo", simulationLayer: "gazebo", speedup: 1 });
  });

  it("keeps ArduPilot setups the job does not run in a live session", () => {
    const onArduPilot = (overrides: Partial<SimulationVesselSetup> = {}) => [vessel("0", { controlLayer: "ardupilot", ...overrides }), vessel("1", { controlLayer: "ardupilot" })];
    const where = (vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}) => planSimulationRun(setup(vessels, { simulatorType: "ArduPilot Sim", ...overrides }));
    expect(where(onArduPilot({ asvSoftware: "usv_navigation" }))).toMatchObject({ where: "session", reason: expect.stringContaining("replay on ArduPilot only") });
    expect(where(onArduPilot({ controlLayer: "custom" }))).toMatchObject({ where: "session", reason: expect.stringContaining("replay on ArduPilot only") });
    expect(where(onArduPilot({ context: "real", controlLayer: "real_vessel" }))).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(where(onArduPilot(), { windVector: [0, 2, 0] })).toMatchObject({ where: "session", reason: expect.stringContaining("calm weather") });
    expect(where(onArduPilot(), { waveAmplitude: 0.5 }).where).toBe("session");
    expect(where([])).toMatchObject({ where: "session", reason: "Load a scenario first." });
  });

  it("keeps wind and USV Navigation on a target ship off the cluster", () => {
    expect(planSimulationRun(setup([vessel("0")], { windVector: [1, 0, 0] })).where).toBe("session");
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { asvSoftware: "usv_navigation" })])).where).toBe("session");
  });

  it("builds the kinematic job with the live monitor", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0", { asvSoftware: "usv_navigation" }), vessel("1")])));
    if (plan.jobType !== "simulation.kinematic") {
      throw new Error("expected a kinematic plan");
    }
    const submission = kinematicSimulationSubmission(plan, { scene_list: [] }, "rules");
    expect(submission).toEqual({
      job_type: "simulation.kinematic",
      payload: { mode: "usv_navigation", trajectories: { scene_list: [] }, monitor: "live", colregs_constraints_content: "rules", include_trajectories: true, own_ship_id: 0 },
      max_attempts: 1,
    });
  });

  it("builds the ArduPilot job with the reference geofence", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "ardupilot" })], { simulatorType: "Gazebo", speedup: 10 })));
    expect(simulationSubmission(plan, { trajectories: { scene_list: [] }, colregsConstraintsContent: "rules", geofence: GEOFENCE })).toEqual({
      job_type: "simulation.gazebo",
      payload: {
        simulation_layer: "gazebo",
        trajectories: { scene_list: [] },
        geofence: GEOFENCE,
        speedup: 10,
        monitor: "live",
        colregs_constraints_content: "rules",
        include_trajectories: true,
      },
      max_attempts: 1,
    });
    if (plan.jobType !== "simulation.gazebo") {
      throw new Error("expected an ArduPilot plan");
    }
    expect(arduPilotSimulationSubmission(plan, {}, { ...GEOFENCE, radius_meters: 20 }, "  ").payload).toMatchObject({ geofence: { radius_meters: 20 }, colregs_constraints_content: null });
  });

  it("submits a kinematic plan as the kinematic job", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0")])));
    expect(simulationSubmission(plan, { trajectories: {}, colregsConstraintsContent: "", geofence: GEOFENCE })).toMatchObject({
      job_type: "simulation.kinematic",
      payload: { mode: "replay", monitor: "live", colregs_constraints_content: null },
    });
  });

  it("says what each cluster plan runs and whether the watch speed paces it", () => {
    const kinematic = clusterPlan(planSimulationRun(setup([vessel("0")])));
    const arduPilot = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "ardupilot" })], { simulatorType: "ArduPilot Sim", speedup: 3 })));
    expect(describeClusterPlan(kinematic)).toContain("kinematic job");
    expect(describeClusterPlan(arduPilot)).toContain("ArduPilot SITL job");
    expect(describeClusterPlan(arduPilot)).toContain("3x real time");
    expect(describeClusterPlan(arduPilot)).toContain("COLREGS monitor");
    expect(isPacedByWatchSpeed(kinematic)).toBe(true);
    expect(isPacedByWatchSpeed(arduPilot)).toBe(false);
  });
});

function clusterPlan(plan: SimulationRunPlan): ClusterRunPlan {
  if (plan.where !== "cluster") {
    throw new Error(`expected a cluster plan, got: ${plan.reason}`);
  }
  return plan;
}
