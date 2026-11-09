import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../test/memoryStorage";

const storage = new MemoryStorage();
let trajectory: typeof import("./trajectoryGenerationStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  trajectory = await import("./trajectoryGenerationStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("trajectory generation persistence", () => {
  it("keeps a saved form when the persisted version changes", () => {
    const migrate = trajectory.useTrajectoryGenerationStore.persist.getOptions().migrate;
    const saved = {
      params: {
        timeStep: 15,
        timeout: 300,
        maxIterations: 2000,
        directionThreshold: 1,
        bestRandomNodesK: 20,
        previewInterval: 1,
      },
      includeMonitorResults: false,
      generator: "straight" as const,
      timespan: 600,
      handoffScene: null,
      handoffSourceName: "demo",
      status: "done" as const,
      iteration: 4,
      resultScenarioJson: "{}",
      resultValid: true,
      resultComplete: false,
      errorMessage: null,
    };
    expect(migrate?.(saved, 1)).toEqual(saved);
  });

  it("drops the old search's parameters from a version 2 form and keeps the rest", () => {
    const migrate = trajectory.useTrajectoryGenerationStore.persist.getOptions().migrate;
    const params = { timeStep: 15, timeout: 300, maxIterations: 2000, directionThreshold: 1, bestRandomNodesK: 7, previewInterval: 1 };
    const saved = {
      params: { ...params, goalSampleRate: 50, bestLeafSampleRate: 90, maxLeafs: 500 },
      includeMonitorResults: true,
      generator: "monitor_driven_rrt" as const,
      timespan: 3600,
      handoffScene: null,
      handoffSourceName: null,
      status: "idle" as const,
      iteration: 0,
      resultScenarioJson: null,
      resultValid: false,
      resultComplete: null,
      errorMessage: null,
    };
    expect(migrate?.(saved, 2)).toEqual({ ...saved, params });
  });

  it("keeps the form without the result when the result does not fit the quota", () => {
    const setItem = vi.spyOn(storage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    const blob = { state: { timespan: 600, resultScenarioJson: "x".repeat(1000), resultValid: true, resultComplete: true, status: "done" }, version: 3 };
    expect(() => trajectory.quotaSafeStorage.setItem("probe", JSON.stringify(blob))).not.toThrow();
    const stored = JSON.parse(storage.getItem("probe") ?? "null") as typeof blob;
    expect(stored.state).toEqual({ timespan: 600, resultScenarioJson: null, resultValid: false, resultComplete: null, status: "idle" });
    setItem.mockRestore();
  });

  it("persists through the quota-safe storage", () => {
    trajectory.useTrajectoryGenerationStore.getState().setTimespan(1234);
    const stored = JSON.parse(storage.getItem("scenegems:trajectory-generation") ?? "null") as { state: { timespan: number } } | null;
    expect(stored?.state.timespan).toBe(1234);
  });
});
