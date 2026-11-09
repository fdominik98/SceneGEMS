import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../test/memoryStorage";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { createPlaybackStore } from "./playbackStore";

const storage = new MemoryStorage();
const KEY = "scenegems:visualized-scene";

beforeAll(() => {
  vi.stubGlobal("window", { localStorage: storage });
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("the scene page's persisted scene", () => {
  it("writes the scene shown when a generation ends, not every sample on the way", () => {
    storage.clear();
    const store = createPlaybackStore({ persistScene: true });
    store.getState().setActiveSceneGenerationRequestId("run");
    store.getState().setVisualizedScenario({ scene: sampleFrames[0]!, valid: false });
    store.getState().setVisualizedScenario({ scene: sampleFrames[1]!, valid: false });
    expect(storage.getItem(KEY)).toBeNull();

    store.getState().completeSceneGeneration("run");
    expect(JSON.parse(storage.getItem(KEY) ?? "null")).toMatchObject({ scene: { timestamp: sampleFrames[1]!.timestamp } });
  });

  it("writes a scene loaded outside a generation at once", () => {
    storage.clear();
    const store = createPlaybackStore({ persistScene: true });
    store.getState().setVisualizedScenario({ scene: sampleFrames[2]!, valid: true });
    expect(storage.getItem(KEY)).not.toBeNull();
    store.getState().clearVisualizedScenario();
    expect(storage.getItem(KEY)).toBeNull();
  });
});
