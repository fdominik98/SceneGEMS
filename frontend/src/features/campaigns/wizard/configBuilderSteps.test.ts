import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { buildCampaignConfig, buildCampaignYaml, stagesOf, type BuilderCatalog } from "./configBuilder";
import { emptyDraft, emptyRun, type InputItemDraft, type ScenarioFileDraft, type WizardDraft } from "./wizardState";

/** The config for every choice of steps and every kind of input (design doc 6.3, format 3). */

const parsedCatalog = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsedCatalog.stacks, generators: parsedCatalog.trajectory_generators };

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);

function baseDraft(): WizardDraft {
  const draft = emptyDraft();
  draft.name = "partial";
  draft.scope = [{ id: "s1", classes: ["2vessel_0obstacle_scenarios/fec1"], patterns: [], quota: 2, failureBudget: 0 }];
  draft.runs = [{ ...emptyRun("kinematic.usv_navigation", "post_hoc"), id: "r1", name: "usv" }];
  return draft;
}

function scenario(overrides: Partial<ScenarioFileDraft> = {}): ScenarioFileDraft {
  return {
    id: "sc1",
    fileName: "my_head_on.problem",
    name: "my_head_on",
    ref: { sha256: SHA_A, size_bytes: 812, kind: "functional_scenario", media_type: "text/plain" },
    quota: 3,
    failureBudget: 1,
    uploadedAt: 1,
    ...overrides,
  };
}

function item(overrides: Partial<InputItemDraft> = {}): InputItemDraft {
  return {
    id: "it1",
    name: "case 5 scene",
    ref: { sha256: SHA_B, size_bytes: 20480, kind: "scene", media_type: "application/json", pointer: null },
    source: { campaign_id: "c1", case_id: 5, step: "scene_generation" },
    uploadedAt: null,
    ...overrides,
  };
}

function keysOf(draft: WizardDraft): string[] {
  return Object.keys(buildCampaignConfig(draft, catalog));
}

describe("buildCampaignConfig steps", () => {
  it("writes format 3 and the steps in chain order", () => {
    const config = buildCampaignConfig(baseDraft(), catalog);
    expect(config.format).toBe(3);
    expect(config.steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
  });

  it("writes scene generation alone with its monitor and nothing of the later steps", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation"];
    draft.sceneMonitor = "post_hoc";
    draft.trajectoryMonitor = "post_hoc";
    const config = buildCampaignConfig(draft, catalog);
    expect(Object.keys(config)).toEqual(["format", "name", "steps", "scope", "domain", "scene_generation", "resources", "policy"]);
    expect(config.scene_generation).toEqual({ monitor: "post_hoc" });
    expect(config.steps).toEqual(["scene_generation"]);
  });

  it("leaves the scene monitor out while it is none, and the section with it", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation", "trajectory_generation"];
    expect(keysOf(draft)).not.toContain("scene_generation");
    draft.sceneMonitor = "post_hoc";
    expect(keysOf(draft)).toContain("scene_generation");
  });

  it("writes the trajectory monitor last in the trajectories section, only when it is post hoc", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation", "trajectory_generation"];
    expect(buildCampaignConfig(draft, catalog).trajectories).toEqual({ generator: "monitor_driven_rrt", timeout_s: 1800 });
    draft.trajectoryMonitor = "post_hoc";
    const trajectories = buildCampaignConfig(draft, catalog).trajectories as Record<string, unknown>;
    expect(Object.keys(trajectories)).toEqual(["generator", "timeout_s", "monitor"]);
    expect(trajectories.monitor).toBe("post_hoc");
  });

  it("writes the sections of the steps it runs and no others", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation", "trajectory_generation"];
    expect(keysOf(draft)).not.toContain("execution");
    draft.steps = ["scene_generation"];
    expect(keysOf(draft)).not.toContain("trajectories");
    draft.steps = ["trajectory_generation", "simulation"];
    draft.input.items = [item()];
    expect(keysOf(draft)).toEqual(["format", "name", "steps", "input", "trajectories", "execution", "resources", "policy"]);
  });

  it("does not write the scene generation settings of the domain when the campaign starts later", () => {
    const draft = baseDraft();
    draft.steps = ["trajectory_generation", "simulation"];
    draft.input.items = [item()];
    expect(keysOf(draft)).not.toContain("domain");
    draft.domain.custom = true;
    draft.domain.colregsConstants = "A: 1\n";
    draft.domain.vesselTypes = "B: 2\n";
    draft.domain.obstacleTypes = "C: 3\n";
    expect(Object.keys(buildCampaignConfig(draft, catalog).domain as object)).toEqual(["colregs_constants", "vessel_types", "obstacle_types"]);
  });

  it("closes a gap in the steps, as the master needs them consecutive", () => {
    const draft = baseDraft();
    draft.steps = ["simulation", "scene_generation"];
    expect(buildCampaignConfig(draft, catalog).steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
  });

  it("writes the queue caps only for the stages the steps use", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation"];
    draft.sceneMonitor = "post_hoc";
    const cluster: BuilderCatalog = {
      ...catalog,
      slots: { scene_generation: 40, trajectory_generation: 50, simulation: 60, "monitoring.post_hoc": 64, "calibration.deviation": 20 },
    };
    expect(buildCampaignConfig(draft, cluster).resources).toEqual({ queue_depth: { generate_scene: 40, monitor: 64 }, priority: 0 });
  });

  it("lists the stages of the whole chain, calibration with repeats, and the monitor stage for a monitored step", () => {
    const draft = baseDraft();
    draft.runs[0].repeats = 3;
    expect(stagesOf(draft)).toEqual(["generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate"]);
    draft.runs[0].repeats = 1;
    draft.runs[0].monitor = "live";
    expect(stagesOf(draft)).toEqual(["generate_scene", "generate_trajectories", "simulate"]);
    draft.trajectoryMonitor = "post_hoc";
    expect(stagesOf(draft)).toContain("monitor");
    draft.steps = ["scene_generation"];
    expect(stagesOf(draft)).toEqual(["generate_scene"]);
  });
});

describe("buildCampaignConfig input", () => {
  it("writes scenario files after the scope, with their reference as the master stored it", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation"];
    draft.input.scenarios = [
      scenario(),
      scenario({ id: "sc2", name: "second", ref: { sha256: SHA_C, size_bytes: 9, kind: "functional_scenario", media_type: "application/json" }, quota: 1, failureBudget: null }),
      scenario({ id: "sc3", name: "third", ref: { sha256: SHA_C, size_bytes: 9, kind: "functional_scenario" }, quota: 2, failureBudget: "unlimited" }),
    ];
    const config = buildCampaignConfig(draft, catalog);
    expect(Object.keys(config)).toEqual(["format", "name", "steps", "scope", "input", "domain", "resources", "policy"]);
    expect(config.input).toEqual({
      functional_scenarios: [
        { name: "my_head_on", ref: { sha256: SHA_A, size_bytes: 812, kind: "functional_scenario", media_type: "text/plain" }, quota: 3, failure_budget: 1 },
        { name: "second", ref: { sha256: SHA_C, size_bytes: 9, kind: "functional_scenario" }, quota: 1 },
        { name: "third", ref: { sha256: SHA_C, size_bytes: 9, kind: "functional_scenario" }, quota: 2, failure_budget: "unlimited" },
      ],
    });
  });

  it("drops scope entries that name nothing while scenario files give the campaign something to run, and the scope when none is left", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation"];
    draft.scope = [{ id: "empty", classes: [], patterns: [], quota: 1, failureBudget: 0 }];
    draft.input.scenarios = [scenario()];
    expect(keysOf(draft)).not.toContain("scope");
    draft.scope.push({ id: "real", classes: ["a/b"], patterns: [], quota: 2, failureBudget: 0 });
    expect(buildCampaignConfig(draft, catalog).scope).toEqual([{ fecs: ["a/b"], quota: 2, failure_budget: 0 }]);
  });

  it("keeps an empty scope entry when there are no scenario files, so the master and the draft check report it", () => {
    const draft = baseDraft();
    draft.steps = ["scene_generation"];
    draft.scope = [{ id: "empty", classes: [], patterns: [], quota: 1, failureBudget: 0 }];
    expect(buildCampaignConfig(draft, catalog).scope).toEqual([{ quota: 1, failure_budget: 0 }]);
  });

  it("takes scene items from Campaign History or files for trajectory generation, without a scope", () => {
    const draft = baseDraft();
    draft.steps = ["trajectory_generation", "simulation"];
    draft.input.items = [item(), item({ id: "it2", name: "uploaded scene", ref: { sha256: SHA_C, size_bytes: 77, kind: "scene" }, source: { file: "head_on.json" }, uploadedAt: 5 })];
    draft.input.scenarios = [scenario()];
    const config = buildCampaignConfig(draft, catalog);
    expect(config).not.toHaveProperty("scope");
    expect(config.input).toEqual({
      items: [
        { name: "case 5 scene", ref: { sha256: SHA_B, size_bytes: 20480, kind: "scene" }, source: { campaign_id: "c1", case_id: 5, step: "scene_generation" } },
        { name: "uploaded scene", ref: { sha256: SHA_C, size_bytes: 77, kind: "scene" }, source: { file: "head_on.json" } },
      ],
    });
  });

  it("takes trajectory data with its pointer and recorded trajectories for simulation", () => {
    const draft = baseDraft();
    draft.steps = ["simulation"];
    draft.input.items = [
      item({ name: "planned", ref: { sha256: SHA_B, size_bytes: 300, kind: "trajectory_data", media_type: "application/json", pointer: "/trajectories" }, source: { campaign_id: "c1", case_id: 6, step: "trajectory_generation" } }),
      item({ id: "it2", name: "recorded", ref: { sha256: SHA_C, size_bytes: 900, kind: "trajectories", pointer: null }, source: { campaign_id: "c2", case_id: 1, step: "simulation" } }),
    ];
    const config = buildCampaignConfig(draft, catalog);
    expect(Object.keys(config)).toEqual(["format", "name", "steps", "input", "execution", "resources", "policy"]);
    expect((config.input as { items: { ref: unknown }[] }).items.map((entry) => entry.ref)).toEqual([
      { sha256: SHA_B, size_bytes: 300, kind: "trajectory_data", pointer: "/trajectories" },
      { sha256: SHA_C, size_bytes: 900, kind: "trajectories" },
    ]);
    expect(config.steps).toEqual(["simulation"]);
  });

  it("writes no input section for a start with scene generation and catalog classes only", () => {
    expect(keysOf(baseDraft())).not.toContain("input");
  });

  it("leaves the items out when the campaign starts with scene generation, and the scenario files when it starts later", () => {
    const draft = baseDraft();
    draft.input.items = [item()];
    expect(keysOf(draft)).not.toContain("input");
    draft.steps = ["trajectory_generation"];
    draft.input.items = [];
    draft.input.scenarios = [scenario()];
    expect(keysOf(draft)).not.toContain("input");
  });

  it("states the steps before the input and the input before the sections in the YAML text", () => {
    const draft = baseDraft();
    draft.steps = ["trajectory_generation"];
    draft.input.items = [item()];
    const text = buildCampaignYaml(draft, catalog);
    expect(text.indexOf("steps:")).toBeLessThan(text.indexOf("input:"));
    expect(text.indexOf("input:")).toBeLessThan(text.indexOf("trajectories:"));
    const parsed = parse(text) as { input: { items: { source: unknown }[] } };
    expect(parsed.input.items[0].source).toEqual({ campaign_id: "c1", case_id: 5, step: "scene_generation" });
  });
});
