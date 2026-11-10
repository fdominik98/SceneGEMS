import { beforeEach, describe, expect, it } from "vitest";
import { useTrajectoryPlaybackStore } from "../../../domain/playback/playbackStore";
import type { ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { sameStoredInput, setTrajectoryInput, simulationInputToRestore, storedTrajectoryContent } from "./pageHandoff";
import { useTrajectoryPageStore, type PageInput } from "./pageStore";

function ref(sha256: string): ConfigArtifactRef {
  return { sha256, size_bytes: 10, kind: "scene", media_type: "application/json", pointer: null } as ConfigArtifactRef;
}

function historyInput(sha256: string): PageInput {
  return { label: `scene ${sha256}`, origin: "history", ref: ref(sha256), source: { campaign_id: "c", case_id: 1, step: "scene_generation" } };
}

const sceneA = { scene: sampleFrames[0]!, evaluationData: {}, valid: true };
const sceneB = { scene: { ...sampleFrames[0]!, timestamp: 0, actors: sampleFrames[0]!.actors.slice(0, 1) }, evaluationData: {}, valid: true };
const plannedFrames = sampleFrames.slice(0, 6);

/** The page as it is after a planned trajectory was loaded for scene A. */
function showPlannedTrajectory() {
  setTrajectoryInput(historyInput("a"), sceneA);
  useTrajectoryPlaybackStore.getState().clearPreviewFrames();
  useTrajectoryPlaybackStore.getState().setTrajectoryPreviewFrames(plannedFrames);
  useTrajectoryGenerationStore.getState().markResult({ valid: true, complete: true, scenarioJson: "{}", errorMessage: null });
  useTrajectoryPageStore.getState().setLoaded({ page: "trajectoryGeneration", campaignId: "e", caseId: 2, step: "trajectory_generation" }, null);
}

beforeEach(() => {
  useTrajectoryGenerationStore.getState().reset();
  useTrajectoryGenerationStore.getState().setHandoffScene(null, null);
  useTrajectoryPageStore.setState({ input: null, loaded: null, output: null, status: "idle" });
  useTrajectoryPlaybackStore.getState().clearPreviewFrames();
});

describe("sameStoredInput", () => {
  it("compares inputs on the control node by their artifact", () => {
    expect(sameStoredInput(historyInput("a"), { ...historyInput("a"), label: "other name" })).toBe(true);
    expect(sameStoredInput(historyInput("a"), historyInput("b"))).toBe(false);
  });

  it("treats a file as a new input every time", () => {
    const file: PageInput = { label: "s.json", origin: "file", ref: null, source: { file: "s.json" } };
    expect(sameStoredInput(file, file)).toBe(false);
    expect(sameStoredInput(null, historyInput("a"))).toBe(false);
  });
});

describe("setTrajectoryInput", () => {
  it("draws the input scene on an empty page", () => {
    setTrajectoryInput(historyInput("a"), sceneA);
    const playback = useTrajectoryPlaybackStore.getState();
    expect(playback.frames).toEqual([sceneA.scene]);
    expect(playback.autoFitPending).toBe(true);
    expect(useTrajectoryPageStore.getState().input?.label).toBe("scene a");
  });

  it("replaces the trajectories of another scene with the new input scene", () => {
    showPlannedTrajectory();
    setTrajectoryInput(historyInput("b"), sceneB);
    expect(useTrajectoryPlaybackStore.getState().frames).toEqual([sceneB.scene]);
    expect(useTrajectoryGenerationStore.getState().resultScenarioJson).toBeNull();
    expect(useTrajectoryGenerationStore.getState().status).toBe("idle");
    expect(useTrajectoryPageStore.getState().loaded).toBeNull();
  });

  it("keeps the trajectories when the same scene is taken again", () => {
    showPlannedTrajectory();
    setTrajectoryInput({ ...historyInput("a"), origin: "previous_page" }, sceneA);
    expect(useTrajectoryPlaybackStore.getState().frames).toHaveLength(plannedFrames.length);
    expect(useTrajectoryGenerationStore.getState().resultScenarioJson).toBe("{}");
    expect(useTrajectoryPageStore.getState().loaded?.campaignId).toBe("e");
  });

  it("leaves the canvas to a run in progress", () => {
    setTrajectoryInput(historyInput("a"), sceneA);
    useTrajectoryGenerationStore.getState().startRun("run");
    useTrajectoryPlaybackStore.getState().setTrajectoryPreviewFrames(plannedFrames);
    setTrajectoryInput(historyInput("b"), sceneB);
    expect(useTrajectoryPlaybackStore.getState().frames).toHaveLength(plannedFrames.length);
    expect(useTrajectoryGenerationStore.getState().status).toBe("running");
    expect(useTrajectoryGenerationStore.getState().handoffScene).toBe(sceneB);
  });
});

describe("simulationInputToRestore", () => {
  const file: PageInput = { label: "run.json", origin: "file", ref: null, source: { file: "run.json" } };

  it("loads a stored input again when nothing else is loaded", () => {
    expect(simulationInputToRestore({ input: historyInput("t"), loaded: null }, false)).toMatchObject({ kind: "stored", ref: { sha256: "t" } });
  });

  it("drops a file, which is not kept after a reload", () => {
    expect(simulationInputToRestore({ input: file, loaded: null }, false)).toEqual({ kind: "file", input: file });
  });

  it("leaves a page alone that shows a loaded run, has trajectories or has no input", () => {
    expect(simulationInputToRestore({ input: historyInput("t"), loaded: { page: "simulation" } }, false).kind).toBe("none");
    expect(simulationInputToRestore({ input: historyInput("t"), loaded: null }, true).kind).toBe("none");
    expect(simulationInputToRestore({ input: null, loaded: null }, false).kind).toBe("none");
  });
});

describe("storedTrajectoryContent", () => {
  const client = { artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` };
  const respond = (body: unknown, status = 200) => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

  it("reads the trajectories of a planned trajectory document", async () => {
    const document = { trajectories: { scene_list: [{}, {}], time_step: 15 }, monitor_frames: [] };
    const content = await storedTrajectoryContent(client, { sha256: "t" }, { fetch: respond(document) });
    // The same content taking this output from Campaign History gives.
    expect(JSON.parse(content ?? "null")).toEqual(document);
  });

  it("gives null for an artifact without trajectories", async () => {
    expect(await storedTrajectoryContent(client, { sha256: "s" }, { fetch: respond({ best_scene: [] }) })).toBeNull();
  });

  it("rejects with the control node's 404 when the artifact was deleted", async () => {
    await expect(storedTrajectoryContent(client, { sha256: "x" }, { fetch: respond({}, 404) })).rejects.toMatchObject({ status: 404 });
  });
});
