import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../../test/memoryStorage";

// uiStore's persist takes window.localStorage when the store is created, so the modules load after the stubs.
const storage = new MemoryStorage();
let target: typeof import("./workbenchTarget");
let ui: typeof import("../../../app/uiStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  ui = await import("../../../app/uiStore");
  target = await import("./workbenchTarget");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  storage.clear();
  target.useWorkbenchTargetStore.setState({ pending: {} });
  ui.useUiStore.setState({ section: "campaigns", workbenchView: "connections" });
});

describe("openInWorkbench", () => {
  it("shows the workbench section on the page's view", () => {
    target.openInWorkbench({ page: "trajectoryGeneration", campaignId: "c1", caseId: 5, step: "trajectory_generation" });
    expect(ui.useUiStore.getState().section).toBe("workbench");
    expect(ui.useUiStore.getState().workbenchView).toBe("trajectoryGeneration");
  });

  it("maps each page to the workbench view of the same name", () => {
    for (const page of ["sceneGeneration", "trajectoryGeneration", "simulation"] as const) {
      expect(target.WORKBENCH_VIEW_OF_PAGE[page]).toBe(page);
      expect((ui.WORKBENCH_VIEWS as readonly string[]).includes(target.WORKBENCH_VIEW_OF_PAGE[page])).toBe(true);
    }
  });

  it("maps each step to the page of its subsystem", () => {
    expect(target.WORKBENCH_PAGE_OF_STEP).toEqual({
      scene_generation: "sceneGeneration",
      trajectory_generation: "trajectoryGeneration",
      simulation: "simulation",
    });
  });

  it("queues the target for the page until it is taken, once", () => {
    const queued = { page: "simulation", campaignId: "c1", caseId: 7, step: "simulation", runRecordId: 11 } as const;
    target.openInWorkbench(queued);
    expect(target.useWorkbenchTargetStore.getState().pending.simulation).toEqual(queued);
    expect(target.takeTarget("simulation")).toEqual(queued);
    expect(target.takeTarget("simulation")).toBeUndefined();
    expect(target.useWorkbenchTargetStore.getState().pending).toEqual({});
  });

  it("keeps a target per page, so one page's target does not wait behind another's", () => {
    const scene = { page: "sceneGeneration", campaignId: "c1", caseId: 1, step: "scene_generation" } as const;
    const run = { page: "simulation", campaignId: "wb2", caseId: 1, step: "simulation", live: true } as const;
    target.openInWorkbench(scene);
    target.openInWorkbench(run);
    expect(ui.useUiStore.getState().workbenchView).toBe("simulation");
    expect(target.takeTarget("trajectoryGeneration")).toBeUndefined();
    expect(target.takeTarget("sceneGeneration")).toEqual(scene);
    expect(target.takeTarget("simulation")).toEqual(run);
  });

  it("replaces a target the page has not taken with the newer one", () => {
    target.openInWorkbench({ page: "sceneGeneration", campaignId: "c1", caseId: 1, step: "scene_generation" });
    const newer = { page: "sceneGeneration", campaignId: "c2", caseId: 9, step: "scene_generation" } as const;
    target.openInWorkbench(newer);
    expect(target.takeTarget("sceneGeneration")).toEqual(newer);
  });

  it("selects the pending target of a page for a component to follow", () => {
    const queued = { page: "trajectoryGeneration", campaignId: "c1", caseId: 3, step: "trajectory_generation" } as const;
    target.openInWorkbench(queued);
    const state = target.useWorkbenchTargetStore.getState();
    expect(target.selectPendingTarget(state, "trajectoryGeneration")).toEqual(queued);
    expect(target.selectPendingTarget(state, "simulation")).toBeUndefined();
  });

  it("is not persisted with the ui state", () => {
    target.openInWorkbench({ page: "sceneGeneration", campaignId: "c1", caseId: 1, step: "scene_generation" });
    const partialize = ui.useUiStore.persist.getOptions().partialize;
    expect(JSON.stringify(partialize?.(ui.useUiStore.getState()))).not.toContain("c1");
  });
});
