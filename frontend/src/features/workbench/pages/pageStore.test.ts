import { describe, expect, it } from "vitest";
import { MemoryStorage } from "../../../test/memoryStorage";
import { createPageStore, inputFromPreviousPage, legacyPageState, migratePageState, PAGE_STORE_VERSION, pageStorageKey, type PageOutput } from "./pageStore";
import type { WorkbenchTarget } from "./workbenchTarget";

const target: WorkbenchTarget = { page: "trajectoryGeneration", campaignId: "wb1", caseId: 3, step: "trajectory_generation", live: true };
const output: PageOutput = {
  label: "Trajectories of case 3 of entry wb1",
  ref: { sha256: "b".repeat(64), size_bytes: 10, kind: "trajectories", media_type: "application/json", pointer: "/trajectories" },
  source: { campaign_id: "wb1", case_id: 3, step: "trajectory_generation" },
};

function storeWith(storage: MemoryStorage, page: Parameters<typeof createPageStore>[0] = "trajectoryGeneration") {
  return createPageStore(page, () => storage);
}

describe("page store", () => {
  it("starts empty and keeps input, loaded target and output, not the run state", () => {
    const storage = new MemoryStorage();
    const store = storeWith(storage);
    expect(store.getState()).toMatchObject({ input: null, loaded: null, output: null, status: "idle" });
    store.getState().setInput({ label: "head_on.json", origin: "file", ref: null, source: { file: "head_on.json" } });
    store.getState().setLoaded(target, output);
    store.getState().setStatus("running", "Planning", "wb2");
    const saved = JSON.parse(storage.getItem(pageStorageKey("trajectoryGeneration")) ?? "{}");
    expect(saved.version).toBe(PAGE_STORE_VERSION);
    expect(Object.keys(saved.state).sort()).toEqual(["input", "loaded", "output"]);
    // A live target is loaded as the finished output after a reload.
    expect(saved.state.loaded).toEqual({ page: "trajectoryGeneration", campaignId: "wb1", caseId: 3, step: "trajectory_generation" });
    expect(saved.state.input.label).toBe("head_on.json");
  });

  it("restores what was stored", () => {
    const storage = new MemoryStorage();
    storeWith(storage).getState().setLoaded(target, output);
    const reloaded = storeWith(storage);
    expect(reloaded.getState().loaded).toMatchObject({ campaignId: "wb1", caseId: 3 });
    expect(reloaded.getState().output?.ref?.sha256).toBe("b".repeat(64));
  });

  it("clears the loaded entry and its output but keeps the input", () => {
    const store = storeWith(new MemoryStorage());
    store.getState().setInput({ label: "scene", origin: "previous_page", ref: null, source: { file: "scene_generation.json" } });
    store.getState().setLoaded(target, output);
    store.getState().clearLoaded("The entry was deleted.");
    expect(store.getState()).toMatchObject({ loaded: null, output: null, status: "failed", message: "The entry was deleted." });
    expect(store.getState().input?.label).toBe("scene");
  });

  it("keeps a note with the shown output only", () => {
    const store = storeWith(new MemoryStorage(), "simulation");
    const run: WorkbenchTarget = { page: "simulation", campaignId: "wb1", caseId: 3, step: "simulation", runRecordId: 11 };
    store.getState().setLoaded(run, null);
    store.getState().setNote({ tone: "busy", text: "The monitor is judging the run..." });
    expect(store.getState().note?.text).toMatch(/judging/);
    // Another run loaded, a run started or a failure: the note of the former output goes.
    store.getState().setLoaded({ ...run, runRecordId: 12 }, null);
    expect(store.getState().note).toBeNull();
    store.getState().setNote({ tone: "warning", text: "The run is shown without the monitor's judgment." });
    store.getState().setStatus("running", "Simulating");
    expect(store.getState().note).toBeNull();
  });

  it("drops the loaded target when the page shows a file", () => {
    const store = storeWith(new MemoryStorage(), "sceneGeneration");
    store.getState().setLoaded({ ...target, page: "sceneGeneration", step: "scene_generation" }, output);
    store.getState().setLocalOutput({ label: "head_on.json", ref: null, source: { file: "head_on.json" } });
    expect(store.getState().loaded).toBeNull();
    expect(store.getState().output?.label).toBe("head_on.json");
  });
});

describe("page store migration", () => {
  it("takes the trajectory page's scene of before Phase 6 as its input", () => {
    const storage = new MemoryStorage();
    storage.setItem("scenegems:trajectory-generation", JSON.stringify({ version: 2, state: { handoffScene: { scene: {}, valid: true }, handoffSourceName: "head_on.json" } }));
    expect(legacyPageState("trajectoryGeneration", storage).input).toEqual({ label: "head_on.json", origin: "file", ref: null, source: { file: "head_on.json" } });
    storage.setItem("scenegems:trajectory-generation", JSON.stringify({ version: 2, state: { handoffScene: { scene: {}, valid: true }, handoffSourceName: null } }));
    expect(legacyPageState("trajectoryGeneration", storage).input?.origin).toBe("previous_page");
    expect(storeWith(storage).getState().input?.origin).toBe("previous_page");
  });

  it("starts empty without an old scene, and for the other pages", () => {
    const storage = new MemoryStorage();
    expect(legacyPageState("trajectoryGeneration", storage).input).toBeNull();
    storage.setItem("scenegems:trajectory-generation", "not json");
    expect(legacyPageState("trajectoryGeneration", storage).input).toBeNull();
    storage.setItem("scenegems:trajectory-generation", JSON.stringify({ state: { handoffScene: { scene: {}, valid: true } } }));
    expect(legacyPageState("simulation", storage).input).toBeNull();
    expect(legacyPageState("trajectoryGeneration", null).input).toBeNull();
  });

  it("keeps well-formed fields of an older blob and resets malformed ones", () => {
    expect(migratePageState({ loaded: { ...target }, input: { label: "x" }, output: output, stray: 1 }, 0)).toEqual({
      loaded: { page: "trajectoryGeneration", campaignId: "wb1", caseId: 3, step: "trajectory_generation", live: undefined },
      input: null,
      output,
    });
    expect(migratePageState(null, 0)).toEqual({ input: null, loaded: null, output: null });
    expect(migratePageState({ loaded: { campaignId: 5 } }, 0).loaded).toBeNull();
  });
});

describe("input from the previous page", () => {
  it("takes the output's reference and source", () => {
    expect(inputFromPreviousPage(output)).toEqual({ label: output.label, origin: "previous_page", ref: output.ref, source: output.source });
    expect(inputFromPreviousPage(null)).toBeNull();
  });
});
