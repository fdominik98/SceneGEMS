import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { buildCampaignConfig, type BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { draftFromStoredConfig, runsWithoutStack } from "./storedConfigDraft";

const parsedCatalog = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsedCatalog.stacks, generators: parsedCatalog.trajectory_generators };

const SHA = "ab".repeat(32);
const CLUSTER_DOMAIN = { colregs_constants: "A: 1\n", vessel_types: "Ferry: {}\n", obstacle_types: "Buoy: {}\n" };

/** The sections every stored config has, as `CampaignConfig.to_json` writes them: every default filled in. */
const STORED_RESOURCES = { worker_nodes: [], required_labels: {}, queue_depth: { generate_scene: 16, generate_trajectories: 16, simulate: 32, monitor: 32, calibrate: 8 }, priority: 0 };
const STORED_POLICY = { retention: "all", keep_frames: false, seed: 20261029, stop: { max_cases: null, max_failed_verdicts: null, max_duration_s: null } };
const STORED_ENVIRONMENT = { wind_vector: [0.0, 0.0, 0.0], waves: null };

function storedRun(name: string | null, stack: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return { name, stack, environment: STORED_ENVIRONMENT, seed: null, repeats: 1, monitor: "post_hoc", early_stop: false, ...extra };
}

/** `05_usv_navigation_comparison.yaml` as the control node stores it for a campaign on a cluster with `CLUSTER_DOMAIN`. */
const STORED_FULL_CHAIN = {
  format: 3,
  name: "USV Navigation against the planned trajectories",
  description: "Three cases of every two- and three-vessel FEC.",
  steps: ["scene_generation", "trajectory_generation", "simulation"],
  scope: [{ fecs: [], patterns: ["2vessel_*_scenarios", "3vessel_*_scenarios"], quota: 3, failure_budget: 3 }],
  input: { functional_scenarios: [], items: [] },
  domain: { ...CLUSTER_DOMAIN, scene_generation_timeout_s: 120, enforce_low_tcpa: false },
  scene_generation: { monitor: "empty" },
  trajectories: { generator: "monitor_driven_rrt", params: {}, timespan_s: null, timeout_s: 1800.0, monitor: "empty" },
  execution: {
    runs: [
      storedRun("planned trajectories", { simulation_layer: "kinematic", mode: "replay", usv_navigation: null, dt: null, steps: null }),
      storedRun("usv navigation own ship", { simulation_layer: "kinematic", mode: "usv_navigation", usv_navigation: null, dt: null, steps: null }),
    ],
  },
  resources: STORED_RESOURCES,
  policy: STORED_POLICY,
};

/** A campaign that plans and simulates from a scene of Campaign History and an uploaded scene. */
const STORED_FROM_ITEMS = {
  format: 3,
  name: "Planned from case 12",
  description: "",
  steps: ["trajectory_generation"],
  scope: [],
  input: {
    functional_scenarios: [],
    items: [
      { name: "case 12 scene", ref: { sha256: SHA, size_bytes: 900, kind: "scene", media_type: "application/json", pointer: null }, source: { campaign_id: "c-1", case_id: 12, step: "scene_generation", file: null } },
      { name: "uploaded", ref: { sha256: SHA, size_bytes: 5, kind: "scene", media_type: "application/json", pointer: null }, source: { campaign_id: null, case_id: null, step: null, file: "f.json" } },
    ],
  },
  domain: { ...CLUSTER_DOMAIN, scene_generation_timeout_s: 60, enforce_low_tcpa: false },
  scene_generation: { monitor: "empty" },
  trajectories: { generator: "straight", params: {}, timespan_s: 600.0, timeout_s: 1800.0, monitor: "post_hoc" },
  execution: { runs: [storedRun(null, { simulation_layer: "kinematic", mode: "replay", usv_navigation: null, dt: null, steps: null })] },
  resources: STORED_RESOURCES,
  policy: { ...STORED_POLICY, seed: 0 },
};

/** Without the ids the draft gives its list entries. */
function plain(config: Record<string, unknown>) {
  return JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
}

describe("draftFromStoredConfig", () => {
  it("builds the config the operator wrote from a stored one with every default filled in", () => {
    const draft = draftFromStoredConfig(STORED_FULL_CHAIN, catalog, { clusterDomain: CLUSTER_DOMAIN });
    expect(checkDraft(draft, catalog, 0)).toEqual([]);
    expect(plain(buildCampaignConfig(draft, catalog))).toEqual({
      format: 3,
      name: STORED_FULL_CHAIN.name,
      description: STORED_FULL_CHAIN.description,
      steps: STORED_FULL_CHAIN.steps,
      scope: [{ patterns: ["2vessel_*_scenarios", "3vessel_*_scenarios"], quota: 3, failure_budget: 3 }],
      domain: { scene_generation_timeout_s: 120, enforce_low_tcpa: false },
      trajectories: { generator: "monitor_driven_rrt", timeout_s: 1800 },
      execution: {
        runs: [
          { name: "planned trajectories", stack: { simulation_layer: "kinematic", mode: "replay" }, repeats: 1, monitor: "post_hoc" },
          { name: "usv navigation own ship", stack: { simulation_layer: "kinematic", mode: "usv_navigation" }, repeats: 1, monitor: "post_hoc" },
        ],
      },
      resources: { priority: 0 },
      policy: { retention: "all", keep_frames: false, seed: 20261029 },
    });
  });

  it("reads a group nobody set as left out, so the run does not ask for its required parameters", () => {
    const draft = draftFromStoredConfig(STORED_FULL_CHAIN, catalog);
    expect(draft.runs.map((run) => [run.stackId, run.groups, run.stackParameters, run.windVector])).toEqual([
      ["kinematic.replay", {}, {}, null],
      ["kinematic.usv_navigation", {}, {}, null],
    ]);
    expect(runsWithoutStack(draft)).toBe(0);
  });

  it("keeps the stack parameters, groups, wind and stop conditions that were set", () => {
    const run = storedRun(
      "sitl",
      { simulation_layer: "ardupilot_sim", mode: "replay", speedup: 10, dt: null, steps: 30, geofence: { latitude: 58.0, longitude: 16.6, radius_meters: 20.0 } },
      { environment: { wind_vector: [0, 3, 0], waves: null }, seed: 7, repeats: 3 }
    );
    const stored = { ...STORED_FULL_CHAIN, execution: { runs: [run] }, policy: { ...STORED_POLICY, retention: "failures", stop: { max_cases: 10, max_failed_verdicts: null, max_duration_s: null } } };
    const draft = draftFromStoredConfig(stored, catalog);
    expect(draft.runs[0]).toMatchObject({
      stackId: "ardupilot_sim.replay",
      seed: 7,
      repeats: 3,
      stackParameters: { speedup: 10, steps: 30 },
      groups: { geofence: { latitude: 58.0, longitude: 16.6, radius_meters: 20.0 } },
      windVector: [0, 3, 0],
    });
    expect(draft.policy).toMatchObject({ retention: "failures", maxCases: 10, maxFailedVerdicts: null });
  });

  it("uses the cluster's domain configuration when the stored contents are the cluster's, and keeps contents that differ", () => {
    expect(draftFromStoredConfig(STORED_FULL_CHAIN, catalog, { clusterDomain: CLUSTER_DOMAIN }).domain).toMatchObject({ custom: false, colregsConstants: "", sceneGenerationTimeoutS: 120 });
    // Line endings alone are no difference
    const windows = { ...CLUSTER_DOMAIN, vessel_types: "Ferry: {}\r\n" };
    expect(draftFromStoredConfig(STORED_FULL_CHAIN, catalog, { clusterDomain: windows }).domain.custom).toBe(false);

    const changed = { ...CLUSTER_DOMAIN, vessel_types: "Tanker: {}\n" };
    expect(draftFromStoredConfig(STORED_FULL_CHAIN, catalog, { clusterDomain: changed }).domain).toMatchObject({ custom: true, vesselTypes: "Ferry: {}\n", colregsConstants: "A: 1\n" });
    // Without the cluster's configuration nothing says the contents are its own
    expect(draftFromStoredConfig(STORED_FULL_CHAIN, catalog).domain.custom).toBe(true);
  });

  it("keeps the input items with their sources, as files the control node holds", () => {
    const draft = draftFromStoredConfig(STORED_FROM_ITEMS, catalog, { clusterDomain: CLUSTER_DOMAIN });
    expect(draft.input.items.map(({ name, source, uploadedAt }) => ({ name, source, uploadedAt }))).toEqual([
      { name: "case 12 scene", source: { campaign_id: "c-1", case_id: 12, step: "scene_generation" }, uploadedAt: null },
      { name: "uploaded", source: { file: "f.json" }, uploadedAt: null },
    ]);
    // Far in the future: a file an entry uses does not expire
    expect(checkDraft(draft, catalog, Date.UTC(2100, 0, 1))).toEqual([]);
    const config = plain(buildCampaignConfig(draft, catalog));
    expect(config.input).toEqual({
      items: [
        { name: "case 12 scene", ref: { sha256: SHA, size_bytes: 900, kind: "scene" }, source: { campaign_id: "c-1", case_id: 12, step: "scene_generation" } },
        { name: "uploaded", ref: { sha256: SHA, size_bytes: 5, kind: "scene" }, source: { file: "f.json" } },
      ],
    });
    // The straight generator has no parameter section of its own: the planner's empty one is not a parameter
    expect(config.trajectories).toEqual({ generator: "straight", timespan_s: 600, timeout_s: 1800, monitor: "post_hoc" });
    expect([config.scope, config.execution]).toEqual([undefined, undefined]);
  });

  it("keeps uploaded scenario files with their quota and failure budget", () => {
    const scenario = { name: "my_head_on", ref: { sha256: SHA, size_bytes: 120, kind: "functional_scenario", media_type: "text/plain; charset=utf-8", pointer: null }, quota: 3, failure_budget: "unlimited" };
    const stored = { ...STORED_FULL_CHAIN, steps: ["scene_generation"], scope: [], input: { functional_scenarios: [scenario], items: [] } };
    const draft = draftFromStoredConfig(stored, catalog, { clusterDomain: CLUSTER_DOMAIN });
    expect(draft.input.scenarios).toEqual([expect.objectContaining({ name: "my_head_on", fileName: "my_head_on", quota: 3, failureBudget: "unlimited", uploadedAt: null })]);
    expect(checkDraft(draft, catalog, Date.UTC(2100, 0, 1))).toEqual([]);
    const config = plain(buildCampaignConfig(draft, catalog));
    expect(config.input).toEqual({
      functional_scenarios: [{ name: "my_head_on", ref: { sha256: SHA, size_bytes: 120, kind: "functional_scenario", media_type: "text/plain; charset=utf-8" }, quota: 3, failure_budget: "unlimited" }],
    });
    expect(config.scope).toBeUndefined();
  });

  it("leaves out an input entry it cannot read", () => {
    const stored = { ...STORED_FROM_ITEMS, input: { functional_scenarios: [{ name: "no ref" }], items: [{ name: "no source", ref: { sha256: SHA, kind: "scene" }, source: {} }, "text"] } };
    expect(draftFromStoredConfig(stored, catalog).input).toEqual({ scenarios: [], items: [] });
  });

  it("uses every worker node unless the campaign named some, and keeps the stored queue caps for then", () => {
    const any = draftFromStoredConfig(STORED_FULL_CHAIN, catalog);
    expect(any.resources).toMatchObject({ fullUsage: true, workerNodes: [] });
    const resources = { ...STORED_RESOURCES, worker_nodes: ["worker-node-2"], required_labels: { gpu: "yes" }, queue_depth: { ...STORED_RESOURCES.queue_depth, simulate: 4 }, priority: 5 };
    const named = draftFromStoredConfig({ ...STORED_FULL_CHAIN, resources }, catalog);
    expect(named.resources).toMatchObject({ fullUsage: false, workerNodes: ["worker-node-2"], labels: [{ key: "gpu", value: "yes" }], priority: 5 });
    expect(named.resources.queueDepth.simulate).toBe(4);
    expect(buildCampaignConfig(named, catalog).resources).toEqual({ worker_nodes: ["worker-node-2"], required_labels: { gpu: "yes" }, queue_depth: { simulate: 4 }, priority: 5 });
  });

  it("reads a config stored before the steps existed as the whole chain, with its FECs under classes", () => {
    const stored = { name: "lab", scope: [{ classes: ["2vessel_0obstacle_scenarios/fec1"], patterns: [], quota: 2, failure_budget: 0 }], execution: STORED_FULL_CHAIN.execution, resources: STORED_RESOURCES, policy: STORED_POLICY };
    const draft = draftFromStoredConfig(stored, catalog);
    expect(draft.steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(draft.scope.map((entry) => entry.classes)).toEqual([["2vessel_0obstacle_scenarios/fec1"]]);
  });

  it("counts the runs whose stack the control node does not offer, only when the campaign simulates", () => {
    const carla = { ...STORED_FULL_CHAIN, execution: { runs: [storedRun("x", { simulation_layer: "carla", mode: "replay" })] } };
    expect(runsWithoutStack(draftFromStoredConfig(carla, catalog))).toBe(1);
    expect(runsWithoutStack(draftFromStoredConfig({ ...carla, steps: ["scene_generation"] }, catalog))).toBe(0);
  });
});
