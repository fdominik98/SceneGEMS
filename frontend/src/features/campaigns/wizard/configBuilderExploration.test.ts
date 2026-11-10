import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { campaignPresetSchema } from "../../../domain/cluster/presetsApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { requiredCapabilities } from "../resourcePlan";
import { buildCampaignConfig, type BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { describeSteps, presetFacts, scopeTags } from "./presetCatalog";
import { draftFromConfig, draftHasEntries, presetConfigOf, withDefaultSpecification } from "./presetDraft";
import { parseReason } from "./reasons";
import { inputKindOf, normalizeSteps, stepRange, visibleWizardSteps } from "./stepPlan";
import { emptyDraft, emptyRun, normalizeDraft, type WizardDraft } from "./wizardState";

/** A campaign that starts with the design space exploration: the draft, the config section, its inverse and its checks. */

const parsedCatalog = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsedCatalog.stacks, generators: parsedCatalog.trajectory_generators };

const SPECIFICATION = "abstract class Vessel.\nclass OS extends Vessel.\n";

function exploring(steps: WizardDraft["steps"] = ["design_space_exploration", "scene_generation"]): WizardDraft {
  const draft = emptyDraft();
  draft.name = "explore";
  draft.steps = steps;
  draft.exploration = { specification: SPECIFICATION, specificationLabel: "the control node's default", scope: "TS = 2, StaticObstacle = 0", maxFecs: 50, timeoutS: 300, quota: 2, failureBudget: "unlimited" };
  draft.runs = [{ ...emptyRun("kinematic.replay"), id: "r1" }];
  return draft;
}

/** `backend/assets/campaign_presets/13_design_space_exploration.yaml` as the control node serves it: no specification, the control node's default applies. */
const PRESET_13 = parse(`
format: 3
name: Design space exploration
steps: [design_space_exploration, scene_generation, trajectory_generation, simulation]
design_space_exploration:
  scope: TS = 2, StaticObstacle = 0
  max_fecs: 100
  timeout_s: 600
  quota: 1
  failure_budget: 0
domain:
  scene_generation_timeout_s: 60
  enforce_low_tcpa: false
trajectories:
  generator: monitor_driven_rrt
  timeout_s: 1800
execution:
  runs:
    - stack: {simulation_layer: kinematic, mode: replay}
      repeats: 1
      monitor: post_hoc
resources:
  priority: 0
policy:
  retention: all
  keep_frames: false
  seed: 0
`) as Record<string, unknown>;

describe("the steps of a campaign that explores", () => {
  it("starts the chain with the exploration, which a default draft does not run", () => {
    expect(emptyDraft().steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeSteps([])).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeSteps(["simulation", "design_space_exploration"])).toEqual(["design_space_exploration", "scene_generation", "trajectory_generation", "simulation"]);
    expect(stepRange("design_space_exploration", "design_space_exploration")).toEqual(["design_space_exploration"]);
  });

  it("shows the exploration page before scene generation and takes no input", () => {
    expect(visibleWizardSteps(["design_space_exploration", "scene_generation"])).toEqual(["steps", "input", "domain", "exploration", "scenes", "resources", "policy", "review"]);
    expect(visibleWizardSteps(["scene_generation"])).not.toContain("exploration");
    expect(inputKindOf(["design_space_exploration"])).toBe("explored");
  });

  it("keeps a stored draft without the exploration as it was", () => {
    const stored = JSON.parse(JSON.stringify(emptyDraft())) as Record<string, unknown>;
    delete stored.exploration;
    const draft = normalizeDraft(stored);
    expect(draft.steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(draft.exploration).toEqual(emptyDraft().exploration);
  });

  it("sends the control node's reasons about the section to the exploration page", () => {
    expect(parseReason("design_space_exploration.scope: entry 1 is not Type = n").step).toBe("exploration");
  });
});

describe("the config of a campaign that explores", () => {
  it("writes the section and leaves out the scope entries and the input", () => {
    const draft = exploring();
    draft.input.scenarios = [{ id: "f", fileName: "a.problem", name: "a", ref: { sha256: "a".repeat(64), kind: "functional_scenario" }, quota: 1, failureBudget: 0, uploadedAt: 0 }];
    const config = buildCampaignConfig(draft, catalog);
    expect(config.steps).toEqual(["design_space_exploration", "scene_generation"]);
    expect(config.design_space_exploration).toEqual({ specification: SPECIFICATION, scope: "TS = 2, StaticObstacle = 0", max_fecs: 50, timeout_s: 300, quota: 2, failure_budget: "unlimited" });
    expect(config.scope).toBeUndefined();
    expect(config.input).toBeUndefined();
  });

  it("writes null for every FEC and leaves out an empty specification for the control node's default", () => {
    const draft = exploring(["design_space_exploration"]);
    draft.exploration.maxFecs = null;
    draft.exploration.specification = "";
    expect(buildCampaignConfig(draft, catalog).design_space_exploration).toEqual({ scope: "TS = 2, StaticObstacle = 0", max_fecs: null, timeout_s: 300, quota: 2, failure_budget: "unlimited" });
  });

  it("has no section when the campaign does not explore", () => {
    expect(buildCampaignConfig(emptyDraft(), catalog).design_space_exploration).toBeUndefined();
  });

  it("reads the section back as the draft that builds the same config", () => {
    const config = buildCampaignConfig(exploring(), catalog);
    const draft = draftFromConfig(config, catalog);
    expect(draft.exploration).toMatchObject({ specification: SPECIFICATION, scope: "TS = 2, StaticObstacle = 0", maxFecs: 50, timeoutS: 300, quota: 2, failureBudget: "unlimited" });
    expect(JSON.parse(JSON.stringify(buildCampaignConfig(draft, catalog)))).toEqual(JSON.parse(JSON.stringify(config)));
    expect(presetConfigOf(exploring(), catalog).design_space_exploration).toEqual(config.design_space_exploration);
  });

  it("reads a preset that leaves the specification to the control node, and builds it again without one", () => {
    const draft = draftFromConfig(PRESET_13, catalog);
    expect(draft.steps).toEqual(["design_space_exploration", "scene_generation", "trajectory_generation", "simulation"]);
    expect(draft.exploration).toMatchObject({ specification: "", scope: "TS = 2, StaticObstacle = 0", maxFecs: 100, quota: 1, failureBudget: 0 });
    expect(JSON.parse(JSON.stringify(buildCampaignConfig(draft, catalog)))).toEqual(PRESET_13);
  });

  it("starts such a preset from the control node's default, which the wizard then shows and sends", () => {
    const draft = draftFromConfig(PRESET_13, catalog);
    const filled = withDefaultSpecification(draft, { specification: "class OS.\r\n" }, "the control node's default");
    expect(filled.exploration).toMatchObject({ specification: "class OS.\n", specificationLabel: "the control node's default" });
    expect(withDefaultSpecification(draft, null, "x")).toBe(draft);
    expect(withDefaultSpecification(exploring(), { specification: "other" }, "x").exploration.specification).toBe(SPECIFICATION);
    expect(withDefaultSpecification(emptyDraft(), { specification: "other" }, "x").exploration.specification).toBe("");
  });

  it("counts an explored specification as an entry a preset would replace", () => {
    expect(draftHasEntries({ ...exploring(), name: "" })).toBe(true);
    expect(draftHasEntries({ ...emptyDraft(), exploration: exploring().exploration })).toBe(false);
  });
});

describe("the checks of a campaign that explores", () => {
  const problems = (draft: WizardDraft) =>
    checkDraft(draft, catalog, 0)
      .filter((reason) => reason.step === "exploration" || reason.step === "input")
      .map((reason) => [reason.step, reason.field, reason.message]);

  it("asks for a specification and a valid scope, and no input", () => {
    expect(problems(exploring())).toEqual([]);
    const draft = exploring();
    draft.exploration.specification = " ";
    draft.exploration.scope = "TS = 2,";
    draft.exploration.timeoutS = null;
    draft.exploration.quota = 0;
    expect(problems(draft)).toEqual([
      ["exploration", "specification", "Write or load the metamodel and the well-formedness constraints."],
      ["exploration", "scope", "The entry 2 is empty. Write Type = n or Type = a..b, separated by commas."],
      ["exploration", "timeout_s", "The timeout is above 0 seconds."],
      ["exploration", "quota", "Each explored FEC needs at least 1 case."],
    ]);
  });

  it("does not ask for cases per FEC when the exploration runs alone", () => {
    const draft = exploring(["design_space_exploration"]);
    draft.exploration.quota = null;
    expect(problems(draft)).toEqual([]);
  });
});

describe("what a campaign that explores needs", () => {
  it("needs the exploration's job type and component", () => {
    const [first] = requiredCapabilities(buildCampaignConfig(exploring(), catalog));
    expect(first).toMatchObject({ jobType: "design_space_exploration", components: ["design_space_exploration"], stage: "explore_design_space" });
    expect(requiredCapabilities({ steps: ["scene_generation"] }).some((need) => need.jobType === "design_space_exploration")).toBe(false);
  });
});

describe("a preset that explores", () => {
  const preset = campaignPresetSchema.parse({
    preset_id: "13_design_space_exploration",
    name: "Design space exploration",
    description: "Every FEC of two target ships.",
    builtin: true,
    steps: PRESET_13.steps,
    config: PRESET_13,
    created_at: null,
    updated_at: null,
  });

  it("says that it explores the design space and sorts its steps with the whole chain", () => {
    const facts = presetFacts(preset, catalog, []);
    expect(facts.explores).toBe(true);
    expect(facts.fromInput).toBe(false);
    expect(scopeTags(facts)).toEqual(["Explores the design space, scope TS = 2, StaticObstacle = 0"]);
    expect(describeSteps(preset.steps)).toBe("Design space exploration and the whole chain");
    expect(describeSteps(["scene_generation", "trajectory_generation", "simulation"])).toBe("Whole chain");
    expect(describeSteps(["design_space_exploration"])).toBe("Design space exploration");
  });
});
