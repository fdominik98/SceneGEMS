import { usePlaybackStore } from "./playbackStore";
import type { GeneratedSceneData } from "../simulation/types";
import { createEvaluationTimeWatcher } from "../sceneGeneration/evaluationTimeWait";

export interface SceneGenerationWaitResult {
  ok: boolean;
  message?: string;
  scene?: GeneratedSceneData;
  /** Set when a newer generation superseded this wait; do not surface as an error. */
  superseded?: boolean;
}

export function waitForSceneGeneration(
  requestId: string,
  timeoutSeconds: number
): Promise<SceneGenerationWaitResult> {
  return new Promise((resolve) => {
    let timedOut = false;
    let settled = false;
    const waitEpoch = usePlaybackStore.getState().sceneGenerationWaitEpoch;

    const settle = (result: SceneGenerationWaitResult) => {
      if (settled) {
        return;
      }
      settled = true;
      watcher.cleanup();
      unsubscribe();
      resolve(result);
    };

    const isSuperseded = () =>
      usePlaybackStore.getState().sceneGenerationWaitEpoch !== waitEpoch;

    const watcher = createEvaluationTimeWatcher({
      timeoutSeconds,
      isAborted: () => isSuperseded(),
      getEvaluationData: () =>
        usePlaybackStore.getState().sceneGenerationEvaluationByRequestId[requestId],
      getBaselineSeconds: () =>
        usePlaybackStore.getState().sceneGenerationEvaluationBaselineByRequestId[requestId] ?? 0,
      isTerminal: () => {
        if (isSuperseded()) {
          return true;
        }
        const state = usePlaybackStore.getState();
        if (state.errorMessage) {
          return true;
        }
        if (state.completedSceneGenerationRequestId === requestId) {
          return true;
        }
        if (
          state.activeSceneGenerationRequestId === null &&
          state.completedSceneGenerationRequestId !== requestId
        ) {
          return true;
        }
        return timedOut;
      },
      onTimedOut: () => {
        timedOut = true;
      },
      onComplete: () => {
        if (isSuperseded()) {
          settle({ ok: false, superseded: true });
          return;
        }

        const state = usePlaybackStore.getState();

        if (state.completedSceneGenerationRequestId === requestId) {
          const scene = state.latestGeneratedScene;
          if (!scene?.valid) {
            settle({
              ok: false,
              message: "Scene generation completed without a valid scene.",
            });
            return;
          }
          settle({ ok: true, scene });
          return;
        }

        if (state.errorMessage) {
          settle({ ok: false, message: state.errorMessage });
          return;
        }

        if (timedOut) {
          settle({ ok: false, message: "Scene generation timed out." });
          return;
        }

        settle({ ok: false, message: "Scene generation stopped." });
      },
    });

    const unsubscribe = usePlaybackStore.subscribe(() => {
      if (isSuperseded()) {
        settle({ ok: false, superseded: true });
        return;
      }

      const state = usePlaybackStore.getState();
      if (state.errorMessage) {
        settle({ ok: false, message: state.errorMessage });
        return;
      }

      watcher.evaluate();
    });

    watcher.evaluate();
  });
}
