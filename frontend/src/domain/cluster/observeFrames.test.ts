import { describe, expect, it } from "vitest";
import { instanceReducer, INSTANCE_FRAMES_KEPT, sceneSampleSchema, trajectoryPreviewSchema } from "./liveTopics";
import {
  jobInstanceSnapshot,
  sceneSampleUpdate,
  simulationFramesUpdate,
  trajectoryPreviewUpdate,
  trajectoryResultUpdate,
  wireFrame,
} from "../../test/fixtures/observeViews";
import { evaluationFacts, FrameBuffer, sceneSampleFrames, trajectoryPreviewFrames } from "./observeFrames";

describe("sceneSampleFrames", () => {
  it("parses the scene of a sample into one frame", () => {
    const sample = sceneSampleSchema.parse(sceneSampleUpdate({ valid: true, final: true }));
    const { frames, error } = sceneSampleFrames(sample);
    expect(error).toBeNull();
    expect(frames).toHaveLength(1);
    expect(frames[0].actors.map((actor) => actor.id)).toEqual(["own_ship", "target_1"]);
    expect(frames[0].statesByActorId.own_ship.speed).toBe(6.5);
  });

  it("gives no frames for a sample without a scene and says so for a scene that does not parse", () => {
    expect(sceneSampleFrames(null)).toEqual({ frames: [], error: null });
    expect(sceneSampleFrames(sceneSampleSchema.parse(sceneSampleUpdate({ scene: null })))).toEqual({ frames: [], error: null });
    const broken = sceneSampleFrames(sceneSampleSchema.parse(sceneSampleUpdate({ scene: { timestamp: "later" } })));
    expect(broken.frames).toEqual([]);
    expect(broken.error).toMatch(/could not be read/);
  });
});

describe("trajectoryPreviewFrames", () => {
  it("builds one frame per planned scene, spaced by the time step", () => {
    const preview = trajectoryPreviewSchema.parse(trajectoryPreviewUpdate(4));
    const { frames, error } = trajectoryPreviewFrames(preview);
    expect(error).toBeNull();
    expect(frames.map((frame) => frame.timestamp)).toEqual([0, 2, 4, 6]);
    expect(frames[3].timeStep).toBe(2);
    expect(frames[3].statesByActorId["0"].x).toBe(30);
    expect(frames[3].actors.find((actor) => actor.isOwnShip)?.name).toBe("os");
  });

  it("converts the final result the same way", () => {
    const result = trajectoryPreviewSchema.parse(trajectoryResultUpdate({ complete: false, error_message: "timed out" }));
    expect(trajectoryPreviewFrames(result).frames).toHaveLength(6);
    expect(result).toMatchObject({ final: true, valid: true, complete: false, error_message: "timed out" });
  });

  it("gives no frames without trajectories", () => {
    expect(trajectoryPreviewFrames(null)).toEqual({ frames: [], error: null });
    expect(trajectoryPreviewFrames(trajectoryPreviewSchema.parse(trajectoryPreviewUpdate(2, { trajectories: null }))).frames).toEqual([]);
    expect(trajectoryPreviewFrames(trajectoryPreviewSchema.parse(trajectoryPreviewUpdate(2, { trajectories: {} }))).frames).toEqual([]);
  });
});

describe("frames while live", () => {
  it("collects the frames of simulation_frames updates in order and counts them", () => {
    let state = instanceReducer.snapshot(jobInstanceSnapshot());
    state = instanceReducer.update(state, simulationFramesUpdate(0, 3), 1);
    state = instanceReducer.update(state, simulationFramesUpdate(3, 2), 2);
    expect(state.frameCount).toBe(5);
    expect(state.frames).toHaveLength(5);
  });

  it("parses only the frames that arrived since the last call", () => {
    const buffer = new FrameBuffer(100);
    let state = instanceReducer.snapshot(jobInstanceSnapshot());
    state = instanceReducer.update(state, simulationFramesUpdate(0, 3), 1);
    const first = buffer.sync(state.frames, state.frameCount);
    expect(first.map((frame) => frame.timestamp)).toEqual([0, 1, 2]);

    // Nothing new: the same list comes back.
    expect(buffer.sync(state.frames, state.frameCount)).toBe(first);

    state = instanceReducer.update(state, simulationFramesUpdate(3, 2), 2);
    const second = buffer.sync(state.frames, state.frameCount);
    expect(second.map((frame) => frame.timestamp)).toEqual([0, 1, 2, 3, 4]);
  });

  it("keeps the newest frames when the buffer is bounded", () => {
    const buffer = new FrameBuffer(4);
    let state = instanceReducer.snapshot(jobInstanceSnapshot());
    state = instanceReducer.update(state, simulationFramesUpdate(0, 3), 1);
    buffer.sync(state.frames, state.frameCount);
    state = instanceReducer.update(state, simulationFramesUpdate(3, 3), 2);
    expect(buffer.sync(state.frames, state.frameCount).map((frame) => frame.timestamp)).toEqual([2, 3, 4, 5]);
  });

  it("follows the topic state's own bound and counts frames it no longer keeps", () => {
    const buffer = new FrameBuffer(INSTANCE_FRAMES_KEPT);
    let state = instanceReducer.snapshot(jobInstanceSnapshot());
    state = { ...state, frames: Array.from({ length: INSTANCE_FRAMES_KEPT }, (_, index) => wireFrame(index)), frameCount: INSTANCE_FRAMES_KEPT + 100 };
    expect(buffer.sync(state.frames, state.frameCount)).toHaveLength(INSTANCE_FRAMES_KEPT);
  });

  it("starts over after a new snapshot and leaves out frames that do not parse", () => {
    const buffer = new FrameBuffer(100);
    let state = instanceReducer.snapshot(jobInstanceSnapshot());
    state = instanceReducer.update(state, simulationFramesUpdate(0, 3), 1);
    buffer.sync(state.frames, state.frameCount);

    const fresh = instanceReducer.snapshot(jobInstanceSnapshot());
    expect(buffer.sync(fresh.frames, fresh.frameCount)).toEqual([]);

    const next = instanceReducer.update(
      fresh,
      { kind: "simulation_frames", job_id: "job-1", frames: [wireFrame(7), { nonsense: true }, wireFrame(8)] },
      1
    );
    const frames = buffer.sync(next.frames, next.frameCount);
    expect(frames.map((frame) => frame.timestamp)).toEqual([7, 8]);
    expect(buffer.skippedCount).toBe(1);
  });
});

describe("evaluationFacts", () => {
  it("lists scalar entries and list lengths, a few of them", () => {
    const facts = evaluationFacts({ iterations: 42, best_score: 0.8125, status: "searching", constraints: ["a", "b"], nested: { x: 1 }, valid: true });
    expect(facts).toEqual([
      { label: "iterations", value: "42" },
      { label: "best score", value: "0.813" },
      { label: "status", value: "searching" },
      { label: "constraints", value: "2 entries" },
      { label: "valid", value: "yes" },
    ]);
    expect(evaluationFacts({ a: 1, b: 2, c: 3 }, 2)).toHaveLength(2);
  });

  it("gives nothing for data that is not an object", () => {
    expect(evaluationFacts(null)).toEqual([]);
    expect(evaluationFacts([1, 2])).toEqual([]);
  });
});
