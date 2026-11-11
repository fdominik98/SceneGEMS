import { describe, expect, it } from "vitest";
import {
  arduPilotSimulationSubmission,
  describeClusterPlan,
  gazeboCustomSimulationSubmission,
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
  return { vesselId, context: "simulation", asvSystem: "replay", controlLayer: "none", isOwnShip: vesselId === "0", ...overrides };
}

function setup(vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}): SimulationSetup {
  return { simulatorType: "Kinematic", vessels, windVector: [0, 0, 0], waveAmplitude: 0, speedup: 1, ...overrides };
}

describe("where a simulation runs", () => {
  it("runs a kinematic replay on the cluster", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1")]))).toMatchObject({
      where: "cluster",
      jobType: "simulation",
      runner: "kinematic",
      mode: "replay",
      ownShipId: null,
      components: ["asv_system/replay", "control_layer/none", "simulation_layer/kinematic"],
    });
  });

  it("runs USV Navigation on the own ship on the cluster", () => {
    const plan = planSimulationRun(setup([vessel("0", { asvSystem: "usv_navigation" }), vessel("1")]));
    expect(plan).toMatchObject({ where: "cluster", mode: "usv_navigation", ownShipId: 0 });
    expect(clusterPlan(plan).components).toEqual(["asv_system/replay", "asv_system/usv_navigation", "control_layer/none", "simulation_layer/kinematic"]);
  });

  it("keeps real vessels and Mission Planner in a live session", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { context: "real", controlLayer: "real_vessel" })]))).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(planSimulationRun(setup([vessel("0", { asvSystem: "mission_planner" })], { simulatorType: "ArduPilot Sim" }))).toMatchObject({ where: "session", reason: expect.stringContaining("Mission Planner") });
  });

  it("runs replay on ArduPilot SITL and Gazebo on the cluster at the setup's speedup", () => {
    const onArduPilot = [vessel("0", { controlLayer: "ardupilot" }), vessel("1", { controlLayer: "ardupilot" })];
    expect(planSimulationRun(setup(onArduPilot, { simulatorType: "ArduPilot Sim", speedup: 5 }))).toMatchObject({
      where: "cluster",
      jobType: "simulation",
      runner: "ardupilot",
      simulationLayer: "ardupilot_sim",
      speedup: 5,
      components: ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"],
    });
    expect(planSimulationRun(setup(onArduPilot, { simulatorType: "Gazebo", speedup: 0.4 }))).toMatchObject({
      where: "cluster",
      jobType: "simulation",
      runner: "ardupilot",
      simulationLayer: "gazebo",
      speedup: 1,
      components: ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"],
    });
  });

  it("keeps ArduPilot setups the job does not run in a live session", () => {
    const onArduPilot = (overrides: Partial<SimulationVesselSetup> = {}) => [vessel("0", { controlLayer: "ardupilot", ...overrides }), vessel("1", { controlLayer: "ardupilot" })];
    const where = (vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}) => planSimulationRun(setup(vessels, { simulatorType: "ArduPilot Sim", ...overrides }));
    expect(where([vessel("0", { controlLayer: "ardupilot" }), vessel("1", { controlLayer: "ardupilot", asvSystem: "usv_navigation" })])).toMatchObject({
      where: "session",
      reason: expect.stringContaining("USV Navigation on the own ship only"),
    });
    expect(where(onArduPilot({ controlLayer: "custom" }))).toMatchObject({ where: "session", reason: expect.stringContaining("replay on ArduPilot") });
    expect(where(onArduPilot({ controlLayer: "custom" }), { simulatorType: "Gazebo" })).toMatchObject({ where: "session", reason: expect.stringContaining("custom controller") });
    expect(where(onArduPilot({ context: "real", controlLayer: "real_vessel" }))).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(where(onArduPilot(), { windVector: [0, 2, 0] })).toMatchObject({ where: "session", reason: expect.stringContaining("calm weather") });
    expect(where(onArduPilot(), { waveAmplitude: 0.5 }).where).toBe("session");
    expect(where([])).toMatchObject({ where: "session", reason: "Load a scenario first." });
  });

  it("runs USV Navigation on the own ship through ArduPilot on the cluster", () => {
    const vessels = [vessel("0", { controlLayer: "ardupilot", asvSystem: "usv_navigation" }), vessel("1", { controlLayer: "ardupilot" })];
    const plan = clusterPlan(planSimulationRun(setup(vessels, { simulatorType: "Gazebo", speedup: 4 })));
    expect(plan).toMatchObject({ runner: "ardupilot", simulationLayer: "gazebo", mode: "usv_navigation", ownShipId: 0, speedup: 4 });
    expect(plan.components).toEqual(["asv_system/replay", "asv_system/usv_navigation", "control_layer/ardupilot", "simulation_layer/gazebo"]);
    expect(simulationSubmission(plan, { trajectories: {}, colregsConstraintsContent: "", geofence: GEOFENCE }).payload).toMatchObject({
      runner: "ardupilot",
      simulation_layer: "gazebo",
      mode: "usv_navigation",
      own_ship_id: 0,
    });
  });

  it("runs the custom controller on Gazebo on the cluster, in the setup's wind", () => {
    const onCustom = [vessel("0", { controlLayer: "custom" }), vessel("1", { controlLayer: "custom" })];
    const plan = clusterPlan(planSimulationRun(setup(onCustom, { simulatorType: "Gazebo", windVector: [0, 3, 0], speedup: 7 })));
    expect(plan).toMatchObject({ where: "cluster", jobType: "simulation", runner: "gazebo_custom", mode: "replay", ownShipId: null, windVector: [0, 3, 0] });
    expect(plan.components).toEqual(["asv_system/replay", "control_layer/custom", "simulation_layer/gazebo"]);
    if (plan.runner !== "gazebo_custom") {
      throw new Error("expected a custom controller plan");
    }
    expect(gazeboCustomSimulationSubmission(plan, { scene_list: [] }, GEOFENCE, "rules")).toEqual({
      job_type: "simulation",
      payload: {
        runner: "gazebo_custom",
        mode: "replay",
        trajectories: { scene_list: [] },
        environment: { wind_vector: [0, 3, 0] },
        geofence: GEOFENCE,
        monitor: "live",
        colregs_constraints_content: "rules",
        include_trajectories: true,
      },
      max_attempts: 1,
    });
    const navigating = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "custom", asvSystem: "usv_navigation" }), vessel("1", { controlLayer: "custom" })], { simulatorType: "Gazebo" })));
    expect(navigating).toMatchObject({ runner: "gazebo_custom", mode: "usv_navigation", ownShipId: 0 });
    expect(simulationSubmission(navigating, { trajectories: {}, colregsConstraintsContent: "", geofence: GEOFENCE }).payload).toMatchObject({ own_ship_id: 0, mode: "usv_navigation" });
    expect(planSimulationRun(setup(onCustom, { simulatorType: "Gazebo", waveAmplitude: 0.5 }))).toMatchObject({ where: "session", reason: expect.stringContaining("waves") });
  });

  it("keeps wind and USV Navigation on a target ship off the cluster", () => {
    expect(planSimulationRun(setup([vessel("0")], { windVector: [1, 0, 0] })).where).toBe("session");
    expect(planSimulationRun(setup([vessel("0"), vessel("1", { asvSystem: "usv_navigation" })])).where).toBe("session");
  });

  it("builds the kinematic job with the live monitor", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0", { asvSystem: "usv_navigation" }), vessel("1")])));
    if (plan.runner !== "kinematic") {
      throw new Error("expected a kinematic plan");
    }
    const submission = kinematicSimulationSubmission(plan, { scene_list: [] }, "rules");
    expect(submission).toEqual({
      job_type: "simulation",
      payload: { runner: "kinematic", mode: "usv_navigation", trajectories: { scene_list: [] }, monitor: "live", colregs_constraints_content: "rules", include_trajectories: true, own_ship_id: 0 },
      max_attempts: 1,
    });
  });

  it("builds the ArduPilot job with the reference geofence", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "ardupilot" })], { simulatorType: "Gazebo", speedup: 10 })));
    expect(simulationSubmission(plan, { trajectories: { scene_list: [] }, colregsConstraintsContent: "rules", geofence: GEOFENCE })).toEqual({
      job_type: "simulation",
      payload: {
        runner: "ardupilot",
        simulation_layer: "gazebo",
        mode: "replay",
        trajectories: { scene_list: [] },
        geofence: GEOFENCE,
        speedup: 10,
        monitor: "live",
        colregs_constraints_content: "rules",
        include_trajectories: true,
      },
      max_attempts: 1,
    });
    if (plan.runner !== "ardupilot") {
      throw new Error("expected an ArduPilot plan");
    }
    expect(arduPilotSimulationSubmission(plan, {}, { ...GEOFENCE, radius_meters: 20 }, "  ").payload).toMatchObject({ geofence: { radius_meters: 20 }, colregs_constraints_content: null });
  });

  it("submits a kinematic plan as the kinematic job", () => {
    const plan = clusterPlan(planSimulationRun(setup([vessel("0")])));
    expect(simulationSubmission(plan, { trajectories: {}, colregsConstraintsContent: "", geofence: GEOFENCE })).toMatchObject({
      job_type: "simulation",
      payload: { runner: "kinematic", mode: "replay", monitor: "live", colregs_constraints_content: null },
    });
  });

  it("says what each cluster plan runs and whether the watch speed paces it", () => {
    const kinematic = clusterPlan(planSimulationRun(setup([vessel("0")])));
    const arduPilot = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "ardupilot" })], { simulatorType: "ArduPilot Sim", speedup: 3 })));
    expect(describeClusterPlan(kinematic)).toContain("kinematic job");
    expect(describeClusterPlan(arduPilot)).toContain("ArduPilot SITL job");
    expect(describeClusterPlan(arduPilot)).toContain("3x real time");
    expect(describeClusterPlan(arduPilot)).toContain("COLREGS monitor");
    const custom = clusterPlan(planSimulationRun(setup([vessel("0", { controlLayer: "custom" })], { simulatorType: "Gazebo", windVector: [1, 0, 0] })));
    expect(describeClusterPlan(arduPilot)).toContain("plays the arriving run in the browser");
    expect(describeClusterPlan(custom)).toContain("Gazebo job with the custom controller");
    expect(describeClusterPlan(custom)).toContain("in the setup's wind");
    expect(isPacedByWatchSpeed(kinematic)).toBe(true);
    expect(isPacedByWatchSpeed(arduPilot)).toBe(false);
    expect(isPacedByWatchSpeed(custom)).toBe(true);
  });
});

function clusterPlan(plan: SimulationRunPlan): ClusterRunPlan {
  if (plan.where !== "cluster") {
    throw new Error(`expected a cluster plan, got: ${plan.reason}`);
  }
  return plan;
}

describe("an attended run", () => {
  const body = { simulatorType: "ArduPilot Sim", windVector: [0, 0, 0], simulationSpeed: 1, connectionsByAgentId: { "0": { asvSystem: "mission_planner", controlLayer: "ardupilot" }, "1": { asvSystem: "replay", controlLayer: "ardupilot" } } };
  const missionPlanner = setup([vessel("0", { asvSystem: "mission_planner", controlLayer: "ardupilot" }), vessel("1", { controlLayer: "ardupilot" })], { simulatorType: "ArduPilot Sim", body });

  it("is the plan of a setup no unattended runner takes, once the setup's body is known", () => {
    const plan = planSimulationRun(missionPlanner);
    expect(plan).toMatchObject({
      where: "cluster",
      jobType: "simulation",
      runner: "attended",
      simulation: body,
      components: ["asv_system/replay", "asv_system/mission_planner", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"],
    });
    expect(describeClusterPlan(plan as ClusterRunPlan)).toContain("waits for your Start");
    expect(isPacedByWatchSpeed(plan as ClusterRunPlan)).toBe(false);
  });

  it("takes the weather and the mixed setups the unattended jobs refuse", () => {
    const windy = setup([vessel("0"), vessel("1")], { windVector: [3, 0, 0], body: { simulatorType: "Kinematic", connectionsByAgentId: {} } });
    expect(planSimulationRun(windy)).toMatchObject({ runner: "attended", reason: expect.stringContaining("wind") });
    const twoNavigators = setup([vessel("0", { asvSystem: "usv_navigation" }), vessel("1", { asvSystem: "usv_navigation" })], { body: { simulatorType: "Kinematic", connectionsByAgentId: {} } });
    expect(planSimulationRun(twoNavigators)).toMatchObject({ runner: "attended" });
  });

  it("leaves a setup a runner takes to that runner, and a real vessel to a live session", () => {
    expect(planSimulationRun(setup([vessel("0"), vessel("1")], { body }))).toMatchObject({ runner: "kinematic" });
    const real = setup([vessel("0", { context: "real" }), vessel("1")], { body });
    expect(planSimulationRun(real)).toMatchObject({ where: "session", reason: expect.stringContaining("real vessel") });
    expect(planSimulationRun(setup([], { body }))).toMatchObject({ where: "session" });
  });

  it("submits the setup as it is, with the live monitor", () => {
    const plan = planSimulationRun(missionPlanner) as ClusterRunPlan;
    const submission = simulationSubmission(plan, { trajectories: { scene_list: [] }, colregsConstraintsContent: "rules: []", geofence: GEOFENCE });
    expect(submission).toMatchObject({ job_type: "simulation", max_attempts: 1 });
    expect(submission.payload).toMatchObject({ runner: "attended", simulation: body, geofence: GEOFENCE, monitor: "live", colregs_constraints_content: "rules: []" });
  });
});
