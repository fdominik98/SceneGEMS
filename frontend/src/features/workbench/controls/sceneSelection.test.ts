import { beforeEach, describe, expect, it, vi } from "vitest";
import { sceneSelectionMode, useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { FEC_ROW_HEIGHT, visibleRange } from "../designSpace/explorationModel";
import { catalogText, loadCatalogTexts, useCatalogTexts } from "./catalogTexts";
import { copyLabel, placeOfInput, runButtonLabel } from "./sceneSelection";

describe("what a run of the selection does", () => {
  it("runs the editor's text for none, one scene for one FEC and a batch for several", () => {
    expect(sceneSelectionMode(0)).toBe("editor");
    expect(sceneSelectionMode(1)).toBe("single");
    expect(sceneSelectionMode(2)).toBe("batch");
    expect(runButtonLabel(0)).toBe("Generate scene");
    expect(runButtonLabel(1)).toBe("Generate scene");
    expect(runButtonLabel(5)).toBe("Generate 5 scenes");
  });

  it("selects the catalog FEC of an opened scene and puts any other scenario into the editor", () => {
    const catalog = new Set(["3vessel_0obstacle_scenarios/fec5"]);
    expect(placeOfInput({ label: "3vessel_0obstacle_scenarios/fec5" }, catalog)).toEqual({ kind: "select", classId: "3vessel_0obstacle_scenarios/fec5" });
    expect(placeOfInput({ label: copyLabel("3vessel_0obstacle_scenarios/fec5") }, catalog)).toEqual({ kind: "editor" });
    expect(placeOfInput({ label: "3vessel_0obstacle_scenarios/fec5 (edited)" }, catalog)).toEqual({ kind: "editor" });
    expect(placeOfInput({ label: "explored/00003" }, catalog)).toEqual({ kind: "editor" });
    // Without the catalog nothing is known to be one of its FECs
    expect(placeOfInput({ label: "3vessel_0obstacle_scenarios/fec5" }, null)).toEqual({ kind: "editor" });
  });

  it("draws a bounded window of the 828 FECs of the catalog wherever the list is scrolled", () => {
    for (const top of [0, 100 * FEC_ROW_HEIGHT, 827 * FEC_ROW_HEIGHT]) {
      const { first, last } = visibleRange(828, top, 260);
      expect(last - first).toBeLessThanOrEqual(Math.ceil(260 / FEC_ROW_HEIGHT) + 13);
      expect(last).toBeLessThanOrEqual(828);
    }
    expect(visibleRange(828, 827 * FEC_ROW_HEIGHT, 260).last).toBe(828);
  });
});

describe("the selection store", () => {
  beforeEach(() => useBatchGenerationStore.setState({ selectedClassIds: [] }));

  it("drops the FECs the catalog no longer has and keeps the others in order", () => {
    useBatchGenerationStore.setState({ selectedClassIds: ["a/fec1", "gone/fec2", "a/fec3"] });
    useBatchGenerationStore.getState().keepKnownSelection(new Set(["a/fec1", "a/fec3"]));
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual(["a/fec1", "a/fec3"]);
  });
});

describe("the catalog FECs' texts", () => {
  beforeEach(() => useCatalogTexts.getState().reset());

  it("reads each text once and says why one cannot be read", async () => {
    const read = vi.fn(async (classId: string) => (classId === "bad" ? Promise.reject(new Error("HTTP 404")) : `text of ${classId}`));
    await loadCatalogTexts(read, ["a", "b", "a", "bad"]);
    await loadCatalogTexts(read, ["a", "b", "bad"]);
    expect(read).toHaveBeenCalledTimes(3);
    expect(useCatalogTexts.getState().texts).toEqual({ a: "text of a", b: "text of b" });
    expect(useCatalogTexts.getState().errors.bad).toBe("The FEC's text could not be read: HTTP 404");
    expect(await catalogText(read, "a")).toBe("text of a");
    expect(read).toHaveBeenCalledTimes(3);
    expect(await catalogText(read, "c")).toBe("text of c");
  });
});
