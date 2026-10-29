import { beforeEach, describe, expect, it, vi } from "vitest";

const storage = new Map<string, string>();
vi.stubGlobal("window", {
  localStorage: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  },
});

const { useUiStore } = await import("../../../app/uiStore");
const { openInWorkbench, useWorkbenchTargetStore } = await import("./workbenchTarget");
const { consumeTarget, loadedTargets } = await import("./useWorkbenchTargets");
const { PAGE_STORES } = await import("./pageStore");

describe("target consumption", () => {
  beforeEach(() => {
    useWorkbenchTargetStore.setState({ pending: {} });
    useUiStore.setState({ section: "history", workbenchView: "connections" });
    for (const store of Object.values(PAGE_STORES)) {
      store.setState({ loaded: null });
    }
  });

  it("opens a queued target once, on its page only", () => {
    openInWorkbench({ page: "trajectoryGeneration", campaignId: "c1", caseId: 4, step: "trajectory_generation" });
    const open = vi.fn();
    expect(consumeTarget("simulation", open)).toBeUndefined();
    expect(consumeTarget("trajectoryGeneration", open)?.caseId).toBe(4);
    expect(consumeTarget("trajectoryGeneration", open)).toBeUndefined();
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ campaignId: "c1", caseId: 4 }));
  });

  it("opens only the newest of two targets queued for a page", () => {
    openInWorkbench({ page: "simulation", campaignId: "c1", caseId: 1, step: "simulation", runRecordId: 3 });
    openInWorkbench({ page: "simulation", campaignId: "c2", caseId: 2, step: "simulation", live: true });
    const open = vi.fn();
    consumeTarget("simulation", open);
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.mock.calls[0][0]).toMatchObject({ campaignId: "c2", live: true });
  });

  it("lists the pages' loaded entries to fetch again", () => {
    PAGE_STORES.sceneGeneration.setState({ loaded: { page: "sceneGeneration", campaignId: "a", caseId: 1, step: "scene_generation" } });
    PAGE_STORES.simulation.setState({ loaded: { page: "simulation", campaignId: "b", caseId: 2, step: "simulation", runRecordId: 7 } });
    expect(loadedTargets().map((target) => target.campaignId)).toEqual(["a", "b"]);
  });
});
