import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../test/memoryStorage";

// zustand's persist takes window.localStorage when the store is created, so the module loads after the stubs.
const storage = new MemoryStorage();
let ui: typeof import("./uiStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  ui = await import("./uiStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function migrate(persisted: unknown, version: number) {
  const run = ui.useUiStore.persist.getOptions().migrate;
  if (!run) {
    throw new Error("uiStore has no migrate");
  }
  return run(persisted, version) as Record<string, unknown>;
}

describe("uiStore sections", () => {
  beforeEach(() => {
    storage.clear();
  });

  it("moves the workbench view out of its old key when migrating to v4", () => {
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("sceneGeneration"));
    const state = migrate({ sceneViewMode: "nautical" }, 3);
    expect(state.section).toBe("workbench");
    expect(state.workbenchView).toBe("sceneGeneration");
    expect(state.sceneViewMode).toBe("nautical");
  });

  it("falls back to the simulation view without a valid old key", () => {
    expect(migrate({}, 3).workbenchView).toBe("simulation");
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("monitor"));
    expect(migrate({}, 3).workbenchView).toBe("simulation");
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, "{not json");
    expect(ui.readLegacyWorkbenchView()).toBeNull();
  });

  it("moves a v1 state to the workbench section", () => {
    expect(migrate({}, 1).section).toBe("workbench");
  });

  it("keeps a v4 state as it is", () => {
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("waraps"));
    const state = migrate({ section: "cluster", workbenchView: "trajectoryGeneration" }, 4);
    expect(state).toEqual({ section: "cluster", workbenchView: "trajectoryGeneration" });
  });

  it("renames the WARA-PS view to connections in v5", () => {
    expect(migrate({ section: "workbench", workbenchView: "waraps" }, 4).workbenchView).toBe("connections");
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("waraps"));
    expect(migrate({}, 3).workbenchView).toBe("connections");
  });

  it("renames the Observe section to history in v6", () => {
    expect(migrate({ section: "observe", workbenchView: "simulation" }, 5)).toEqual({ section: "history", workbenchView: "simulation" });
    expect(migrate({ section: "observe" }, 4).section).toBe("history");
  });

  it("leaves other sections alone when migrating to v6", () => {
    expect(migrate({ section: "results", workbenchView: "trajectoryGeneration" }, 5)).toEqual({ section: "results", workbenchView: "trajectoryGeneration" });
    expect(migrate({ section: "history" }, 5).section).toBe("history");
  });

  it("does not rename a v6 state", () => {
    expect(migrate({ section: "observe" }, 6).section).toBe("observe");
  });

  it("moves the domain configuration out of the workbench into the cluster's section in v7", () => {
    expect(migrate({ section: "workbench", workbenchView: "domainConfig" }, 6)).toEqual({ section: "domain", workbenchView: "sceneGeneration" });
    expect(migrate({ section: "results", workbenchView: "domainConfig" }, 6)).toEqual({ section: "results", workbenchView: "sceneGeneration" });
    expect(migrate({ section: "workbench", workbenchView: "simulation" }, 6)).toEqual({ section: "workbench", workbenchView: "simulation" });
    expect(ui.WORKBENCH_VIEWS as readonly string[]).not.toContain("domainConfig");
    expect(ui.APP_SECTIONS).toContain("domain");
  });

  it("drops the scene page's old Single and Batch tab in v8 and keeps the rest", () => {
    expect(migrate({ section: "workbench", workbenchView: "sceneGeneration", sceneGenerationTab: "batch", sceneGenerationLivePreview: false }, 7)).toEqual({
      section: "workbench",
      workbenchView: "sceneGeneration",
      sceneGenerationLivePreview: false,
    });
    expect(migrate({ section: "workbench", sceneGenerationTab: "single" }, 3)).not.toHaveProperty("sceneGenerationTab");
  });

  it("lists history among the sections and not observe", () => {
    expect(ui.APP_SECTIONS).toContain("history");
    expect(ui.APP_SECTIONS as readonly string[]).not.toContain("observe");
  });

  it("takes the workbench view from the old key when there is no stored ui state", async () => {
    vi.resetModules();
    storage.setItem(ui.LEGACY_ACTIVE_VIEW_KEY, JSON.stringify("trajectoryGeneration"));
    const fresh = await import("./uiStore");
    expect(fresh.useUiStore.getState().workbenchView).toBe("trajectoryGeneration");
    expect(fresh.useUiStore.getState().section).toBe("workbench");
  });

  it("persists the section and the workbench view", () => {
    const partialize = ui.useUiStore.persist.getOptions().partialize;
    if (!partialize) {
      throw new Error("uiStore has no partialize");
    }
    ui.useUiStore.getState().setSection("history");
    ui.useUiStore.getState().setWorkbenchView("trajectoryGeneration");
    const persisted = partialize(ui.useUiStore.getState()) as Record<string, unknown>;
    expect(persisted.section).toBe("history");
    expect(persisted.workbenchView).toBe("trajectoryGeneration");
    expect(ui.useUiStore.persist.getOptions().version).toBe(8);
    expect(persisted).not.toHaveProperty("sceneGenerationTab");
  });
});

describe("rightPaneShown", () => {
  it("always shows the scene page's specification pane", () => {
    expect(ui.rightPaneShown("sceneGeneration", true)).toBe(true);
    expect(ui.rightPaneShown("sceneGeneration", false)).toBe(true);
  });

  it("always shows the design space exploration page's specification pane, the first workbench view", () => {
    expect(ui.rightPaneShown("designSpaceExploration", false)).toBe(true);
    expect(ui.WORKBENCH_VIEWS[0]).toBe("designSpaceExploration");
  });

  it("hides the monitoring panel of the trajectory and simulation pages when asked", () => {
    expect(ui.rightPaneShown("trajectoryGeneration", true)).toBe(true);
    expect(ui.rightPaneShown("trajectoryGeneration", false)).toBe(false);
    expect(ui.rightPaneShown("simulation", true)).toBe(true);
    expect(ui.rightPaneShown("simulation", false)).toBe(false);
  });

  it("never shows a right pane on Connections", () => {
    expect(ui.rightPaneShown("connections", true)).toBe(false);
  });
});
