import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../test/memoryStorage";

// zustand's persist takes localStorage when the store is created, so the module loads after the stub.
const storage = new MemoryStorage();
let store: typeof import("./batchGenerationStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  storage.setItem("scenegems:scene-generation-selection", JSON.stringify({ state: { selectedClassIds: ["a/fec1", 7, "a/fec2"] }, version: 1 }));
  store = await import("./batchGenerationStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("the scene page's selection of catalog FECs", () => {
  it("is read back per browser, without what is not a class id", () => {
    expect(store.useBatchGenerationStore.getState().selectedClassIds).toEqual(["a/fec1", "a/fec2"]);
  });

  it("keeps only the selection, not the results or the run", () => {
    const { useBatchGenerationStore, SCENE_SELECTION_STORAGE_KEY } = store;
    useBatchGenerationStore.setState({ running: true, results: [{ classId: "a/fec1", label: "a/fec1", requestId: "r1", status: "pending" }] });
    useBatchGenerationStore.getState().toggleSelectedClassId("b/fec3");
    expect(JSON.parse(storage.getItem(SCENE_SELECTION_STORAGE_KEY) ?? "{}").state).toEqual({ selectedClassIds: ["a/fec1", "a/fec2", "b/fec3"] });
  });
});
