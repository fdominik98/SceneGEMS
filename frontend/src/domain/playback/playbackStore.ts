import { create } from "zustand";
import type { EvaluationData, GeneratedSceneData, SimulationFrame } from "../simulation/types";
import type { StackOptionsPayload } from "../simulation/wireTypes";
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

/**
 * The preview frame key at a play head time: `currentTimestamp` names a preview frame, so it
 * snaps to the preview's own timestamps (the simulation may sample at other times).
 */
function previewKeyAt(frames: SimulationFrame[], t: number): number {
  return frames.length > 0 ? timestampAtOrBefore(frames, t) : t;
}

/** The time span playback covers: the preview and the simulation together, null without frames. */
export function playbackRange(state: Pick<PlaybackState, "frames" | "simulationFrames">): { min: number; max: number } | null {
  const { frames, simulationFrames } = state;
  if (frames.length === 0 && simulationFrames.length === 0) {
    return null;
  }
  return {
    min: Math.min(frames[0]?.timestamp ?? Infinity, simulationFrames[0]?.timestamp ?? Infinity),
    max: Math.max(frames[frames.length - 1]?.timestamp ?? -Infinity, simulationFrames[simulationFrames.length - 1]?.timestamp ?? -Infinity),
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
    currentTimestamp: state.followLatestPush ? previewKeyAt(state.frames, latest) : state.currentTimestamp,
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
  scenarioTrajectoryLength: null as number | null,
  simulationInitialized: false,
  simulationInitializing: false,
  hasTrajectoryChunk: false,
  autoFitPending: false,
  serverTimeStep: null,
  hasSimulationTrajectoryChunk: false,
  simulationFrames: [] as SimulationFrame[],
  simulationFrameIndexByTimestamp: {} as Record<number, number>,
  simulationStatus: "not initialized" as const,
  groundControlPortsByAgentId: {} as Record<string, number>,
  activeScenarioId: null as string | null,
  receivedSimulationModels: null,
};

/**
 * The buffered frames (sorted by time) with a chunk merged in, an incoming frame replacing one
 * at the same time. Linear in the frames, so a long stream of chunks stays cheap; a chunk that
 * only extends the end, the usual case, is appended.
 */
export function mergeSortedUnique(existing: SimulationFrame[], incoming: SimulationFrame[]): SimulationFrame[] {
  const chunk = [...incoming].sort((a, b) => a.timestamp - b.timestamp);
  const lastExisting = existing[existing.length - 1];
  if (lastExisting === undefined || chunk[0]!.timestamp > lastExisting.timestamp) {
    const merged = existing.slice();
    for (const frame of chunk) {
      if (merged.length === 0 || frame.timestamp > merged[merged.length - 1]!.timestamp) {
        merged.push(frame);
      } else {
        merged[merged.length - 1] = frame;
      }
    }
    return merged;
  }
  const merged: SimulationFrame[] = [];
  const push = (frame: SimulationFrame) => {
    const last = merged[merged.length - 1];
    if (last !== undefined && last.timestamp === frame.timestamp) {
      merged[merged.length - 1] = frame;
    } else {
      merged.push(frame);
    }
  };
  let i = 0;
  let j = 0;
  while (i < existing.length || j < chunk.length) {
    // On a tie the incoming frame comes second, so it replaces the buffered one.
    if (j >= chunk.length || (i < existing.length && existing[i]!.timestamp <= chunk[j]!.timestamp)) {
      push(existing[i++]!);
    } else {
      push(chunk[j++]!);
    }
  }
  return merged;
}

export interface ReceivedSimulationModels {
  /** Per-vessel SDF model content keyed by the same id used in connectionsByAgentId. */
  vesselModelsByAgentId: Record<string, string | null>;
  /** Monotonic token so consumers can react even to identical repeated payloads. */
  receivedToken: number;
}

/** The cluster's post-hoc monitoring of the loaded preview trajectory. */
export interface PreviewMonitorState {
  status: "idle" | "running" | "done" | "unavailable" | "failed";
  /** The scenario the state belongs to; a newer load replaces it. */
  scenarioId: string | null;
  message: string | null;
}

export const IDLE_PREVIEW_MONITOR: PreviewMonitorState = { status: "idle", scenarioId: null, message: null };

export interface PlaybackState {
  streamStatus: "connecting" | "connected" | "disconnected" | "error";
  /** The interactive simulation's MQTT broker connection on the server. */
  mqttBrokerStatus: "connected" | "disconnected";
  /** The master's own broker as the server dials it ("host:port"), null when it has none or is not known yet. */
  masterBroker: string | null;
  monitorStatus: "connected" | "disconnected";
  errorMessage: string | null;
  isPlaying: boolean;
  speed: number;
  /** Playback waits at the end of the buffered frames instead of stopping, while frames keep arriving. */
  holdAtLiveEdge: boolean;
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
  /**
   * Seconds of trajectory in the loaded scenario, as the backend reported it with
   * `initial_state`. 0 is a bare scene (its initial scene only); null before any load.
   */
  scenarioTrajectoryLength: number | null;
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
  /** Request id of the pending monitor run for a scene loaded from disk. */
  pendingSceneMonitorRequestId: string | null;
  /** Bumped when a new single-scene generation starts; stale waits ignore updates. */
  sceneGenerationWaitEpoch: number;
  sceneGenerationEvaluationByRequestId: Record<string, EvaluationData>;
  sceneGenerationEvaluationBaselineByRequestId: Record<string, number>;
  /** Latest server-generated Gazebo models (from `simulation_models`), to load into the init tables. */
  receivedSimulationModels: ReceivedSimulationModels | null;
  /** Host port (TCP on localhost) of each Mission Planner vessel's ground control station, by agent id. */
  groundControlPortsByAgentId: Record<string, number>;
  /** The backend resolver's stack combinations (from `stack_options`); null until received. */
  stackOptions: StackOptionsPayload | null;
  setStackOptions: (options: StackOptionsPayload | null) => void;
  setStreamStatus: (status: PlaybackState["streamStatus"]) => void;
  setMqttBrokerStatus: (status: PlaybackState["mqttBrokerStatus"], masterBroker?: string | null) => void;
  previewMonitor: PreviewMonitorState;
  setPreviewMonitor: (state: PreviewMonitorState) => void;
  setMonitorStatus: (status: PlaybackState["monitorStatus"]) => void;
  setError: (message: string | null) => void;
  setFollowLatestPush: (value: boolean) => void;
  /** Follow the latest simulation trajectory frame without starting RAF playback. */
  followSimulationLive: () => void;
  setLatestTimestamp: (value: number) => void;
  setScenarioTrajectoryLength: (value: number | null) => void;
  setActiveScenarioId: (id: string | null) => void;
  resetForNewScene: () => void;
  beginSimulationInitialization: () => void;
  requestAutoFit: () => void;
  consumeAutoFit: () => void;
  ingestFrame: (frame: SimulationFrame) => void;
  ingestFrames: (frames: SimulationFrame[]) => void;
  ingestSimulationFrames: (frames: SimulationFrame[]) => void;
  applyMergedSimulationFrames: (merged: SimulationFrame[]) => void;
  /** Replace the preview trajectory wholesale (trajectory generation previews/results). */
  setTrajectoryPreviewFrames: (frames: SimulationFrame[]) => void;
  /** Drop the preview trajectory without touching simulation/scene-generation state. */
  clearPreviewFrames: () => void;
  ingestPushFrame: (frame: SimulationFrame) => void;
  clearSimulationTrajectories: () => void;
  markSimulationInitialized: () => void;
  setSimulationStatus: (
    status: PlaybackState["simulationStatus"],
    groundControlPortsByAgentId?: Record<string, number>
  ) => void;
  setActiveSceneGenerationRequestId: (requestId: string | null) => void;
  recordSceneGenerationEvaluation: (requestId: string, evaluationData: EvaluationData) => void;
  completeSceneGeneration: (requestId: string) => void;
  setReceivedSimulationModels: (models: ReceivedSimulationModels | null) => void;
  /** Sets the scene-generation preview and drops any prior backend-loaded trajectory. */
  setVisualizedScenario: (scene: GeneratedSceneData) => void;
  beginSceneMonitor: (requestId: string) => void;
  /** Merges the monitor fields of a `monitor_scene` answer into the displayed scene. */
  applySceneMonitorResult: (requestId: string, frame: SimulationFrame) => void;
  cancelSceneGeneration: () => void;
  clearVisualizedScenario: () => void;
  setPlaying: (value: boolean) => void;
  /** Keep playing at the end of the buffered frames, waiting for more (a cluster run whose watch speed is the playback speed). */
  setHoldAtLiveEdge: (value: boolean) => void;
  setSpeed: (value: number) => void;
  stepBy: (delta: number) => void;
  seek: (timestamp: number) => void;
  /** Advance continuous playhead during RAF playback (frame at or before cursor). */
  advancePlayback: (playbackCursor: number) => void;
}

export interface PlaybackStoreOptions {
  /** Restore the shown scene after a reload (the scene generation page). */
  persistScene?: boolean;
}

/**
 * A playback store: one per workbench page, so each page renders its own scene, trajectories or
 * run (design doc 6.6). `usePlaybackStore` is the simulation page's and also holds the gateway
 * session (stream, broker, monitor and simulation status, stack options, errors);
 * `useScenePlaybackStore` holds the scene generation page's scene, `useTrajectoryPlaybackStore`
 * the trajectory generation page's planned trajectories. Components of a page read the page's
 * store through `PlaybackStoreContext` (`playbackContext.ts`).
 */
export function createPlaybackStore(options: PlaybackStoreOptions = {}) {
  const store = create<PlaybackState>((set, get) => ({
    streamStatus: "disconnected",
    mqttBrokerStatus: "disconnected",
    masterBroker: null,
    previewMonitor: IDLE_PREVIEW_MONITOR,
    setPreviewMonitor: (previewMonitor) => set({ previewMonitor }),
    monitorStatus: "disconnected",
    errorMessage: null,
    isPlaying: false,
    speed: 1,
    holdAtLiveEdge: false,
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
    scenarioTrajectoryLength: null,
    frames: [],
    frameIndexByTimestamp: {},
    hasSimulationTrajectoryChunk: false,
    simulationFrames: [],
    simulationFrameIndexByTimestamp: {},
    simulationStatus: "not initialized",
    activeSceneGenerationRequestId: null,
    completedSceneGenerationRequestId: null,
    latestGeneratedScene: options.persistScene ? loadPersistedScene() : null,
    pendingSceneMonitorRequestId: null,
    sceneGenerationWaitEpoch: 0,
    sceneGenerationEvaluationByRequestId: {},
    sceneGenerationEvaluationBaselineByRequestId: {},
    receivedSimulationModels: null,
    groundControlPortsByAgentId: {},
    stackOptions: null,
    setStackOptions: (options) => set({ stackOptions: options }),
    setStreamStatus: (status) => set({ streamStatus: status }),
    setMqttBrokerStatus: (status, masterBroker) =>
      set(masterBroker === undefined ? { mqttBrokerStatus: status } : { mqttBrokerStatus: status, masterBroker }),
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
        return {
          ...base,
          playbackCursor: latest,
          currentTimestamp: previewKeyAt(state.frames, latest),
        };
      }),
    setLatestTimestamp: (value) =>
      set((state) => ({ latestTimestamp: Math.max(state.latestTimestamp, value) })),
    setScenarioTrajectoryLength: (value) => set({ scenarioTrajectoryLength: value }),
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
    setTrajectoryPreviewFrames: (incoming) =>
      set((state) => {
        if (incoming.length === 0) {
          return state;
        }
        const frames = [...incoming].sort((a, b) => a.timestamp - b.timestamp);
        const first = frames[0]!.timestamp;
        const last = frames[frames.length - 1]!.timestamp;
        const wasEmpty = state.frames.length === 0;
        const hasCurrent = frames.some((f) => f.timestamp === state.currentTimestamp);
        const nextCurrent = hasCurrent ? state.currentTimestamp : first;
        return {
          frames,
          frameIndexByTimestamp: rebuildIndex(frames),
          latestTimestamp: last,
          currentTimestamp: nextCurrent,
          playbackCursor: hasCurrent
            ? Math.min(Math.max(state.playbackCursor, first), last)
            : first,
          hasTrajectoryChunk: true,
          simulationInitializing: false,
          autoFitPending: wasEmpty ? true : state.autoFitPending,
        };
      }),
    clearPreviewFrames: () =>
      set({
        frames: [],
        frameIndexByTimestamp: {},
        hasTrajectoryChunk: false,
        currentTimestamp: 0,
        playbackCursor: 0,
        latestTimestamp: 0,
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
    setSimulationStatus: (status, groundControlPortsByAgentId = {}) =>
      set((state) => ({
        simulationStatus: status,
        groundControlPortsByAgentId,
        // Any concrete status report from the backend ends the local "initializing"
        // spinner state started by beginSimulationInitialization().
        simulationInitializing:
          status === "initializing" ? state.simulationInitializing : false,
      })),
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
        pendingSceneMonitorRequestId: null,
        ...clearedLoadedPlaybackState,
      }),
    beginSceneMonitor: (requestId) => set({ pendingSceneMonitorRequestId: requestId }),
    applySceneMonitorResult: (requestId, frame) =>
      set((state) => {
        const current = state.latestGeneratedScene;
        // A newer scene replaced the one this answer belongs to.
        if (state.pendingSceneMonitorRequestId !== requestId || !current) {
          return {};
        }
        return {
          pendingSceneMonitorRequestId: null,
          latestGeneratedScene: {
            ...current,
            scene: {
              ...current.scene,
              situationContexts: frame.situationContexts,
              colregsStates: frame.colregsStates,
              ruleResults: frame.ruleResults,
              maneuverStates: frame.maneuverStates,
              metrics: frame.metrics,
            },
          },
        };
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
        pendingSceneMonitorRequestId: null,
        completedSceneGenerationRequestId: null,
        ...clearedLoadedPlaybackState,
      }),
    setPlaying: (value) => set({ isPlaying: value }),
    setHoldAtLiveEdge: (value) => set({ holdAtLiveEdge: value }),
    setSpeed: (value) => set({ speed: Math.max(0.1, Math.min(240, value)) }),
    stepBy: (delta) => {
      const state = get();
      state.seek(state.playbackCursor + delta);
    },
    // Seeking and playing cover both streams: a run loaded without its preview, or a simulation
    // that outlasts the preview, plays to its end.
    seek: (timestamp) => {
      const state = get();
      const range = playbackRange(state);
      if (range === null) {
        return;
      }
      const clamped = Math.min(Math.max(timestamp, range.min), range.max);
      set({ followLatestPush: false, currentTimestamp: previewKeyAt(state.frames, clamped), playbackCursor: clamped });
    },
    advancePlayback: (playbackCursor) => {
      set((state) => {
        const range = playbackRange(state);
        if (range === null) {
          return state;
        }
        const clamped = Math.min(Math.max(playbackCursor, range.min), range.max);
        const currentTimestamp = previewKeyAt(state.frames, clamped);
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
  if (options.persistScene) {
    // Persist the last generated/loaded scene so it is restored on a hard refresh. The samples a
    // running generation shows are not written (one per sample, and a reload would restore an
    // unfinished scene): what is shown when it ends is.
    store.subscribe((state, prev) => {
      const generating = state.activeSceneGenerationRequestId !== null;
      const ended = !generating && prev.activeSceneGenerationRequestId !== null;
      if (!generating && (ended || state.latestGeneratedScene !== prev.latestGeneratedScene)) {
        savePersistedScene(state.latestGeneratedScene);
      }
    });
  }
  return store;
}

export type PlaybackStore = ReturnType<typeof createPlaybackStore>;

/** The simulation page's frames and the workbench's gateway session. */
export const usePlaybackStore = createPlaybackStore();
/** The scene generation page's scene, restored after a reload. */
export const useScenePlaybackStore = createPlaybackStore({ persistScene: true });
/** The trajectory generation page's planned trajectories. */
export const useTrajectoryPlaybackStore = createPlaybackStore();

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

