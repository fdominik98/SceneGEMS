import { create } from "zustand";
import type { EvaluationData, GeneratedSceneData, SimulationFrame } from "../simulation/types";
import { timestampAtOrBefore } from "./playbackFrameResolve";
import { loadPersistedScene, savePersistedScene } from "./persistedScene";
import { evaluationTimeBaseline } from "../sceneGeneration/evaluationTime";


function rebuildIndex(frames: SimulationFrame[]): Record<number, number> {
  const frameIndexByTimestamp: Record<number, number> = {};
  frames.forEach((item, index) => {
    frameIndexByTimestamp[item.timestamp] = index;
  });
  return frameIndexByTimestamp;
}

function applyPreviewMergeResult(
  state: PlaybackState,
  merged: SimulationFrame[],
  firstTrajectoryChunk: boolean
): Partial<PlaybackState> {
  const latest = merged[merged.length - 1]?.timestamp ?? state.latestTimestamp;
  const hasCurrent = merged.some((f) => f.timestamp === state.currentTimestamp);
  const nextCurrent =
    state.frames.length === 0
      ? (merged[0]?.timestamp ?? state.currentTimestamp)
      : hasCurrent
        ? state.currentTimestamp
        : (merged[0]?.timestamp ?? state.currentTimestamp);
  const nextPlaybackCursor =
    state.frames.length === 0 || !hasCurrent ? nextCurrent : state.playbackCursor;
  return {
    frames: merged,
    frameIndexByTimestamp: rebuildIndex(merged),
    latestTimestamp: Math.max(state.latestTimestamp, latest),
    currentTimestamp: nextCurrent,
    playbackCursor: nextPlaybackCursor,
    hasTrajectoryChunk: true,
    autoFitPending: firstTrajectoryChunk ? true : state.autoFitPending,
    simulationInitializing: firstTrajectoryChunk ? false : state.simulationInitializing,
    // Keep latestGeneratedScene so the scene generation panel retains the
    // loaded/generated scenario and it can be initialized again.
  };
}

function applySimulationMergeResult(
  state: PlaybackState,
  merged: SimulationFrame[]
): Partial<PlaybackState> {
  const latest = merged[merged.length - 1]?.timestamp ?? state.latestTimestamp;
  return {
    simulationFrames: merged,
    simulationFrameIndexByTimestamp: rebuildIndex(merged),
    latestTimestamp: Math.max(state.latestTimestamp, latest),
    hasSimulationTrajectoryChunk: true,
    currentTimestamp: state.followLatestPush ? latest : state.currentTimestamp,
    playbackCursor: state.followLatestPush ? latest : state.playbackCursor,
    simulationInitializing:
      state.simulationFrames.length === 0 ? false : state.simulationInitializing,
  };
}

/** Clears backend-loaded trajectories so a new static or streamed scenario can take over. */
const clearedLoadedPlaybackState = {
  frames: [] as SimulationFrame[],
  frameIndexByTimestamp: {} as Record<number, number>,
  currentTimestamp: 0,
  playbackCursor: 0,
  latestTimestamp: 0,
  simulationInitialized: false,
  hasTrajectoryChunk: false,
  autoFitPending: false,
  serverTimeStep: null,
  hasSimulationTrajectoryChunk: false,
  simulationFrames: [] as SimulationFrame[],
  simulationFrameIndexByTimestamp: {} as Record<number, number>,
  simulationStatus: "not initialized" as const,
  activeScenarioId: null as string | null,
  receivedSimulationModels: null,
};

function mergeSortedUnique(
  existing: SimulationFrame[],
  incoming: SimulationFrame[]
): SimulationFrame[] {
  const byTs = new Map<number, SimulationFrame>();
  for (const f of existing) {
    byTs.set(f.timestamp, f);
  }
  for (const f of incoming) {
    byTs.set(f.timestamp, f);
  }
  return Array.from(byTs.values()).sort((a, b) => a.timestamp - b.timestamp);
}

export interface ReceivedSimulationModels {
  /** Per-vessel SDF model content keyed by the same id used in connectionsByAgentId. */
  vesselModelsByAgentId: Record<string, string | null>;
  /** Monotonic token so consumers can react even to identical repeated payloads. */
  receivedToken: number;
}

export interface PlaybackState {
  streamStatus: "connecting" | "connected" | "disconnected" | "error";
  warapsStatus: "connected" | "disconnected";
  monitorStatus: "connected" | "disconnected";
  errorMessage: string | null;
  isPlaying: boolean;
  speed: number;
  /** When true, ingested push frames move the play head to the latest timestamp. */
  followLatestPush: boolean;
  /** Active scenario load id; trajectory chunks must match this when set. */
  activeScenarioId: string | null;
  serverTimeStep: number | null;
  /** Backend has accepted scenario init; playback control is available. */
  simulationInitialized: boolean;
  /** True after Initialize is clicked until the first trajectory chunk or an error. */
  simulationInitializing: boolean;
  autoFitPending: boolean;
  hasTrajectoryChunk: boolean;
  /** Discrete frame key (snapped to buffered samples). */
  currentTimestamp: number;
  /** Continuous simulation-time playhead (seconds); used for real-time playback speed. */
  playbackCursor: number;
  latestTimestamp: number;
  frames: SimulationFrame[];
  frameIndexByTimestamp: Record<number, number>;
  /** Async simulation trajectory (separate stream from animation). */
  hasSimulationTrajectoryChunk: boolean;
  simulationFrames: SimulationFrame[];
  simulationFrameIndexByTimestamp: Record<number, number>;
  simulationStatus:
    | "running"
    | "starting"
    | "ready to start"
    | "agents are preparing"
    | "initializing"
    | "offline"
    | "not initialized";
  activeSceneGenerationRequestId: string | null;
  completedSceneGenerationRequestId: string | null;
  latestGeneratedScene: GeneratedSceneData | null;
  /** Bumped when a new single-scene generation starts; stale waits ignore updates. */
  sceneGenerationWaitEpoch: number;
  sceneGenerationEvaluationByRequestId: Record<string, EvaluationData>;
  sceneGenerationEvaluationBaselineByRequestId: Record<string, number>;
  /** Latest server-generated Gazebo models (from `simulation_models`), to load into the init tables. */
  receivedSimulationModels: ReceivedSimulationModels | null;
  setStreamStatus: (status: PlaybackState["streamStatus"]) => void;
  setWarapsStatus: (status: PlaybackState["warapsStatus"]) => void;
  setMonitorStatus: (status: PlaybackState["monitorStatus"]) => void;
  setError: (message: string | null) => void;
  setFollowLatestPush: (value: boolean) => void;
  /** Follow the latest simulation trajectory frame without starting RAF playback. */
  followSimulationLive: () => void;
  setLatestTimestamp: (value: number) => void;
  setActiveScenarioId: (id: string | null) => void;
  resetForNewScene: () => void;
  beginSimulationInitialization: () => void;
  requestAutoFit: () => void;
  consumeAutoFit: () => void;
  ingestFrame: (frame: SimulationFrame) => void;
  ingestFrames: (frames: SimulationFrame[]) => void;
  /** Apply pre-merged preview trajectory (e.g. from Web Worker). */
  applyMergedPreviewFrames: (merged: SimulationFrame[]) => void;
  ingestSimulationFrames: (frames: SimulationFrame[]) => void;
  applyMergedSimulationFrames: (merged: SimulationFrame[]) => void;
  ingestPushFrame: (frame: SimulationFrame) => void;
  clearSimulationTrajectories: () => void;
  markSimulationInitialized: () => void;
  setSimulationStatus: (status: PlaybackState["simulationStatus"]) => void;
  setActiveSceneGenerationRequestId: (requestId: string | null) => void;
  recordSceneGenerationEvaluation: (requestId: string, evaluationData: EvaluationData) => void;
  completeSceneGeneration: (requestId: string) => void;
  setReceivedSimulationModels: (models: ReceivedSimulationModels | null) => void;
  /** Sets the scene-generation preview and drops any prior backend-loaded trajectory. */
  setVisualizedScenario: (scene: GeneratedSceneData) => void;
  cancelSceneGeneration: () => void;
  clearVisualizedScenario: () => void;
  setPlaying: (value: boolean) => void;
  setSpeed: (value: number) => void;
  stepBy: (delta: number) => void;
  seek: (timestamp: number) => void;
  /** Advance continuous playhead during RAF playback (frame at or before cursor). */
  advancePlayback: (playbackCursor: number) => void;
}

export const usePlaybackStore = create<PlaybackState>((set, get) => ({
  streamStatus: "disconnected",
  warapsStatus: "disconnected",
  monitorStatus: "disconnected",
  errorMessage: null,
  isPlaying: false,
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
  activeSceneGenerationRequestId: null,
  completedSceneGenerationRequestId: null,
  latestGeneratedScene: loadPersistedScene(),
  sceneGenerationWaitEpoch: 0,
  sceneGenerationEvaluationByRequestId: {},
  sceneGenerationEvaluationBaselineByRequestId: {},
  receivedSimulationModels: null,
  setStreamStatus: (status) => set({ streamStatus: status }),
  setWarapsStatus: (status) => set({ warapsStatus: status }),
  setMonitorStatus: (status) => set({ monitorStatus: status }),
  setError: (message) =>
    set({
      errorMessage: message,
      ...(message !== null ? { simulationInitializing: false } : {}),
    }),
  setFollowLatestPush: (value) => set({ followLatestPush: value }),
  followSimulationLive: () =>
    set((state) => {
      const base = { followLatestPush: true, isPlaying: false };
      if (state.simulationFrames.length === 0) {
        return base;
      }
      const latest = state.simulationFrames[state.simulationFrames.length - 1]!.timestamp;
      const currentTimestamp = timestampAtOrBefore(state.simulationFrames, latest);
      return {
        ...base,
        playbackCursor: latest,
        currentTimestamp,
      };
    }),
  setLatestTimestamp: (value) =>
    set((state) => ({ latestTimestamp: Math.max(state.latestTimestamp, value) })),
  setActiveScenarioId: (id) => set({ activeScenarioId: id }),
  resetForNewScene: () => set(clearedLoadedPlaybackState),
  beginSimulationInitialization: () =>
    set({
      simulationInitializing: true,
      simulationStatus: "initializing",
      errorMessage: null,
    }),
  requestAutoFit: () => set({ autoFitPending: true }),
  consumeAutoFit: () => set({ autoFitPending: false }),
  ingestFrame: (frame) =>
    set((state) => {
      if (state.frameIndexByTimestamp[frame.timestamp] !== undefined) {
        return state;
      }
      const frames = [...state.frames, frame];
      return {
        frames,
        frameIndexByTimestamp: rebuildIndex(frames),
        latestTimestamp: Math.max(state.latestTimestamp, frame.timestamp),
      };
    }),
  ingestFrames: (incoming) =>
    set((state) => {
      if (incoming.length === 0) {
        return state;
      }
      const merged = mergeSortedUnique(state.frames, incoming);
      return applyPreviewMergeResult(state, merged, state.frames.length === 0);
    }),
  applyMergedPreviewFrames: (merged) =>
    set((state) => {
      if (merged.length === 0) {
        return state;
      }
      return applyPreviewMergeResult(state, merged, state.frames.length === 0);
    }),
  ingestSimulationFrames: (incoming) =>
    set((state) => {
      if (incoming.length === 0) {
        return state;
      }
      const merged = mergeSortedUnique(state.simulationFrames, incoming);
      return applySimulationMergeResult(state, merged);
    }),
  applyMergedSimulationFrames: (merged) =>
    set((state) => {
      if (merged.length === 0) {
        return state;
      }
      return applySimulationMergeResult(state, merged);
    }),
  ingestPushFrame: (frame) =>
    set((state) => {
      const exists = state.frameIndexByTimestamp[frame.timestamp] !== undefined;
      const frames = exists ? state.frames : [...state.frames, frame];
      const frameIndexByTimestamp = exists
        ? state.frameIndexByTimestamp
        : rebuildIndex(frames);
      const latest = Math.max(state.latestTimestamp, frame.timestamp);
      return {
        frames,
        frameIndexByTimestamp,
        latestTimestamp: latest,
        currentTimestamp: state.followLatestPush ? frame.timestamp : state.currentTimestamp,
        playbackCursor: state.followLatestPush ? frame.timestamp : state.playbackCursor,
      };
    }),
  clearSimulationTrajectories: () =>
    set((state) => {
      const previewLatest =
        state.frames.length > 0 ? state.frames[state.frames.length - 1]!.timestamp : 0;
      const previewStart = state.frames.length > 0 ? state.frames[0]!.timestamp : 0;
      const hadOnlySimulation =
        state.simulationFrames.length > 0 && state.frames.length === 0;
      return {
        hasSimulationTrajectoryChunk: false,
        simulationFrames: [],
        simulationFrameIndexByTimestamp: {},
        latestTimestamp:
          state.frames.length > 0
            ? Math.max(previewLatest, previewStart)
            : hadOnlySimulation
              ? 0
              : state.latestTimestamp,
        ...(hadOnlySimulation || state.simulationFrames.length > 0
          ? {
              currentTimestamp: previewStart,
              playbackCursor: previewStart,
            }
          : {}),
      };
    }),
  markSimulationInitialized: () => set({ simulationInitialized: true }),
  setSimulationStatus: (status) => set({ simulationStatus: status }),
  setActiveSceneGenerationRequestId: (requestId) =>
    set((state) => ({
      activeSceneGenerationRequestId: requestId,
      completedSceneGenerationRequestId: null,
      sceneGenerationWaitEpoch: state.sceneGenerationWaitEpoch + 1,
      sceneGenerationEvaluationByRequestId: {},
      sceneGenerationEvaluationBaselineByRequestId: {},
    })),
  recordSceneGenerationEvaluation: (requestId, evaluationData) =>
    set((state) => {
      const baseline =
        state.sceneGenerationEvaluationBaselineByRequestId[requestId] ??
        evaluationTimeBaseline(evaluationData);
      return {
        sceneGenerationEvaluationByRequestId: {
          ...state.sceneGenerationEvaluationByRequestId,
          [requestId]: evaluationData,
        },
        sceneGenerationEvaluationBaselineByRequestId: {
          ...state.sceneGenerationEvaluationBaselineByRequestId,
          [requestId]: baseline,
        },
      };
    }),
  completeSceneGeneration: (requestId) =>
    set((state) => {
      const {
        [requestId]: _removedEval,
        ...sceneGenerationEvaluationByRequestId
      } = state.sceneGenerationEvaluationByRequestId;
      const {
        [requestId]: _removedBaseline,
        ...sceneGenerationEvaluationBaselineByRequestId
      } = state.sceneGenerationEvaluationBaselineByRequestId;
      void _removedEval;
      void _removedBaseline;
      return {
        activeSceneGenerationRequestId: null,
        completedSceneGenerationRequestId: requestId,
        sceneGenerationEvaluationByRequestId,
        sceneGenerationEvaluationBaselineByRequestId,
      };
    }),
  setReceivedSimulationModels: (models) => set({ receivedSimulationModels: models }),
  setVisualizedScenario: (scene) =>
    set({
      latestGeneratedScene: scene,
      ...clearedLoadedPlaybackState,
    }),
  cancelSceneGeneration: () =>
    set((state) => {
      const requestId = state.activeSceneGenerationRequestId;
      const sceneGenerationEvaluationByRequestId = {
        ...state.sceneGenerationEvaluationByRequestId,
      };
      const sceneGenerationEvaluationBaselineByRequestId = {
        ...state.sceneGenerationEvaluationBaselineByRequestId,
      };
      if (requestId) {
        delete sceneGenerationEvaluationByRequestId[requestId];
        delete sceneGenerationEvaluationBaselineByRequestId[requestId];
      }
      return {
        activeSceneGenerationRequestId: null,
        completedSceneGenerationRequestId: null,
        sceneGenerationEvaluationByRequestId,
        sceneGenerationEvaluationBaselineByRequestId,
      };
    }),
  clearVisualizedScenario: () =>
    set({
      latestGeneratedScene: null,
      completedSceneGenerationRequestId: null,
      ...clearedLoadedPlaybackState,
    }),
  setPlaying: (value) => set({ isPlaying: value }),
  setSpeed: (value) => set({ speed: Math.max(0.1, Math.min(240, value)) }),
  stepBy: (delta) => {
    const state = get();
    state.seek(state.playbackCursor + delta);
  },
  seek: (timestamp) => {
    const state = get();
    if (state.frames.length === 0) {
      return;
    }
    const minT = state.frames[0]!.timestamp;
    const maxT = state.frames[state.frames.length - 1]!.timestamp;
    const clamped = Math.min(Math.max(timestamp, minT), maxT);
    const currentTimestamp = timestampAtOrBefore(state.frames, clamped);
    set({ followLatestPush: false, currentTimestamp, playbackCursor: clamped });
  },
  advancePlayback: (playbackCursor) => {
    set((state) => {
      if (state.frames.length === 0) {
        return state;
      }
      const minT = state.frames[0]!.timestamp;
      const maxT = state.frames[state.frames.length - 1]!.timestamp;
      const clamped = Math.min(Math.max(playbackCursor, minT), maxT);
      const currentTimestamp = timestampAtOrBefore(state.frames, clamped);
      if (
        state.playbackCursor === clamped &&
        state.currentTimestamp === currentTimestamp &&
        !state.followLatestPush
      ) {
        return state;
      }
      return {
        followLatestPush: false,
        playbackCursor: clamped,
        currentTimestamp,
      };
    });
  },
}));

export function getCurrentFrame(state: PlaybackState): SimulationFrame | null {
  const index = state.frameIndexByTimestamp[state.currentTimestamp];
  return index === undefined ? null : state.frames[index];
}

export function getCurrentSimulationFrame(state: PlaybackState): SimulationFrame | null {
  if (state.simulationFrames.length === 0) {
    return null;
  }
  const ts = timestampAtOrBefore(state.simulationFrames, state.playbackCursor);
  const index = state.simulationFrameIndexByTimestamp[ts];
  return index === undefined ? null : state.simulationFrames[index];
}

// Persist the last generated/loaded scene so it is restored on a hard refresh.
usePlaybackStore.subscribe((state, prev) => {
  if (state.latestGeneratedScene !== prev.latestGeneratedScene) {
    savePersistedScene(state.latestGeneratedScene);
  }
});
