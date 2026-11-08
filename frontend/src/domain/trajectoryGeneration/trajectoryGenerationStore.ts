import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { GeneratedSceneData } from "../simulation/types";
import type {
  TrajectoryGenerationParamsWire,
  TrajectoryGeneratorWire,
} from "../simulation/wireTypes";

/**
 * Advanced planner parameter defaults. These mirror the class-level constants in
 * `backend/src/concrete_level/trajectory_generation/monitor_guided_planner.py`
 * and `trajectory_generator.py` (TIME_STEP). Leaving a field at its default still
 * sends the value so the run is reproducible from the UI alone.
 */
export const TRAJECTORY_GENERATION_PARAM_DEFAULTS = {
  timeStep: 15,
  timeout: 300,
  maxIterations: 2000,
  directionThreshold: 1,
  bestRandomNodesK: 20,
  previewInterval: 1,
} as const;

export type TrajectoryGenerationParams = {
  [K in keyof typeof TRAJECTORY_GENERATION_PARAM_DEFAULTS]: number;
};

/** The trajectory generator choices, in the order the control lists them. */
export const TRAJECTORY_GENERATORS: { id: TrajectoryGeneratorWire; label: string }[] = [
  { id: "monitor_driven_rrt", label: "Monitor-guided planner" },
  { id: "straight", label: "Straight" },
];

export const DEFAULT_TRAJECTORY_GENERATOR: TrajectoryGeneratorWire = "monitor_driven_rrt";

/** Seconds the straight generator runs every vessel on from its initial state. */
export const DEFAULT_STRAIGHT_TIMESPAN = 3600;

export type TrajectoryGenerationStatus = "idle" | "running" | "done" | "error";

/** Monitor results ride along with every preview by default. */
export const DEFAULT_INCLUDE_MONITOR_RESULTS = true;

/** Fields written to local storage. `migrate` must return this shape. */
type TrajectoryGenerationPersisted = {
  params: TrajectoryGenerationParams;
  includeMonitorResults: boolean;
  generator: TrajectoryGeneratorWire;
  timespan: number;
  handoffScene: GeneratedSceneData | null;
  handoffSourceName: string | null;
  status: TrajectoryGenerationStatus;
  iteration: number;
  resultScenarioJson: string | null;
  resultValid: boolean;
  resultComplete: boolean | null;
  errorMessage: string | null;
};

interface TrajectoryGenerationState {
  /** The trajectory page's input scene: from the Scene Generation page, Campaign History or a file. */
  handoffScene: GeneratedSceneData | null;
  /** Human-readable label for the handoff scene source. */
  handoffSourceName: string | null;
  params: TrajectoryGenerationParams;
  /**
   * Whether the planner attaches its COLREGS monitor output to previews and to the
   * result. Kept apart from `params` because those are all numeric form fields.
   */
  includeMonitorResults: boolean;
  /** Which generator runs: the monitor-guided planner with `params`, or the straight one. */
  generator: TrajectoryGeneratorWire;
  /** Seconds of straight trajectory (the straight generator only). */
  timespan: number;
  status: TrajectoryGenerationStatus;
  activeRequestId: string | null;
  iteration: number;
  /** Full-trajectory scenario JSON of the last result (persisted; drives the preview). */
  resultScenarioJson: string | null;
  resultValid: boolean;
  /**
   * Whether the last result is a complete plan. False is the best partial path of a
   * search that ended without a complete one; null when the backend did not say.
   */
  resultComplete: boolean | null;
  errorMessage: string | null;
  setHandoffScene: (scene: GeneratedSceneData | null, sourceName: string | null) => void;
  setParam: (key: keyof TrajectoryGenerationParams, value: number) => void;
  setIncludeMonitorResults: (value: boolean) => void;
  setGenerator: (generator: TrajectoryGeneratorWire) => void;
  setTimespan: (seconds: number) => void;
  resetParams: () => void;
  startRun: (requestId: string) => void;
  markPreview: (iteration: number) => void;
  markResult: (args: {
    valid: boolean;
    complete?: boolean | null;
    scenarioJson: string | null;
    errorMessage: string | null;
  }) => void;
  markStopped: () => void;
  reset: () => void;
}

export const useTrajectoryGenerationStore = create<TrajectoryGenerationState>()(
  persist(
    (set) => ({
      handoffScene: null,
      handoffSourceName: null,
      params: { ...TRAJECTORY_GENERATION_PARAM_DEFAULTS },
      includeMonitorResults: DEFAULT_INCLUDE_MONITOR_RESULTS,
      generator: DEFAULT_TRAJECTORY_GENERATOR,
      timespan: DEFAULT_STRAIGHT_TIMESPAN,
      status: "idle",
      activeRequestId: null,
      iteration: 0,
      resultScenarioJson: null,
      resultValid: false,
      resultComplete: null,
      errorMessage: null,
      // The page's input; the shown trajectories stay until a run or a loaded entry replaces them (design doc 6.6).
      setHandoffScene: (scene, sourceName) => set({ handoffScene: scene, handoffSourceName: sourceName }),
      setParam: (key, value) =>
        set((state) => ({ params: { ...state.params, [key]: value } })),
      setIncludeMonitorResults: (includeMonitorResults) => set({ includeMonitorResults }),
      setGenerator: (generator) => set({ generator }),
      setTimespan: (timespan) => set({ timespan }),
      resetParams: () =>
        set({
          params: { ...TRAJECTORY_GENERATION_PARAM_DEFAULTS },
          includeMonitorResults: DEFAULT_INCLUDE_MONITOR_RESULTS,
        }),
      startRun: (requestId) =>
        set({
          status: "running",
          activeRequestId: requestId,
          iteration: 0,
          resultScenarioJson: null,
          resultValid: false,
          resultComplete: null,
          errorMessage: null,
        }),
      markPreview: (iteration) => set({ iteration }),
      markResult: ({ valid, complete = null, scenarioJson, errorMessage }) =>
        set({
          status: errorMessage ? "error" : "done",
          activeRequestId: null,
          resultScenarioJson: scenarioJson,
          resultValid: valid,
          resultComplete: complete,
          errorMessage,
        }),
      markStopped: () =>
        set((state) =>
          state.status === "running" ? { status: "idle", activeRequestId: null } : state
        ),
      reset: () =>
        set({
          status: "idle",
          activeRequestId: null,
          iteration: 0,
          resultScenarioJson: null,
          resultValid: false,
          resultComplete: null,
          errorMessage: null,
        }),
    }),
    {
      name: "scenegems:trajectory-generation",
      version: 3,
      // Persist the advanced-parameter form, the handoff scene and
      // the last generated trajectory so the page restores on reload. A run that was
      // still in flight is downgraded to "idle" (there is no live request to resume).
      partialize: (state): TrajectoryGenerationPersisted => ({
        params: state.params,
        includeMonitorResults: state.includeMonitorResults,
        generator: state.generator,
        timespan: state.timespan,
        handoffScene: state.handoffScene,
        handoffSourceName: state.handoffSourceName,
        status: state.status === "running" ? "idle" : state.status,
        iteration: state.iteration,
        resultScenarioJson: state.resultScenarioJson,
        resultValid: state.resultValid,
        resultComplete: state.resultComplete,
        errorMessage: state.status === "running" ? null : state.errorMessage,
      }),
      // A version bump must keep the saved form. Older blobs may omit fields added
      // later; rehydration merges them over the current defaults. Version 3 drops the
      // old search's parameters the planner never read.
      migrate: (persisted): TrajectoryGenerationPersisted => withoutRetiredParams(persisted as TrajectoryGenerationPersisted),
    }
  )
);

/** Keys of the old RRT search that the planner never read; saved forms may still hold them. */
const RETIRED_PARAM_KEYS = ["goalSampleRate", "bestLeafSampleRate", "maxLeafs"];

function withoutRetiredParams(persisted: TrajectoryGenerationPersisted): TrajectoryGenerationPersisted {
  if (!persisted?.params) return persisted;
  const params = Object.fromEntries(
    Object.entries(persisted.params).filter(([key]) => !RETIRED_PARAM_KEYS.includes(key))
  ) as TrajectoryGenerationParams;
  return { ...persisted, params };
}

/**
 * The params of a `generate_trajectories` message. The planner sends all its tuning
 * values; the straight generator needs only the step and the timespan, so nothing else
 * of the search's form leaks into its request.
 */
export function toParamsWire(
  params: TrajectoryGenerationParams,
  includeMonitorResults: boolean = DEFAULT_INCLUDE_MONITOR_RESULTS,
  generator: TrajectoryGeneratorWire = DEFAULT_TRAJECTORY_GENERATOR,
  timespan: number = DEFAULT_STRAIGHT_TIMESPAN
): TrajectoryGenerationParamsWire {
  if (generator === "straight") {
    return { generator, timeStep: params.timeStep, timespan };
  }
  return {
    generator,
    timeStep: params.timeStep,
    timeout: params.timeout,
    maxIterations: params.maxIterations,
    directionThreshold: params.directionThreshold,
    bestRandomNodesK: params.bestRandomNodesK,
    previewInterval: params.previewInterval,
    includeMonitorResults,
  };
}
