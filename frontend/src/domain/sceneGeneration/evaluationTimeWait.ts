import type { EvaluationData } from "../simulation/types";
import { hasExceededEvaluationTimeout } from "./evaluationTime";

export interface EvaluationTimeWatcherOptions {
  timeoutSeconds: number;
  isAborted: () => boolean;
  getEvaluationData: () => EvaluationData | undefined | null;
  getBaselineSeconds?: () => number;
  isTerminal: () => boolean;
  onTimedOut: () => void;
  onComplete: () => void;
}

export interface EvaluationTimeWatcher {
  evaluate: () => void;
  cleanup: () => void;
}

/** Tracks scene-generation timeout using `evaluation_time` from evaluation data only. */
export function createEvaluationTimeWatcher(
  options: EvaluationTimeWatcherOptions
): EvaluationTimeWatcher {
  let completed = false;

  const finish = () => {
    if (completed) {
      return;
    }
    completed = true;
    options.onComplete();
  };

  const evaluate = () => {
    if (completed) {
      return;
    }
    if (options.isAborted() || options.isTerminal()) {
      finish();
      return;
    }

    if (
      hasExceededEvaluationTimeout(
        options.getEvaluationData(),
        options.timeoutSeconds,
        options.getBaselineSeconds?.() ?? 0
      )
    ) {
      options.onTimedOut();
      finish();
    }
  };

  return {
    evaluate,
    cleanup: finish,
  };
}
