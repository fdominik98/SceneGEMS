import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { buildCampaignConfig, buildCampaignYaml, configToYaml, supportsEnvironment, type BuilderCatalog } from "./configBuilder";
import { emptyDraft, emptyRun, type WizardDraft } from "./wizardState";

/** `backend/src/tests/scenegems_tool/assurance/campaign/data/exit_campaign.yaml` (the Phase 4 exit campaign) as the wizard writes it: format 3 with the whole chain. */
const EXIT_CAMPAIGN_YAML = `
format: 3
name: phase 4 exit campaign
description: Two- and three-vessel classes at quota 15 with USV Navigation on the kinematic layer.
steps: [scene_generation, trajectory_generation, simulation]
scope:
  - patterns: [2vessel_*_scenarios, 3vessel_*_scenarios]
    quota: 15
    failure_budget: 15
domain:
  scene_generation_timeout_s: 60
  enforce_low_tcpa: false
trajectories:
  generator: monitor_driven_rrt
  timeout_s: 1800
execution:
  runs:
    - name: usv_navigation
      stack:
        simulation_layer: kinematic
        mode: usv_navigation
      repeats: 1
      monitor: post_hoc
resources:
  priority: 0
policy:
  retention: all
  keep_frames: false
  seed: 20261025
`;

const parsedCatalog = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsedCatalog.stacks, generators: parsedCatalog.trajectory_generators };

function exitDraft(): WizardDraft {
  const draft = emptyDraft();
  draft.name = "phase 4 exit campaign";
  draft.description = "Two- and three-vessel classes at quota 15 with USV Navigation on the kinematic layer.";
  draft.scope = [{ id: "s1", classes: [], patterns: ["2vessel_*_scenarios", "3vessel_*_scenarios"], quota: 15, failureBudget: 15 }];
  draft.runs = [{ ...emptyRun("kinematic.usv_navigation", "post_hoc"), id: "r1", name: "usv_navigation" }];
  draft.policy.seed = 20261025;
  return draft;
}

describe("buildCampaignConfig", () => {
  it("builds the exit campaign from the wizard's state", () => {
    expect(parse(buildCampaignYaml(exitDraft(), catalog))).toEqual(parse(EXIT_CAMPAIGN_YAML));
  });

  it("writes the sections in the config's order", () => {
    expect(Object.keys(buildCampaignConfig(exitDraft(), catalog))).toEqual([
      "format",
      "name",
      "description",
      "steps",
      "scope",
      "domain",
      "trajectories",
      "execution",
      "resources",
      "policy",
    ]);
  });

  it("leaves the domain texts out while the control node's defaults are used, and writes them when customized", () => {
    const draft = exitDraft();
    expect(Object.keys(buildCampaignConfig(draft, catalog).domain as object)).toEqual(["scene_generation_timeout_s", "enforce_low_tcpa"]);
    draft.domain.custom = true;
    draft.domain.colregsConstants = "# c\nA: 1\r\nB: 2\n";
    draft.domain.vesselTypes = "Unspecified:\n  length: 10\n";
    draft.domain.obstacleTypes = "Rock:\n  radius: 4\n";
    draft.domain.enforceLowTcpa = true;
    const domain = buildCampaignConfig(draft, catalog).domain as Record<string, unknown>;
    expect(Object.keys(domain)).toEqual(["colregs_constants", "vessel_types", "obstacle_types", "scene_generation_timeout_s", "enforce_low_tcpa"]);
    expect(domain.colregs_constants).toBe("# c\nA: 1\nB: 2\n");
    expect(domain.enforce_low_tcpa).toBe(true);
  });

  it("keeps multi-line domain content intact through the YAML text", () => {
    const draft = exitDraft();
    draft.domain.custom = true;
    draft.domain.colregsConstants = "# Section: head on\nHEAD_ON_ANGLE: 0.3 # radians\n\nOTHER:\n  nested: 1.5\n";
    draft.domain.vesselTypes = "Unspecified:\n  length: 10\n  beam: 2\n";
    draft.domain.obstacleTypes = "Rock:\n  radius: 4\n";
    const text = buildCampaignYaml(draft, catalog);
    const parsed = parse(text) as { domain: Record<string, string> };
    expect(parsed.domain.colregs_constants).toBe(draft.domain.colregsConstants);
    expect(parsed.domain.vessel_types).toBe(draft.domain.vesselTypes);
    expect(text).toContain("colregs_constants: |");
  });

  it("writes the search parameters under params by their wire keys, and the straight timespan as a field", () => {
    const draft = exitDraft();
    draft.trajectories.parameters = { maxIterations: 4000, includeMonitorResults: false, bestRandomNodesK: 5, timeout: null };
    let trajectories = buildCampaignConfig(draft, catalog).trajectories as Record<string, unknown>;
    expect(trajectories).toEqual({
      generator: "monitor_driven_rrt",
      params: { bestRandomNodesK: 5, maxIterations: 4000, includeMonitorResults: false },
      timeout_s: 1800,
    });
    draft.trajectories.generator = "straight";
    draft.trajectories.parameters = { timespan_s: 120 };
    trajectories = buildCampaignConfig(draft, catalog).trajectories as Record<string, unknown>;
    expect(trajectories).toEqual({ generator: "straight", timespan_s: 120, timeout_s: 1800 });
  });

  it("builds a run with its seed, repeats, live monitor, early stop and stack parameters", () => {
    const draft = exitDraft();
    Object.assign(draft.runs[0], { monitor: "live", earlyStop: true, seed: 7, repeats: 3, stackParameters: { dt: 0.5, steps: null } });
    const run = (buildCampaignConfig(draft, catalog).execution as { runs: Record<string, unknown>[] }).runs[0];
    expect(run).toEqual({
      name: "usv_navigation",
      stack: { simulation_layer: "kinematic", mode: "usv_navigation", dt: 0.5 },
      seed: 7,
      repeats: 3,
      monitor: "live",
      early_stop: true,
    });
  });

  it("writes the USV Navigation group only when it is set, with numbers and the runtime options", () => {
    const draft = exitDraft();
    const stackOf = () => ((buildCampaignConfig(draft, catalog).execution as { runs: { stack: Record<string, unknown> }[] }).runs[0].stack);
    expect(stackOf()).not.toHaveProperty("usv_navigation");
    draft.runs[0].groups = {
      usv_navigation: { goal: [100, -20.5], speed: 4, safety_radius: 30, control_horizon: 60, runtime_options: { K: 2 } },
    };
    expect(stackOf().usv_navigation).toEqual({ goal: [100, -20.5], speed: 4, safety_radius: 30, control_horizon: 60, runtime_options: { K: 2 } });
    const text = buildCampaignYaml(draft, catalog);
    expect(text).toContain("goal: [100, -20.5]");
  });

  it("writes the stack section that picks the catalog option: the control layer only for the custom controller", () => {
    const draft = exitDraft();
    const stackOf = (stackId: string) => {
      draft.runs[0] = { ...draft.runs[0], stackId, stackParameters: {}, groups: {} };
      return (buildCampaignConfig(draft, catalog).execution as { runs: { stack: Record<string, unknown> }[] }).runs[0].stack;
    };
    expect(stackOf("ardupilot_sim.usv_navigation")).toEqual({ simulation_layer: "ardupilot_sim", mode: "usv_navigation" });
    expect(stackOf("ardupilot_sim.replay")).toEqual({ simulation_layer: "ardupilot_sim", mode: "replay" });
    expect(stackOf("gazebo_custom.replay")).toEqual({ simulation_layer: "gazebo", control_layer: "custom", mode: "replay" });
    const older = { ...catalog, stacks: catalog.stacks.map((stack) => ({ ...stack, stack_section: undefined })) };
    draft.runs[0].stackId = "kinematic.usv_navigation";
    expect((buildCampaignConfig(draft, older).execution as { runs: { stack: Record<string, unknown> }[] }).runs[0].stack).toEqual({
      simulation_layer: "kinematic",
      mode: "usv_navigation",
    }); // an older control node's catalog
  });

  it("keeps the wind and waves of the custom controller, which supports them", () => {
    const draft = exitDraft();
    Object.assign(draft.runs[0], { stackId: "gazebo_custom.replay", groups: {}, windVector: [0, 3, 0], waves: { amplitude: 0.5, period: 5, steepness: 0, direction: [1, 0] } });
    const run = (buildCampaignConfig(draft, catalog).execution as { runs: Record<string, unknown>[] }).runs[0];
    expect(run.environment).toEqual({ wind_vector: [0, 3, 0], waves: { amplitude: 0.5, period: 5, steepness: 0, direction: [1, 0] } });
  });

  it("drops the environment of a stack that does not support it", () => {
    const draft = exitDraft();
    Object.assign(draft.runs[0], { windVector: [1, 2, 0], waves: { amplitude: 1, period: 2, steepness: 0.1, direction: [1, 0] } });
    const run = (buildCampaignConfig(draft, catalog).execution as { runs: Record<string, unknown>[] }).runs[0];
    expect(run).not.toHaveProperty("environment");
    const permissive: BuilderCatalog = {
      ...catalog,
      stacks: catalog.stacks.map((stack) => ({ ...stack, environment: { wind: "supported", waves: "unmeasured", interactive_only: false } })),
    };
    const withEnvironment = (buildCampaignConfig(draft, permissive).execution as { runs: Record<string, unknown>[] }).runs[0];
    expect(withEnvironment.environment).toEqual({ wind_vector: [1, 2, 0], waves: { amplitude: 1, period: 2, steepness: 0.1, direction: [1, 0] } });
    expect(supportsEnvironment(catalog.stacks[0])).toEqual({ wind: false, waves: false });
    expect(supportsEnvironment(undefined)).toEqual({ wind: false, waves: false });
  });

  it("writes only the resources that differ from the defaults", () => {
    const draft = exitDraft();
    draft.resources.fullUsage = false;
    draft.resources.workerNodes = ["worker-node-b", "worker-node-a"];
    draft.resources.labels = [
      { key: "site", value: "lab" },
      { key: "  ", value: "" },
    ];
    draft.resources.queueDepth.simulate = 64;
    draft.resources.queueDepth.monitor = 32;
    draft.resources.priority = 5;
    expect(buildCampaignConfig(draft, catalog).resources).toEqual({ worker_nodes: ["worker-node-a", "worker-node-b"], required_labels: { site: "lab" }, queue_depth: { simulate: 64 }, priority: 5 });
  });

  it("names no worker nodes and sizes the queues to the cluster's slots in full usage", () => {
    const draft = exitDraft();
    draft.resources.workerNodes = ["worker-node-a"];
    draft.resources.queueDepth.simulate = 4;
    expect(buildCampaignConfig(draft, catalog).resources).toEqual({ priority: 0 });
    const cluster: BuilderCatalog = { ...catalog, slots: { scene_generation: 40, simulation: 12, "monitoring.post_hoc": 64 } };
    expect(buildCampaignConfig(draft, cluster).resources).toEqual({ queue_depth: { generate_scene: 40, monitor: 64 }, priority: 0 });
  });

  it("keeps the operator's queue caps when the machines are chosen", () => {
    const draft = exitDraft();
    draft.resources.fullUsage = false;
    draft.resources.workerNodes = ["worker-node-a"];
    const cluster: BuilderCatalog = { ...catalog, slots: { scene_generation: 40 } };
    expect(buildCampaignConfig(draft, cluster).resources).toEqual({ worker_nodes: ["worker-node-a"], priority: 0 });
  });

  it("writes the stop conditions that are set", () => {
    const draft = exitDraft();
    Object.assign(draft.policy, { retention: "failures", keepFrames: true, maxCases: 500, maxDurationS: 3600 });
    expect(buildCampaignConfig(draft, catalog).policy).toEqual({
      retention: "failures",
      keep_frames: true,
      seed: 20261025,
      stop: { max_cases: 500, max_duration_s: 3600 },
    });
  });

  it("writes several scope entries, classes and patterns apart", () => {
    const draft = exitDraft();
    draft.scope = [
      { id: "a", classes: ["3vessel_0obstacle_scenarios/fec5"], patterns: [], quota: 3, failureBudget: 0 },
      { id: "b", classes: [], patterns: ["4vessel_*_scenarios"], quota: 1, failureBudget: null },
    ];
    expect(buildCampaignConfig(draft, catalog).scope).toEqual([
      { fecs: ["3vessel_0obstacle_scenarios/fec5"], quota: 3, failure_budget: 0 },
      { patterns: ["4vessel_*_scenarios"], quota: 1 },
    ]);
  });

  it("writes an unlimited failure budget as unlimited", () => {
    const draft = exitDraft();
    draft.scope = [{ id: "a", classes: [], patterns: ["2vessel_*_scenarios"], quota: 2, failureBudget: "unlimited" }];
    expect(buildCampaignConfig(draft, catalog).scope).toEqual([{ patterns: ["2vessel_*_scenarios"], quota: 2, failure_budget: "unlimited" }]);
  });
});

describe("configToYaml", () => {
  it("does not fold long text and keeps lists of numbers inline", () => {
    const long = "word ".repeat(60).trim();
    const text = configToYaml({ description: long, point: [1, 2], names: ["a", "b"] });
    expect(text).toContain(`description: ${long}`);
    expect(text).toContain("point: [1, 2]");
    expect(text).toMatch(/names:\n {2}- a\n {2}- b/);
  });
});
