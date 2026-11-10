import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import type { ExploredFec } from "../../../domain/designSpace/explorationResult";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { MemoryStorage } from "../../../test/memoryStorage";
import { sendToScenePage, useSceneSpecificationHandoff } from "../pages/sceneSpecificationHandoff";
import { createExplorationInputStore, editedLabel, EXPLORATION_INPUT_KEY } from "./explorationInputStore";
import { explorationInputProblem, FEC_ROW_HEIGHT, fecCounts, visibleRange } from "./explorationModel";
import { handoffFec, useExplorationStore } from "./explorationStore";
import { allFecTexts, fecText, loadFecTexts } from "./fecTexts";
import { explorationZip, fecFileName } from "./explorationExport";

const ARTIFACT = { sha256: "a".repeat(64), size_bytes: 10, kind: "functional_scenario", media_type: "text/plain", pointer: null };

function fec(index: number, artifact: ExploredFec["artifact"] = { ...ARTIFACT, sha256: String(index).repeat(64) }): ExploredFec {
  return { fecId: `explored/0000${index}`, index, vesselCount: 2, obstacleCount: index, artifact };
}

describe("the exploration page's input", () => {
  it("is kept per browser, with the limits' defaults", async () => {
    const storage = new MemoryStorage();
    const store = createExplorationInputStore(() => storage);
    expect(store.getState()).toMatchObject({ specification: "", specificationLabel: null, scope: "", maxFecs: 1000, timeoutSeconds: 600 });
    store.getState().loadSpecification("class OS.\n", "the control node's default");
    store.getState().editSpecification("class OS.\nclass TS.\n");
    store.getState().setScope("TS = 2");
    store.getState().setMaxFecs(null);
    expect(store.getState()).toMatchObject({ specificationLabel: "the control node's default (edited)", maxFecs: null });
    expect(JSON.parse(storage.getItem(EXPLORATION_INPUT_KEY) ?? "{}").state).toEqual({
      specification: "class OS.\nclass TS.\n",
      specificationLabel: "the control node's default (edited)",
      scope: "TS = 2",
      maxFecs: null,
      timeoutSeconds: 600,
    });
    const again = createExplorationInputStore(() => storage);
    await again.persist.rehydrate();
    expect(again.getState().scope).toBe("TS = 2");
  });

  it("marks a loaded text as edited once", () => {
    expect(editedLabel(null)).toBeNull();
    expect(editedLabel("a.problem")).toBe("a.problem (edited)");
    expect(editedLabel("a.problem (edited)")).toBe("a.problem (edited)");
  });

  it("says what the run waits for", () => {
    expect(explorationInputProblem(" ", "TS = 2")).toContain("Write or load the metamodel");
    expect(explorationInputProblem("class OS.", "TS 2")).toContain("Correct the scope first");
    expect(explorationInputProblem("class OS.", "TS = 2")).toBeNull();
  });
});

describe("the explored FECs the page shows", () => {
  beforeEach(() => useExplorationStore.getState().clear());
  afterEach(() => vi.unstubAllGlobals());

  it("keeps the selection and the texts of the same entry, and starts over for another", () => {
    const store = useExplorationStore;
    store.getState().show({ campaignId: "c1", result: null, fecs: [fec(0), fec(1)], selectedFecId: "explored/00001" });
    expect(store.getState().selectedFecId).toBe("explored/00001");
    store.getState().textLoaded("explored/00001", "x");
    store.getState().show({ campaignId: "c1", result: null, fecs: [fec(0), fec(1)] });
    expect(store.getState()).toMatchObject({ selectedFecId: "explored/00001", texts: { "explored/00001": "x" } });
    store.getState().show({ campaignId: "c2", result: null, fecs: [fec(0)], selectedFecId: "explored/00009" });
    expect(store.getState()).toMatchObject({ selectedFecId: null, texts: {} });
    expect(handoffFec(store.getState())?.fecId).toBe("explored/00000");
    store.getState().clear();
    expect(handoffFec(store.getState())).toBeNull();
  });

  it("reads the texts it is asked for once, and says which cannot be read", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => (String(input).endsWith("1".repeat(64)) ? new Response("gone", { status: 404 }) : new Response("declare os.\r\n")));
    const client = { artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` };
    useExplorationStore.getState().show({ campaignId: "c1", result: null, fecs: [fec(0), fec(1), fec(2, null)] });
    await loadFecTexts(client, ["explored/00000", "explored/00001", "explored/00002"], fetchImpl as unknown as typeof fetch);
    await loadFecTexts(client, ["explored/00000"], fetchImpl as unknown as typeof fetch);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const state = useExplorationStore.getState();
    expect(state.texts).toEqual({ "explored/00000": "declare os.\n" });
    expect(Object.keys(state.textErrors).sort()).toEqual(["explored/00001", "explored/00002"]);
    expect(state.loadingTexts).toEqual({});
    await expect(fecText(client, fec(1), fetchImpl as unknown as typeof fetch)).rejects.toThrow("could not be read");
    expect((await allFecTexts(client, fetchImpl as unknown as typeof fetch)).map((entry) => entry.fec.fecId)).toEqual(["explored/00000"]);
  });

  it("exports the texts as .problem files", async () => {
    expect(fecFileName("explored/00003")).toBe("explored_00003.problem");
    const blob = await explorationZip([{ fec: fec(3), text: "declare os.\n" }]);
    expect(blob.size).toBeGreaterThan(0);
  });

  it("draws only the rows in view, each the same height", () => {
    expect(fecCounts({ vesselCount: 1, obstacleCount: 0 })).toBe("1 vessel, 0 obstacles");
    expect(fecCounts({ vesselCount: null, obstacleCount: 2 })).toBe("? vessels, 2 obstacles");
    expect(visibleRange(462, 0, 10 * FEC_ROW_HEIGHT)).toEqual({ first: 0, last: 16 });
    expect(visibleRange(462, 100 * FEC_ROW_HEIGHT, 10 * FEC_ROW_HEIGHT)).toEqual({ first: 94, last: 116 });
    expect(visibleRange(3, 0, 10 * FEC_ROW_HEIGHT)).toEqual({ first: 0, last: 3 });
  });
});

describe("a FEC sent to the scene page", () => {
  it("is queued for the scene page's editor, which is shown: the FECs selected there are cleared", async () => {
    useUiStore.setState({ section: "history", workbenchView: "simulation", sceneGenerationPaneView: "monitor" });
    useBatchGenerationStore.setState({ selectedClassIds: ["2vessel_0obstacle_scenarios/fec1", "2vessel_0obstacle_scenarios/fec2"] });
    sendToScenePage({ label: "explored/00003", text: async () => "declare os.\n" });
    expect(useUiStore.getState()).toMatchObject({ section: "workbench", workbenchView: "sceneGeneration", sceneGenerationPaneView: "specification" });
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([]);
    const load = useSceneSpecificationHandoff.getState().take();
    expect(load?.label).toBe("explored/00003");
    expect(await load?.text()).toBe("declare os.\n");
    expect(useSceneSpecificationHandoff.getState().take()).toBeNull();
  });
});
