import { create } from "zustand";
import type { EvaluationData, GeneratedSceneData, SimulationFrame } from "../simulation/types";
import { hasExceededEvaluationTimeout, evaluationTimeBaseline } from "./evaluationTime";
import { createEvaluationTimeWatcher } from "./evaluationTimeWait";

export interface BatchRunResult {
  presetPath: string;
  label: string;
  requestId: string;
  status: "pending" | "running" | "success" | "error" | "timeout" | "cancelled";
  message?: string;
  evaluationData?: EvaluationData;
  evaluationTimeBaseline?: number;
  scene?: SimulationFrame;
}

const TERMINAL_STATUSES: BatchRunResult["status"][] = [
  "success",
  "error",
  "timeout",
  "cancelled",
];

interface BatchGenerationState {
  results: BatchRunResult[];
  selectedPaths: string[];
  running: boolean;
  batchTimeoutSeconds: number | null;
  batchRequestIds: Set<string>;
  setResults: (updater: BatchRunResult[] | ((prev: BatchRunResult[]) => BatchRunResult[])) => void;
  setSelectedPaths: (paths: string[]) => void;
  toggleSelectedPath: (path: string) => void;
  selectAllPaths: (paths: string[]) => void;
  clearSelectedPaths: () => void;
  setRunning: (running: boolean) => void;
  setBatchTimeoutSeconds: (seconds: number | null) => void;
  clearResults: () => void;
  registerBatchRequestIds: (requestIds: string[]) => void;
  clearBatchRequestIds: () => void;
  isBatchRequest: (requestId: string) => boolean;
  handleBatchGeneratedScene: (requestId: string, scene: GeneratedSceneData) => void;
  markAllBatchStopped: () => void;
}

export const useBatchGenerationStore = create<BatchGenerationState>((set, get) => ({
  results: [],
  selectedPaths: [],
  running: false,
  batchTimeoutSeconds: null,
  batchRequestIds: new Set(),
  setResults: (updater) =>
    set((state) => ({
      results: typeof updater === "function" ? updater(state.results) : updater,
    })),
  setSelectedPaths: (paths) => set({ selectedPaths: paths }),
  toggleSelectedPath: (path) =>
    set((state) => {
      const selected = new Set(state.selectedPaths);
      if (selected.has(path)) selected.delete(path);
      else selected.add(path);
      return { selectedPaths: Array.from(selected) };
    }),
  selectAllPaths: (paths) => set({ selectedPaths: paths }),
  clearSelectedPaths: () => set({ selectedPaths: [] }),
  setRunning: (running) => set({ running }),
  setBatchTimeoutSeconds: (seconds) => set({ batchTimeoutSeconds: seconds }),
  clearResults: () => set({ results: [], batchRequestIds: new Set(), batchTimeoutSeconds: null }),
  registerBatchRequestIds: (requestIds) =>
    set({ batchRequestIds: new Set(requestIds) }),
  clearBatchRequestIds: () => set({ batchRequestIds: new Set() }),
  isBatchRequest: (requestId) => get().batchRequestIds.has(requestId),
  handleBatchGeneratedScene: (requestId, scene) =>
    set((state) => ({
      results: state.results.map((r) => {
        if (r.requestId !== requestId) return r;
        if (r.status === "cancelled" || r.status === "timeout") return r;

        if (scene.valid && scene.evaluationData) {
          return {
            ...r,
            status: "success",
            evaluationData: scene.evaluationData,
            scene: scene.scene,
            message: undefined,
          };
        }

        if (r.status === "success") return r;

        const evaluationData = scene.evaluationData ?? r.evaluationData;
        const baseline =
          r.evaluationTimeBaseline ??
          evaluationTimeBaseline(scene.evaluationData ?? r.evaluationData);
        const updated: BatchRunResult = {
          ...r,
          status: r.status === "pending" ? "running" : r.status,
          evaluationTimeBaseline: baseline,
          ...(scene.evaluationData ? { evaluationData: scene.evaluationData } : {}),
          ...(scene.scene ? { scene: scene.scene } : {}),
        };

        if (
          state.batchTimeoutSeconds !== null &&
          evaluationData &&
          hasExceededEvaluationTimeout(
            evaluationData,
            state.batchTimeoutSeconds,
            baseline
          )
        ) {
          return { ...updated, status: "timeout", message: undefined };
        }

        return updated;
      }),
    })),
  markAllBatchStopped: () =>
    set((state) => ({
      running: false,
      results: state.results.map((r) =>
        r.status === "pending" || r.status === "running"
          ? { ...r, status: "cancelled", message: "Stopped" }
          : r
      ),
    })),
}));

export function waitForBatchRequestResult(
  requestId: string,
  timeoutSeconds: number,
  isAborted: () => boolean
): Promise<void> {
  return new Promise((resolve) => {
    const getResult = () =>
      useBatchGenerationStore.getState().results.find((r) => r.requestId === requestId);

    const watcher = createEvaluationTimeWatcher({
      timeoutSeconds,
      isAborted,
      getEvaluationData: () => getResult()?.evaluationData,
      getBaselineSeconds: () => getResult()?.evaluationTimeBaseline ?? 0,
      isTerminal: () => {
        const result = getResult();
        return !!result && TERMINAL_STATUSES.includes(result.status);
      },
      onTimedOut: () => {
        useBatchGenerationStore.getState().setResults((prev) =>
          prev.map((r) =>
            r.requestId === requestId && (r.status === "pending" || r.status === "running")
              ? { ...r, status: "timeout", message: undefined }
              : r
          )
        );
      },
      onComplete: () => {
        clearTimeout(hardTimer);
        unsubscribe();
        resolve();
      },
    });

    const unsubscribe = useBatchGenerationStore.subscribe(() => {
      watcher.evaluate();
    });

    // Wall-clock safety net: the evaluation-time watcher only trips while the
    // backend keeps streaming progress for this request. If it never does, force
    // a timeout so runBatchGeneration's Promise.all cannot hang indefinitely.
    // Assigned before the final evaluate() below, so onComplete can always clear it.
    const hardTimer = setTimeout(
      () => {
        useBatchGenerationStore.getState().setResults((prev) =>
          prev.map((r) =>
            r.requestId === requestId && (r.status === "pending" || r.status === "running")
              ? { ...r, status: "timeout", message: undefined }
              : r
          )
        );
        watcher.evaluate();
      },
      Math.max(1, timeoutSeconds + 30) * 1000
    );

    watcher.evaluate();
  });
}
