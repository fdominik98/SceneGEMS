import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { buildCampaignConfig, type BuilderCatalog } from "./configBuilder";
import { draftFromConfig, draftHasEntries, presetConfigOf, stackIdOf } from "./presetDraft";
import { emptyDraft, emptyRun } from "./wizardState";

const parsedCatalog = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsedCatalog.stacks, generators: parsedCatalog.trajectory_generators };

/** `backend/assets/campaign_presets/05_usv_navigation_comparison.yaml` as the master serves it (a preset holds no input). */
const USV_PRESET = parse(`
format: 3
name: "USV Navigation against the planned trajectories"
description: Three cases of every two- and three-vessel class, each simulated twice.
steps: [scene_generation, trajectory_generation, simulation]
scope:
  - patterns: [2vessel_*_scenarios, 3vessel_*_scenarios]
    quota: 3
    failure_budget: 3
domain:
  scene_generation_timeout_s: 120
  enforce_low_tcpa: false
trajectories:
  generator: monitor_driven_rrt
  timeout_s: 1800
execution:
  runs:
    - name: planned trajectories
      stack: {simulation_layer: kinematic, mode: replay}
      repeats: 1
      monitor: post_hoc
    - name: usv navigation own ship
      stack: {simulation_layer: kinematic, mode: usv_navigation}
      repeats: 1
      monitor: post_hoc
policy:
  retention: all
  seed: 20261029
`) as Record<string, unknown>;

/** Without the ids the draft gives its list entries. */
function withoutIds(config: Record<string, unknown>) {
  return JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
}

describe("draftFromConfig", () => {
  it("turns a shipped preset into a draft that builds the same config", () => {
    const draft = draftFromConfig(USV_PRESET, catalog);
    expect(draft.name).toBe("USV Navigation against the planned trajectories");
    expect(draft.runs.map((run) => [run.name, run.stackId])).toEqual([
      ["planned trajectories", "kinematic.replay"],
      ["usv navigation own ship", "kinematic.usv_navigation"],
    ]);
    expect(draft.domain).toMatchObject({ custom: false, sceneGenerationTimeoutS: 120 });
    expect(draft.resources.fullUsage).toBe(true);
    expect(withoutIds(buildCampaignConfig(draft, catalog))).toEqual({ ...USV_PRESET, resources: { priority: 0 }, policy: { retention: "all", keep_frames: false, seed: 20261029 } });
  });

  it("keeps the stack parameters, groups, environment and policy of a run", () => {
    const config = {
      format: 2,
      name: "sitl nightly",
      steps: ["simulation"],
      domain: { colregs_constants: "A: 1\n", vessel_types: "Ferry: {}\n", obstacle_types: "Buoy: {}\n" },
      execution: { runs: [{ stack: { simulation_layer: "ardupilot_sim", mode: "replay", speedup: 10, geofence: { radius_meters: 900 } }, repeats: 3, monitor: "post_hoc", seed: 7 }] },
      resources: { nodes: ["node-2"], required_labels: { gpu: "yes" }, queue_depth: { simulate: 4 }, priority: 5 },
      policy: { retention: "failures", keep_frames: true, seed: 3, stop: { max_cases: 10 } },
    };
    const draft = draftFromConfig(config, catalog);
    const [run] = draft.runs;
    expect(run).toMatchObject({ stackId: "ardupilot_sim.replay", repeats: 3, seed: 7, stackParameters: { speedup: 10 }, groups: { geofence: { radius_meters: 900 } } });
    expect(draft.domain).toMatchObject({ custom: true, colregsConstants: "A: 1\n" });
    expect(draft.resources).toMatchObject({ fullUsage: false, nodes: ["node-2"], labels: [{ key: "gpu", value: "yes" }], priority: 5 });
    expect(draft.resources.queueDepth.simulate).toBe(4);
    expect(draft.policy).toMatchObject({ retention: "failures", keepFrames: true, seed: 3, maxCases: 10 });
    expect(draft.steps).toEqual(["simulation"]);
  });

  it("keeps an unlimited failure budget and reads a missing one as 0", () => {
    const scope = [
      { patterns: ["2vessel_*_scenarios"], quota: 3, failure_budget: "unlimited" },
      { patterns: ["3vessel_*_scenarios"], quota: 1 },
    ];
    const draft = draftFromConfig({ ...USV_PRESET, scope }, catalog);
    expect(draft.scope.map((entry) => entry.failureBudget)).toEqual(["unlimited", 0]);
    expect(buildCampaignConfig(draft, catalog).scope).toEqual([
      { patterns: ["2vessel_*_scenarios"], quota: 3, failure_budget: "unlimited" },
      { patterns: ["3vessel_*_scenarios"], quota: 1, failure_budget: 0 },
    ]);
  });

  it("reads a preset saved in format 2, whose entries list their FECs under classes, and writes it as format 3", () => {
    const draft = draftFromConfig({ ...USV_PRESET, format: 2, scope: [{ classes: ["2vessel_0obstacle_scenarios/fec1"], quota: 2 }] }, catalog);
    expect(draft.scope.map((entry) => entry.classes)).toEqual([["2vessel_0obstacle_scenarios/fec1"]]);
    const config = buildCampaignConfig(draft, catalog);
    expect([config.format, config.scope]).toEqual([3, [{ fecs: ["2vessel_0obstacle_scenarios/fec1"], quota: 2, failure_budget: 0 }]]);
  });

  it("leaves a run without a stack the master does not offer", () => {
    expect(stackIdOf({ simulation_layer: "carla" }, catalog)).toBe("");
    expect(stackIdOf({}, catalog)).toBe("kinematic.replay");
  });

  it("tells the stacks of a layer apart by their mode and control layer", () => {
    expect(stackIdOf({ simulation_layer: "ardupilot_sim" }, catalog)).toBe("ardupilot_sim.replay");
    expect(stackIdOf({ simulation_layer: "ardupilot_sim", mode: "usv_navigation" }, catalog)).toBe("ardupilot_sim.usv_navigation");
    expect(stackIdOf({ simulation_layer: "ardupilot_sim", control_layer: "ardupilot" }, catalog)).toBe("ardupilot_sim.replay"); // the implied control layer named
    expect(stackIdOf({ simulation_layer: "gazebo", control_layer: "custom" }, catalog)).toBe("gazebo_custom.replay");
    expect(stackIdOf({ simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" }, catalog)).toBe("gazebo_custom.usv_navigation");
    expect(stackIdOf({ simulation_layer: "gazebo" }, catalog)).toBe(""); // ArduPilot on Gazebo is not in the sample catalog
  });

  it("reads a custom controller run back with its parameters, groups and environment", () => {
    const usvNavigation = { goal: [100, 0], speed: 4, safety_radius: 30, control_horizon: 60 };
    const run = {
      stack: { simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation", dt: 2, usv_navigation: usvNavigation },
      environment: { wind_vector: [0, 3, 0] },
      monitor: "live",
    };
    const draft = draftFromConfig({ ...USV_PRESET, execution: { runs: [run] } }, catalog);
    expect(draft.runs[0].stackId).toBe("gazebo_custom.usv_navigation");
    expect(draft.runs[0].stackParameters).toEqual({ dt: 2 });
    expect(draft.runs[0].groups).toEqual({ usv_navigation: usvNavigation });
    const written = (buildCampaignConfig(draft, catalog).execution as { runs: Record<string, unknown>[] }).runs[0];
    expect(written.stack).toEqual(run.stack);
    expect(written.environment).toEqual({ wind_vector: [0, 3, 0] });
  });
});

describe("presetConfigOf", () => {
  it("leaves out the input and the queue caps of full usage", () => {
    const draft = emptyDraft();
    draft.name = "from files";
    draft.steps = ["trajectory_generation", "simulation"];
    draft.input.items = [{ id: "i", name: "scene", ref: { sha256: "a".repeat(64), size_bytes: 1, kind: "scene" }, source: { file: "s.json" }, uploadedAt: 0 }];
    draft.runs = [{ ...emptyRun("kinematic.replay"), id: "r" }];
    const config = presetConfigOf(draft, { ...catalog, slots: { simulation: 64 } });
    expect(config.input).toBeUndefined();
    expect(config.resources).toEqual({ priority: 0 });
    expect(draftFromConfig(config, catalog).steps).toEqual(["trajectory_generation", "simulation"]);
  });
});

describe("draftHasEntries", () => {
  it("is false for an empty draft and true once something was entered", () => {
    expect(draftHasEntries(emptyDraft())).toBe(false);
    const named = emptyDraft();
    named.name = "x";
    expect(draftHasEntries(named)).toBe(true);
    const scoped = emptyDraft();
    scoped.scope[0].patterns = ["2vessel_*"];
    expect(draftHasEntries(scoped)).toBe(true);
  });
});
