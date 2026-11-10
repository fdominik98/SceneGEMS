import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { campaignInputSchema } from "../../../domain/cluster/campaignApi";
import type { GazeboCustomRunPlan } from "../cluster/simulationJobs";
import { defaultReferenceGeofence } from "../connection/referenceGeofence";
import {
  entryName,
  MAX_ENTRY_SEED,
  newEntrySeed,
  scenarioClassId,
  scenarioInputName,
  sceneEntryConfig,
  simulationEntryConfig,
  simulationStack,
  toConfigYaml,
  trajectoryEntryConfig,
  WORKBENCH_ORIGIN,
  designSpaceEntryConfig,
} from "./entryConfig";

const sceneRef = { sha256: "a".repeat(64), size_bytes: 120, kind: "scene", media_type: "application/json", pointer: null };
const scenarioRef = { sha256: "d".repeat(64), size_bytes: 90, kind: "functional_scenario", media_type: "text/plain", pointer: null };
const trajectoriesRef = { sha256: "b".repeat(64), size_bytes: 400, kind: "trajectories", media_type: "application/json", pointer: "/trajectories" };
const domain = { colregsConstraintsContent: "colregs: 1\n", vesselTypesContent: "vessels: 1\n", obstacleTypesContent: "obstacles: 1\n" };

describe("scene generation entries", () => {
  it("runs one step over a functional scenario with the scene monitor, kept frames and the seed", () => {
    const config = sceneEntryConfig({ name: "Scene generation", scenarios: [{ name: "head_on", ref: scenarioRef }], domain, timeoutSeconds: 240.4, enforceLowTcpa: true, seed: 77 });
    expect(config).toMatchObject({
      format: 3,
      steps: ["scene_generation"],
      input: { functional_scenarios: [{ name: "head_on", ref: scenarioRef, quota: 1, failure_budget: 0 }] },
      domain: { colregs_constants: "colregs: 1\n", vessel_types: "vessels: 1\n", obstacle_types: "obstacles: 1\n", scene_generation_timeout_s: 240, enforce_low_tcpa: true },
      scene_generation: { monitor: "post_hoc" },
      policy: { keep_frames: true, seed: 77 },
    });
    expect(config.scope).toBeUndefined();
    expect(campaignInputSchema.safeParse(config.input).success).toBe(true);
  });

  it("leaves the monitor out when no worker node monitors", () => {
    const config = sceneEntryConfig({ name: "n", scenarios: [{ name: "s", ref: scenarioRef }], domain, timeoutSeconds: 60, enforceLowTcpa: false, seed: 1, monitor: "empty" });
    expect(config.scene_generation).toEqual({ monitor: "empty" });
  });

  it("makes a batch one entry with a scenario per row", () => {
    const config = sceneEntryConfig({
      name: "Batch",
      scenarios: [
        { name: "a", ref: scenarioRef },
        { name: "b", ref: scenarioRef },
      ],
      domain,
      timeoutSeconds: 60,
      enforceLowTcpa: false,
      seed: 3,
    });
    expect(config.input?.functional_scenarios?.map((scenario) => scenario.name)).toEqual(["a", "b"]);
  });

  it("names scenarios without slashes, distinct, and gives their class ids", () => {
    expect(scenarioInputName("2vessel_0obstacle_scenarios/fec0.problem")).toBe("2vessel_0obstacle_scenarios_fec0");
    expect(scenarioInputName("   ")).toBe("scenario");
    expect(scenarioInputName("x", new Set(["x", "x_2"]))).toBe("x_3");
    expect(scenarioInputName("y".repeat(300)).length).toBeLessThanOrEqual(200);
    expect(scenarioClassId("head_on")).toBe("scenario/head_on");
  });
});

describe("trajectory generation entries", () => {
  const scene = { name: "case 5 scene", ref: sceneRef, source: { campaign_id: "c1", case_id: 5, step: "scene_generation" as const } };

  it("plans one scene item with the search's wire parameters and the trajectory monitor", () => {
    const config = trajectoryEntryConfig({
      name: "Trajectory generation",
      scene,
      colregsConstraintsContent: "colregs: 1\n",
      params: { generator: "monitor_driven_rrt", timeStep: 15, timeout: 300, maxIterations: 2000, includeMonitorResults: true },
      seed: 9,
    });
    expect(config).toMatchObject({
      format: 3,
      steps: ["trajectory_generation"],
      input: { items: [scene] },
      domain: { colregs_constants: "colregs: 1\n" },
      trajectories: { generator: "monitor_driven_rrt", params: { timeStep: 15, timeout: 300, maxIterations: 2000, includeMonitorResults: true }, timeout_s: 420, monitor: "post_hoc" },
      policy: { keep_frames: true, seed: 9 },
    });
    expect(config.trajectories).not.toHaveProperty("timespan_s");
  });

  it("gives the straight generator its timespan and no search parameters", () => {
    const config = trajectoryEntryConfig({ name: "n", scene, colregsConstraintsContent: "", params: { generator: "straight", timeStep: 10, timespan: 600 }, seed: 1 });
    expect(config.trajectories).toEqual({ generator: "straight", timespan_s: 600, monitor: "post_hoc" });
  });

  it("takes an uploaded file as the item with the file as its source", () => {
    const config = trajectoryEntryConfig({ name: "n", scene: { ...scene, source: { file: "head_on.json" } }, colregsConstraintsContent: "", params: { generator: "straight", timespan: 60 }, seed: 1 });
    expect(campaignInputSchema.parse(config.input).items?.[0].source).toEqual({ file: "head_on.json" });
  });
});

describe("simulation entries", () => {
  it("runs one trajectory item on the kinematic layer with the live monitor", () => {
    const config = simulationEntryConfig({
      name: "Simulation",
      trajectories: { name: "planned", ref: trajectoriesRef, source: { campaign_id: "wb1", case_id: 1, step: "trajectory_generation" } },
      plan: { where: "cluster", jobType: "simulation", runner: "kinematic", mode: "usv_navigation", ownShipId: 0, components: [], summary: "" },
      colregsConstraintsContent: "colregs: 1\n",
      seed: 5,
    });
    expect(config).toMatchObject({
      format: 3,
      steps: ["simulation"],
      input: { items: [{ name: "planned", ref: trajectoriesRef }] },
      execution: { runs: [{ stack: { simulation_layer: "kinematic", mode: "usv_navigation" }, monitor: "live" }] },
      policy: { keep_frames: true, seed: 5 },
    });
  });
});

describe("ArduPilot simulation entries", () => {
  const trajectories = { name: "planned", ref: trajectoriesRef, source: { campaign_id: "wb1", case_id: 1, step: "trajectory_generation" as const } };

  it("runs one trajectory item on SITL with its pace and the Connections page's geofence", () => {
    const config = simulationEntryConfig({
      name: "Simulation",
      trajectories,
      plan: { where: "cluster", jobType: "simulation", runner: "ardupilot", simulationLayer: "ardupilot_sim", mode: "replay", ownShipId: null, speedup: 4, components: [], summary: "" },
      colregsConstraintsContent: "colregs: 1\n",
      seed: 5,
      geofence: { latitude: 58.1, longitude: 15.2, radius_meters: 35 },
    });
    expect(config).toMatchObject({
      format: 3,
      steps: ["simulation"],
      input: { items: [{ name: "planned", ref: trajectoriesRef }] },
      execution: { runs: [{ stack: { simulation_layer: "ardupilot_sim", mode: "replay", speedup: 4, geofence: { latitude: 58.1, longitude: 15.2, radius_meters: 35 } }, monitor: "live" }] },
      policy: { keep_frames: true, seed: 5 },
    });
    expect(config.execution).toEqual({ runs: [{ stack: simulationStack({ where: "cluster", jobType: "simulation", runner: "ardupilot", simulationLayer: "ardupilot_sim", mode: "replay", ownShipId: null, speedup: 4, components: [], summary: "" }, { latitude: 58.1, longitude: 15.2, radius_meters: 35 }), monitor: "live" }] });
  });

  it("uses the workbench's default reference area when none is given, and Gazebo as its own layer", () => {
    const stack = simulationStack({ where: "cluster", jobType: "simulation", runner: "ardupilot", simulationLayer: "gazebo", mode: "replay", ownShipId: null, speedup: 1, components: [], summary: "" });
    expect(stack).toEqual({ simulation_layer: "gazebo", mode: "replay", speedup: 1, geofence: { ...defaultReferenceGeofence } });
  });

  it("names USV Navigation on ArduPilot by its mode", () => {
    const stack = simulationStack({ where: "cluster", jobType: "simulation", runner: "ardupilot", simulationLayer: "gazebo", mode: "usv_navigation", ownShipId: 0, speedup: 2, components: [], summary: "" });
    expect(stack).toMatchObject({ simulation_layer: "gazebo", mode: "usv_navigation", speedup: 2 });
  });

  it("runs the custom controller on Gazebo with its control layer and the setup's wind", () => {
    const plan: GazeboCustomRunPlan = { where: "cluster", jobType: "simulation", runner: "gazebo_custom", mode: "usv_navigation", ownShipId: 0, windVector: [0, 3, 0], components: [], summary: "" };
    const config = simulationEntryConfig({ name: "Simulation", trajectories, plan: { ...plan, windVector: [0, 3, 0] }, colregsConstraintsContent: "", seed: 5 });
    expect(config.execution).toEqual({
      runs: [{ stack: { simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" }, environment: { wind_vector: [0, 3, 0] }, monitor: "live" }],
    });
    const calm = simulationEntryConfig({ name: "Simulation", trajectories, plan: { ...plan, windVector: [0, 0, 0] }, colregsConstraintsContent: "", seed: 5 });
    expect(calm.execution).toEqual({ runs: [{ stack: { simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" }, monitor: "live" }] });
  });

  it("leaves the kinematic stack as it was, without a speedup or a geofence", () => {
    expect(simulationStack({ where: "cluster", jobType: "simulation", runner: "kinematic", mode: "replay", ownShipId: null, components: [], summary: "" })).toEqual({ simulation_layer: "kinematic", mode: "replay" });
  });
});

describe("entry seeds, names and YAML", () => {
  it("draws a fresh 31-bit seed per entry", () => {
    expect(newEntrySeed(() => 0)).toBe(0);
    expect(newEntrySeed(() => 0.999999999999)).toBe(MAX_ENTRY_SEED);
    const seeds = new Set(Array.from({ length: 20 }, () => newEntrySeed()));
    expect(seeds.size).toBeGreaterThan(1);
  });

  it("serializes to YAML the control node reads back as the same config", () => {
    const config = sceneEntryConfig({ name: "Scene: x", scenarios: [{ name: "s", ref: scenarioRef }], domain: { ...domain, colregsConstraintsContent: "a: 1\nb: [2, 3]\n" }, timeoutSeconds: 60, enforceLowTcpa: false, seed: 1 });
    expect(parse(toConfigYaml(config))).toEqual(JSON.parse(JSON.stringify(config)));
  });

  it("names entries by what ran on what, and the origin by the page", () => {
    expect(entryName("Scene generation", "head_on", new Date("2026-10-28T10:20:30Z"))).toBe("Scene generation: head_on (2026-10-28 10:20)");
    expect(WORKBENCH_ORIGIN).toEqual({ designSpaceExploration: "design_space_exploration", sceneGeneration: "scene_generation", trajectoryGeneration: "trajectory_generation", simulation: "simulation" });
  });
});

describe("the design space exploration's entry", () => {
  it("runs the exploration alone with the specification inline, no input and no scope entries", () => {
    const config = designSpaceEntryConfig({ name: "explore", specification: "class OS.\n", scope: " TS = 2, StaticObstacle = 0 ", maxFecs: 100.4, timeoutSeconds: 0.2, seed: 9 });
    expect(config).toEqual({
      format: 3,
      name: "explore",
      steps: ["design_space_exploration"],
      design_space_exploration: { specification: "class OS.\n", scope: "TS = 2, StaticObstacle = 0", max_fecs: 100, timeout_s: 1 },
      policy: { keep_frames: true, seed: 9 },
    });
    expect(config.input).toBeUndefined();
    expect(config.scope).toBeUndefined();
    expect(designSpaceEntryConfig({ name: "all", specification: "x", scope: "TS = 1", maxFecs: null, timeoutSeconds: 600, seed: 0 }).design_space_exploration).toMatchObject({ max_fecs: null });
  });
});
