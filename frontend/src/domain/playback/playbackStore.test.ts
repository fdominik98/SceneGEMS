import { beforeEach, describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { getCurrentFrame, usePlaybackStore } from "./playbackStore";

describe("playbackStore", () => {
  beforeEach(() => {
    usePlaybackStore.setState({
      streamStatus: "disconnected",
      errorMessage: null,
      isPlaying: true,
      speed: 1,
      followLatestPush: true,
      activeScenarioId: null,
      serverTimeStep: null,
      simulationInitialized: false,
      simulationInitializing: false,
      autoFitPending: false,
      hasTrajectoryChunk: false,
      currentTimestamp: 0,
      playbackCursor: 0,
      latestTimestamp: 0,
      frames: [],
      frameIndexByTimestamp: {},
      hasSimulationTrajectoryChunk: false,
      simulationFrames: [],
      simulationFrameIndexByTimestamp: {},
      simulationStatus: "not initialized",
    });
  });

  it("ingests frames and tracks latest timestamp", () => {
    const { ingestFrame } = usePlaybackStore.getState();
    ingestFrame(sampleFrames[0]);
    ingestFrame(sampleFrames[1]);
    const state = usePlaybackStore.getState();
    expect(state.frames).toHaveLength(2);
    expect(state.latestTimestamp).toBe(1);
  });

  it("seeks to the latest buffered frame at or before the requested time", () => {
    const { ingestFrame, seek } = usePlaybackStore.getState();
    ingestFrame(sampleFrames[0]);
    ingestFrame(sampleFrames[2]);
    seek(1);
    const frame = getCurrentFrame(usePlaybackStore.getState());
    expect(frame?.timestamp).toBe(0);
    seek(2);
    expect(getCurrentFrame(usePlaybackStore.getState())?.timestamp).toBe(2);
  });

  it("followSimulationLive jumps to latest simulation frame without playing", () => {
    const { ingestSimulationFrames, followSimulationLive } = usePlaybackStore.getState();
    ingestSimulationFrames(
      [0, 5, 12].map((timestamp) => ({
        ...sampleFrames[0],
        timestamp,
      }))
    );
    usePlaybackStore.setState({ isPlaying: true, followLatestPush: false, playbackCursor: 0 });
    followSimulationLive();
    const state = usePlaybackStore.getState();
    expect(state.isPlaying).toBe(false);
    expect(state.followLatestPush).toBe(true);
    expect(state.playbackCursor).toBe(12);
    expect(state.currentTimestamp).toBe(12);
  });

  it("advancePlayback steps through sparse timestamps without freezing mid-gap", () => {
    const { ingestFrames, advancePlayback } = usePlaybackStore.getState();
    ingestFrames(
      [0, 10, 20].map((timestamp) => ({
        ...sampleFrames[0],
        timestamp,
      }))
    );
    advancePlayback(5);
    expect(usePlaybackStore.getState().currentTimestamp).toBe(0);
    expect(usePlaybackStore.getState().playbackCursor).toBe(5);
    advancePlayback(10);
    expect(usePlaybackStore.getState().currentTimestamp).toBe(10);
    advancePlayback(19);
    expect(usePlaybackStore.getState().currentTimestamp).toBe(10);
    advancePlayback(20);
    expect(usePlaybackStore.getState().currentTimestamp).toBe(20);
  });

  it("sets latest timestamp from init payload horizon", () => {
    const { setLatestTimestamp } = usePlaybackStore.getState();
    setLatestTimestamp(300);
    const state = usePlaybackStore.getState();
    expect(state.latestTimestamp).toBe(300);
  });

  it("allows requesting auto-fit when revisiting simulation view", () => {
    const { requestAutoFit, consumeAutoFit } = usePlaybackStore.getState();
    requestAutoFit();
    expect(usePlaybackStore.getState().autoFitPending).toBe(true);
    consumeAutoFit();
    expect(usePlaybackStore.getState().autoFitPending).toBe(false);
  });

  it("keeps full buffered history for chunked trajectories", () => {
    const { ingestFrames, seek } = usePlaybackStore.getState();
    const frames = Array.from({ length: 3001 }, (_, timestamp) => ({
      ...sampleFrames[0],
      timestamp,
    }));
    ingestFrames(frames);

    const stateAfterIngest = usePlaybackStore.getState();
    expect(stateAfterIngest.frames).toHaveLength(3001);

    seek(0);
    const frameAtStart = getCurrentFrame(usePlaybackStore.getState());
    expect(frameAtStart?.timestamp).toBe(0);
  });

  it("follows latest simulation chunk timestamp while auto-follow is enabled", () => {
    const { ingestSimulationFrames } = usePlaybackStore.getState();
    const simulationFrames = [0, 1, 2].map((timestamp) => ({
      ...sampleFrames[0],
      timestamp,
    }));
    ingestSimulationFrames(simulationFrames);
    const state = usePlaybackStore.getState();
    expect(state.currentTimestamp).toBe(2);
    expect(state.playbackCursor).toBe(2);
  });

  it("clears loaded simulation trajectory chunks and rewinds simulation-only playback", () => {
    const { ingestSimulationFrames, clearSimulationTrajectories } =
      usePlaybackStore.getState();
    ingestSimulationFrames(
      [0, 1, 5].map((timestamp) => ({
        ...sampleFrames[0],
        timestamp,
      }))
    );
    clearSimulationTrajectories();
    const state = usePlaybackStore.getState();
    expect(state.simulationFrames).toEqual([]);
    expect(state.hasSimulationTrajectoryChunk).toBe(false);
    expect(state.latestTimestamp).toBe(0);
    expect(state.currentTimestamp).toBe(0);
    expect(state.playbackCursor).toBe(0);
  });

  it("sorts a large unsorted preview chunk by timestamp", () => {
    const { ingestFrames } = usePlaybackStore.getState();
    const timestamps = Array.from({ length: 100 }, (_, i) => i);
    const shuffled = [...timestamps].sort(() => Math.random() - 0.5);
    const frames = shuffled.map((timestamp) => ({
      ...sampleFrames[0],
      timestamp,
    }));
    ingestFrames(frames);
    const { frames: stored } = usePlaybackStore.getState();
    expect(stored).toHaveLength(100);
    expect(stored.map((f) => f.timestamp)).toEqual(timestamps);
  });

  it("refreshes preview frames when the same timestamp arrives again", () => {
    const { ingestFrames } = usePlaybackStore.getState();
    const first = { ...sampleFrames[0], timestamp: 5, actors: sampleFrames[0].actors };
    const refreshed = {
      ...sampleFrames[0],
      timestamp: 5,
      actors: sampleFrames[0].actors.map((a) => ({ ...a, maxSpeed: 99 })),
    };
    ingestFrames([first]);
    ingestFrames([refreshed]);
    const stored = usePlaybackStore.getState().frames.find((f) => f.timestamp === 5);
    expect(stored?.actors[0]?.maxSpeed).toBe(99);
    expect(usePlaybackStore.getState().frames).toHaveLength(1);
  });

  it("sorts a large unsorted simulation chunk and follows latest", () => {
    const { ingestSimulationFrames } = usePlaybackStore.getState();
    const timestamps = Array.from({ length: 100 }, (_, i) => i);
    const shuffled = [...timestamps].sort(() => Math.random() - 0.5);
    ingestSimulationFrames(
      shuffled.map((timestamp) => ({ ...sampleFrames[0], timestamp }))
    );
    const state = usePlaybackStore.getState();
    expect(state.simulationFrames.map((f) => f.timestamp)).toEqual(timestamps);
    expect(state.currentTimestamp).toBe(99);
    expect(state.playbackCursor).toBe(99);
  });

  it("setVisualizedScenario replaces buffered trajectories", () => {
    const { ingestFrames, setVisualizedScenario } = usePlaybackStore.getState();
    ingestFrames(sampleFrames);
    setVisualizedScenario({
      scene: sampleFrames[0],
      evaluationData: { scenario_name: "test" },
      valid: true,
    });
    const state = usePlaybackStore.getState();
    expect(state.frames).toEqual([]);
    expect(state.hasTrajectoryChunk).toBe(false);
    expect(state.latestGeneratedScene?.valid).toBe(true);
  });

  it("retains the visualized scene when the first preview trajectory chunk arrives", () => {
    const { setVisualizedScenario, ingestFrames } = usePlaybackStore.getState();
    setVisualizedScenario({
      scene: sampleFrames[0],
      evaluationData: { scenario_name: "test" },
      valid: true,
    });
    ingestFrames([sampleFrames[0]]);
    // The scene stays in the scene generation panel so it can be initialized again.
    expect(usePlaybackStore.getState().latestGeneratedScene?.valid).toBe(true);
    expect(usePlaybackStore.getState().hasTrajectoryChunk).toBe(true);
  });

  it("clears simulation chunks but keeps preview playback horizon", () => {
    const { ingestFrames, ingestSimulationFrames, clearSimulationTrajectories } =
      usePlaybackStore.getState();
    ingestFrames(sampleFrames);
    ingestSimulationFrames([
      { ...sampleFrames[0], timestamp: 10 },
      { ...sampleFrames[0], timestamp: 20 },
    ]);
    clearSimulationTrajectories();
    const state = usePlaybackStore.getState();
    expect(state.simulationFrames).toEqual([]);
    expect(state.frames).toHaveLength(sampleFrames.length);
    expect(state.latestTimestamp).toBe(199);
  });
});
