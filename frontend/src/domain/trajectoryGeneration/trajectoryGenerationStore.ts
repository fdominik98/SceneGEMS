import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { GeneratedSceneData } from "../simulation/types";
import type { TrajectoryGenerationParamsWire } from "../simulation/wireTypes";

/**
 * Advanced RRT parameter defaults. These mirror the class-level constants in
 * `backend/src/concrete_level/trajectory_generation/monitor_driven_rrt_search.py`
 * and `trajectory_generator.py` (TIME_STEP). Leaving a field at its default still
 * sends the value so the run is reproducible from the UI alone.
 */
export const TRAJECTORY_GENERATION_PARAM_DEFAULTS = {
  timeStep: 15,
  timeout: 300,
  maxIterations: 2000,
  goalSampleRate: 50,
  bestLeafSampleRate: 90,
  maxLeafs: 500,
  directionThreshold: 1,
  bestRandomNodesK: 20,
  previewInterval: 1,
} as const;

export type TrajectoryGenerationParams = {
  [K in keyof typeof TRAJECTORY_GENERATION_PARAM_DEFAULTS]: number;
};

export type TrajectoryGenerationStatus = "idle" | "running" | "done" | "error";

interface TrajectoryGenerationState {
  /** Initial scene handed over from the Scene Generation page (or loaded here). */
  handoffScene: GeneratedSceneData | null;
  /** Human-readable label for the handoff scene source. */
  handoffSourceName: string | null;
  params: TrajectoryGenerationParams;
  status: TrajectoryGenerationStatus;
  activeRequestId: string | null;
  iteration: number;
  /** Full-trajectory scenario JSON of the final result (for "Load for Simulation"). */
  resultScenarioJson: string | null;
  resultValid: boolean;
  errorMessage: string | null;
  setHandoffScene: (scene: GeneratedSceneData | null, sourceName: string | null) => void;
  setParam: (key: keyof TrajectoryGenerationParams, value: number) => void;
  resetParams: () => void;
  startRun: (requestId: string) => void;
  markPreview: (iteration: number) => void;
  markResult: (args: {
    valid: boolean;
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
      status: "idle",
      activeRequestId: null,
      iteration: 0,
      resultScenarioJson: null,
      resultValid: false,
      errorMessage: null,
      setHandoffScene: (scene, sourceName) =>
        set({
          handoffScene: scene,
          handoffSourceName: sourceName,
          status: "idle",
          activeRequestId: null,
          iteration: 0,
          resultScenarioJson: null,
          resultValid: false,
          errorMessage: null,
        }),
      setParam: (key, value) =>
        set((state) => ({ params: { ...state.params, [key]: value } })),
      resetParams: () => set({ params: { ...TRAJECTORY_GENERATION_PARAM_DEFAULTS } }),
      startRun: (requestId) =>
        set({
          status: "running",
          activeRequestId: requestId,
          iteration: 0,
          resultScenarioJson: null,
          resultValid: false,
          errorMessage: null,
        }),
      markPreview: (iteration) => set({ iteration }),
      markResult: ({ valid, scenarioJson, errorMessage }) =>
        set({
          status: errorMessage ? "error" : "done",
          activeRequestId: null,
          resultScenarioJson: scenarioJson,
          resultValid: valid,
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
          errorMessage: null,
        }),
    }),
    {
      name: "scenegems:trajectory-generation",
      version: 1,
      // Persist only the advanced parameter form; run state is transient.
      partialize: (state) => ({ params: state.params }),
    }
  )
);

export function toParamsWire(
  params: TrajectoryGenerationParams
): TrajectoryGenerationParamsWire {
  return {
    timeStep: params.timeStep,
    timeout: params.timeout,
    maxIterations: params.maxIterations,
    goalSampleRate: params.goalSampleRate,
    bestLeafSampleRate: params.bestLeafSampleRate,
    maxLeafs: params.maxLeafs,
    directionThreshold: params.directionThreshold,
    bestRandomNodesK: params.bestRandomNodesK,
    previewInterval: params.previewInterval,
  };
}
