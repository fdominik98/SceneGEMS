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
});
