import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import type { BuilderCatalog } from "./configBuilder";
import { checkDraft, uploadExpired } from "./draftChecks";
import { emptyDraft, emptyRun, UPLOAD_LIFETIME_MS, type InputItemDraft, type ScenarioFileDraft, type WizardDraft } from "./wizardState";

const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsed.stacks, generators: parsed.trajectory_generators };

function validDraft(): WizardDraft {
  const draft = emptyDraft();
  draft.name = "sweep";
  draft.scope = [{ id: "s", classes: [], patterns: ["2vessel_*"], quota: 3, failureBudget: 1 }];
  draft.runs = [emptyRun("kinematic.replay")];
  return draft;
}

function messages(draft: WizardDraft, withCatalog: BuilderCatalog | null = catalog) {
  return checkDraft(draft, withCatalog).map((reason) => `${reason.step}/${reason.entry ?? "-"}/${reason.field ?? "-"}`);
}

describe("checkDraft", () => {
  it("accepts a complete draft", () => {
    expect(checkDraft(validDraft(), catalog)).toEqual([]);
  });

  it("asks for a name and a scope", () => {
    const draft = emptyDraft();
    draft.runs = [emptyRun("kinematic.replay")];
    expect(messages(draft)).toEqual(["steps/-/name", "input/0/-"]);
  });

  it("checks the quota and the failure budget of each entry", () => {
    const draft = validDraft();
    draft.scope[0].quota = 0;
    draft.scope.push({ id: "t", classes: ["a/b"], patterns: [], quota: null, failureBudget: -1 });
    expect(messages(draft)).toEqual(["input/0/quota", "input/1/quota", "input/1/failure_budget"]);
  });

  it("accepts an unlimited failure budget", () => {
    const draft = validDraft();
    draft.scope[0].failureBudget = "unlimited";
    expect(messages(draft)).toEqual([]);
  });

  it("parses customized domain text and flags what is not a YAML mapping", () => {
    const draft = validDraft();
    draft.domain.custom = true;
    draft.domain.colregsConstants = "A: 1\nB: 2\n";
    draft.domain.vesselTypes = "A: [1\n";
    draft.domain.obstacleTypes = "- just\n- a list\n";
    expect(messages(draft)).toEqual(["domain/-/vessel_types", "domain/-/obstacle_types"]);
    draft.domain.colregsConstants = "A: 1\nA: 2\n";
    expect(messages(draft)).toContain("domain/-/colregs_constants");
  });

  it("does not look at domain texts while the defaults are used", () => {
    const draft = validDraft();
    draft.domain.colregsConstants = "not: [valid";
    expect(checkDraft(draft, catalog)).toEqual([]);
  });

  it("requires the generator's required parameters", () => {
    const draft = validDraft();
    draft.trajectories.generator = "straight";
    expect(messages(draft)).toEqual(["trajectories/-/timespan_s"]);
    draft.trajectories.parameters = { timespan_s: 60 };
    expect(checkDraft(draft, catalog)).toEqual([]);
    draft.trajectories.generator = "unheard_of";
    expect(messages(draft)).toEqual(["trajectories/-/generator"]);
  });

  it("flags a run without a stack, with an unknown stack, or with an unavailable one", () => {
    const draft = validDraft();
    draft.runs = [emptyRun(""), emptyRun("kinematic.nope")];
    expect(messages(draft)).toEqual(["runs/0/stack", "runs/1/stack"]);
    const unavailable: BuilderCatalog = { ...catalog, stacks: catalog.stacks.map((stack) => ({ ...stack, available: false, reasons: ["resolver says no"] })) };
    draft.runs = [emptyRun("kinematic.replay")];
    const reasons = checkDraft(draft, unavailable);
    expect(reasons).toHaveLength(1);
    expect(reasons[0].message).toContain("resolver says no");
  });

  it("flags early stop without the live monitor and repeats below 1", () => {
    const draft = validDraft();
    Object.assign(draft.runs[0], { earlyStop: true, repeats: 0 });
    expect(messages(draft)).toEqual(["runs/0/early_stop", "runs/0/repeats"]);
    Object.assign(draft.runs[0], { monitor: "live", repeats: 1 });
    expect(checkDraft(draft, catalog)).toEqual([]);
  });

  it("flags early stop on a stack that runs to the end", () => {
    const draft = validDraft();
    draft.runs = [{ ...emptyRun("ardupilot_sim.replay"), monitor: "live", earlyStop: true }];
    expect(messages(draft)).toEqual(["runs/0/early_stop"]);
    expect(checkDraft(draft, catalog)[0].message).toBe("Replay on ArduPilot SITL runs to the end: a run on it does not stop early.");
    draft.runs[0].earlyStop = false;
    expect(checkDraft(draft, catalog)).toEqual([]);
  });

  it("requires the USV Navigation values once the group is set", () => {
    const draft = validDraft();
    draft.runs = [{ ...emptyRun("kinematic.usv_navigation"), groups: { usv_navigation: { speed: 4 } } }];
    expect(messages(draft)).toEqual([
      "runs/0/stack.usv_navigation.goal",
      "runs/0/stack.usv_navigation.safety_radius",
      "runs/0/stack.usv_navigation.control_horizon",
    ]);
  });

  it("does not judge stacks before the catalog is loaded", () => {
    const draft = validDraft();
    draft.runs = [emptyRun("")];
    expect(checkDraft(draft, null)).toEqual([]);
  });

  it("flags a label value without a name", () => {
    const draft = validDraft();
    draft.resources.labels = [{ key: "", value: "lab" }];
    expect(messages(draft)).toEqual(["resources/-/required_labels"]);
  });

  it("asks for a machine when the machines are chosen by hand", () => {
    const draft = validDraft();
    draft.resources.fullUsage = false;
    expect(messages(draft)).toEqual(["resources/-/worker_nodes"]);
    draft.resources.workerNodes = ["worker-node-a"];
    expect(messages(draft)).toEqual([]);
  });
});

const NOW = 1_800_000_000_000;

function scenario(overrides: Partial<ScenarioFileDraft> = {}): ScenarioFileDraft {
  return {
    id: "sc",
    fileName: "a.problem",
    name: "a",
    ref: { sha256: "a".repeat(64), size_bytes: 10, kind: "functional_scenario" },
    quota: 1,
    failureBudget: 0,
    uploadedAt: NOW - 1000,
    ...overrides,
  };
}

function item(overrides: Partial<InputItemDraft> = {}): InputItemDraft {
  return {
    id: "it",
    name: "scene",
    ref: { sha256: "b".repeat(64), size_bytes: 10, kind: "scene" },
    source: { campaign_id: "c1", case_id: 1, step: "scene_generation" },
    uploadedAt: null,
    ...overrides,
  };
}

function checks(draft: WizardDraft) {
  return checkDraft(draft, catalog, NOW).map((reason) => `${reason.step}/${reason.list ?? ""}/${reason.entry ?? "-"}/${reason.field ?? "-"}`);
}

describe("checkDraft for partial campaigns", () => {
  it("does not look at the sections of steps it does not run", () => {
    const draft = validDraft();
    draft.steps = ["scene_generation"];
    draft.runs = [emptyRun("")];
    draft.trajectories.generator = "unheard_of";
    draft.trajectories.timeoutS = null;
    expect(checks(draft)).toEqual([]);
    draft.steps = ["scene_generation"];
    draft.domain.sceneGenerationTimeoutS = null;
    // The scene generation timeout is set on the Scene generation page
    expect(checks(draft)).toEqual(["scenes//-/scene_generation_timeout_s"]);
    draft.steps = ["trajectory_generation"];
    draft.input.items = [item()];
    expect(checks(draft)).toEqual(["trajectories//-/generator", "trajectories//-/timeout_s"]);
    draft.steps = ["simulation"];
    draft.input.items = [item({ ref: { sha256: "c".repeat(64), size_bytes: 1, kind: "trajectories" } })];
    expect(checks(draft)).toEqual(["runs//0/stack"]);
  });

  it("asks scene generation for classes or scenario files", () => {
    const draft = validDraft();
    draft.steps = ["scene_generation"];
    draft.scope = [{ id: "e", classes: [], patterns: [], quota: 1, failureBudget: 0 }];
    expect(checks(draft)).toEqual(["input//0/-"]);
    draft.input.scenarios = [scenario()];
    expect(checks(draft)).toEqual([]);
  });

  it("checks each scenario file's name, quota and failure budget", () => {
    const draft = validDraft();
    draft.steps = ["scene_generation"];
    draft.input.scenarios = [scenario({ name: " ", quota: 0 }), scenario({ id: "b", name: "a/b", failureBudget: -1 }), scenario({ id: "c", name: "a" }), scenario({ id: "d", name: "a" })];
    expect(checks(draft)).toEqual([
      "input/scenario/0/name",
      "input/scenario/0/quota",
      "input/scenario/1/name",
      "input/scenario/1/failure_budget",
      "input/scenario/3/name",
    ]);
  });

  it("asks a later start for items of the right kind", () => {
    const draft = validDraft();
    draft.steps = ["trajectory_generation", "simulation"];
    expect(checks(draft)).toEqual(["input//-/items"]);
    draft.input.items = [item({ name: "" }), item({ id: "t", ref: { sha256: "c".repeat(64), size_bytes: 1, kind: "trajectories" } })];
    expect(checks(draft)).toEqual(["input/item/0/name", "input/item/1/ref"]);
    draft.steps = ["simulation"];
    draft.input.items = [item({ ref: { sha256: "c".repeat(64), size_bytes: 1, kind: "trajectory_data", pointer: "/trajectories" } })];
    expect(checks(draft)).toEqual([]);
  });

  it("reports an upload the control node has deleted by now, for a scenario file and an item", () => {
    const draft = validDraft();
    draft.steps = ["scene_generation"];
    draft.input.scenarios = [scenario({ uploadedAt: NOW - UPLOAD_LIFETIME_MS })];
    expect(checks(draft)).toEqual(["input/scenario/0/ref"]);
    draft.steps = ["trajectory_generation"];
    draft.input.items = [item({ uploadedAt: NOW - UPLOAD_LIFETIME_MS - 1 }), item({ id: "kept", uploadedAt: null })];
    expect(checks(draft)).toEqual(["input/item/0/ref"]);
  });

  it("dates an upload against the clock: expired from 24 hours on, never for a history output", () => {
    expect(uploadExpired(NOW - UPLOAD_LIFETIME_MS + 1, NOW)).toBe(false);
    expect(uploadExpired(NOW - UPLOAD_LIFETIME_MS, NOW)).toBe(true);
    expect(uploadExpired(null, NOW)).toBe(false);
  });

  it("puts the missing name on the steps page", () => {
    const draft = validDraft();
    draft.name = " ";
    expect(checkDraft(draft, catalog, NOW)[0]).toMatchObject({ step: "steps", field: "name", source: "local" });
  });
});
