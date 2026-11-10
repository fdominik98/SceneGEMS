import { describe, expect, it } from "vitest";
import { MemoryStorage } from "../../../test/memoryStorage";
import { createWizardStore, emptyDraft, migrateStoredWizard, normalizeDraft, WIZARD_STORAGE_KEY } from "./wizardState";

function storeWith(storage = new MemoryStorage()) {
  return { store: createWizardStore(storage), storage };
}

describe("wizard store", () => {
  it("starts with an empty draft at the steps page, running the whole chain", () => {
    const { store } = storeWith();
    expect(store.getState().step).toBe("steps");
    expect(store.getState().draft).toMatchObject({
      name: "",
      steps: ["scene_generation", "trajectory_generation", "simulation"],
      sceneMonitor: "empty",
      trajectoryMonitor: "empty",
      input: { scenarios: [], items: [] },
      scope: [{ quota: 1, failureBudget: 0 }],
      runs: [{ monitor: "post_hoc" }],
    });
  });

  it("changes a copy of the draft and notifies", () => {
    const { store } = storeWith();
    const before = store.getState().draft;
    store.getState().update((draft) => {
      draft.name = "sweep";
      draft.runs[0].stackId = "kinematic.replay";
    });
    expect(store.getState().draft.name).toBe("sweep");
    expect(store.getState().draft.runs[0].stackId).toBe("kinematic.replay");
    expect(before.name).toBe("");
  });

  it("remembers the steps left behind", () => {
    const { store } = storeWith();
    store.getState().setStep("domain");
    store.getState().setStep("runs");
    store.getState().setStep("domain");
    expect(store.getState().visited).toEqual(["steps", "domain", "runs"]);
  });

  it("keeps the draft per browser: a new store on the same storage finds it", () => {
    const first = storeWith();
    first.store.getState().update((draft) => {
      draft.name = "half done";
      draft.domain.custom = true;
      draft.domain.vesselTypes = "A:\n  length: 3\n";
    });
    first.store.getState().setStep("runs");
    const second = storeWith(first.storage);
    expect(second.store.getState().step).toBe("runs");
    expect(second.store.getState().draft.name).toBe("half done");
    expect(second.store.getState().draft.domain.vesselTypes).toBe("A:\n  length: 3\n");
    expect(second.store.getState().visited).toEqual(["steps"]);
  });

  it("starts over on reset and stores the empty draft", () => {
    const { store, storage } = storeWith();
    store.getState().update((draft) => {
      draft.name = "x";
    });
    store.getState().setStep("policy");
    store.getState().reset();
    expect(store.getState().step).toBe("steps");
    expect(store.getState().draft.name).toBe("");
    expect(JSON.parse(storage.getItem(WIZARD_STORAGE_KEY) as string).state.draft.name).toBe("");
  });

  it("ignores a stored step it does not know", () => {
    const storage = new MemoryStorage();
    storage.setItem(WIZARD_STORAGE_KEY, JSON.stringify({ state: { step: "teleport", draft: { name: "kept" }, visited: ["scope", "bogus"] }, version: 1 }));
    const { store } = storeWith(storage);
    expect(store.getState().step).toBe("steps");
    expect(store.getState().draft.name).toBe("kept");
    expect(store.getState().visited).toEqual(["input"]);
  });

  it("opens a draft stored before Phase 6 as the full chain on the page that replaced the scope page", () => {
    const storage = new MemoryStorage();
    storage.setItem(
      WIZARD_STORAGE_KEY,
      JSON.stringify({
        state: {
          step: "scope",
          draft: { name: "old sweep", scope: [{ id: "s", classes: [], patterns: ["2vessel_*"], quota: 3, failureBudget: 1 }], runs: [{ stackId: "kinematic.replay" }] },
          visited: ["scope", "domain"],
        },
        version: 1,
      })
    );
    const { store } = storeWith(storage);
    const state = store.getState();
    expect(state.step).toBe("input");
    expect(state.visited).toEqual(["input", "domain"]);
    expect(state.draft).toMatchObject({
      name: "old sweep",
      steps: ["scene_generation", "trajectory_generation", "simulation"],
      sceneMonitor: "empty",
      trajectoryMonitor: "empty",
      input: { scenarios: [], items: [] },
      scope: [{ patterns: ["2vessel_*"], quota: 3 }],
    });
  });

  it("keeps a version 2 draft as it was stored", () => {
    const first = storeWith();
    first.store.getState().update((draft) => {
      draft.steps = ["trajectory_generation", "simulation"];
      draft.trajectoryMonitor = "post_hoc";
      draft.input.items.push({
        id: "i1",
        name: "case 5 scene",
        ref: { sha256: "ab", size_bytes: 12, kind: "scene" },
        source: { campaign_id: "c1", case_id: 5, step: "scene_generation" },
        uploadedAt: null,
      });
    });
    first.store.getState().setStep("input");
    const second = storeWith(first.storage);
    expect(second.store.getState().step).toBe("input");
    expect(second.store.getState().draft.steps).toEqual(["trajectory_generation", "simulation"]);
    expect(second.store.getState().draft.trajectoryMonitor).toBe("post_hoc");
    expect(second.store.getState().draft.input.items[0]).toMatchObject({ name: "case 5 scene", source: { campaign_id: "c1" } });
  });
});

describe("normalizeDraft", () => {
  it("fills the sections a stored draft lacks", () => {
    const draft = normalizeDraft({ name: "old", resources: { priority: 3, queueDepth: { simulate: 8 } }, runs: [{ stackId: "kinematic.replay" }] });
    expect(draft.name).toBe("old");
    expect(draft.resources.priority).toBe(3);
    expect(draft.resources.queueDepth).toMatchObject({ simulate: 8, generate_scene: 16 });
    expect(draft.resources).toMatchObject({ fullUsage: true, workerNodes: [] });
    expect(draft.runs[0]).toMatchObject({ stackId: "kinematic.replay", monitor: "post_hoc", repeats: 1 });
    expect(draft.trajectories.generator).toBe("monitor_driven_rrt");
  });

  it("gives an empty draft for anything that is not an object", () => {
    expect(normalizeDraft(null).name).toBe(emptyDraft().name);
    expect(normalizeDraft("x").scope).toHaveLength(1);
  });
});

describe("normalizeDraft for the steps", () => {
  it("reads a draft without steps as the full chain and closes a gap in stored steps", () => {
    expect(normalizeDraft({ name: "x" }).steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeDraft({ steps: ["simulation", "scene_generation"] }).steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeDraft({ steps: ["trajectory_generation"] }).steps).toEqual(["trajectory_generation"]);
    expect(normalizeDraft({ steps: ["bogus"] }).steps).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
  });

  it("reads anything but post_hoc as no monitor and fills the input lists", () => {
    const draft = normalizeDraft({ sceneMonitor: "live", trajectoryMonitor: "post_hoc", input: { items: "nope" } });
    expect(draft.sceneMonitor).toBe("empty");
    expect(draft.trajectoryMonitor).toBe("post_hoc");
    expect(draft.input).toEqual({ scenarios: [], items: [] });
  });
});

describe("migrateStoredWizard", () => {
  it("renames the scope page, drops unknown pages and repeats", () => {
    const migrated = migrateStoredWizard({ step: "scope", visited: ["scope", "bogus", "scope", "runs"], draft: { name: "n" } });
    expect(migrated.step).toBe("input");
    expect(migrated.visited).toEqual(["input", "runs"]);
    expect(migrated.draft.name).toBe("n");
  });

  it("gives an empty draft and no step for stored state that is not an object", () => {
    expect(migrateStoredWizard(undefined)).toMatchObject({ step: null, visited: [] });
    expect(migrateStoredWizard("x").draft.steps).toHaveLength(3);
  });
});
