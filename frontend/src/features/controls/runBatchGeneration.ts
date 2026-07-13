import { formatFunctionalPresetLabel } from "./functionalPresetPaths";
import { loadFunctionalPresetsManifest } from "./functionalPresets";
import {
  useBatchGenerationStore,
  waitForBatchRequestResult,
  type BatchRunResult,
} from "../../domain/sceneGeneration/batchGenerationStore";

export interface RunBatchGenerationParams {
  selectedPaths: string[];
  loadPresetText: (path: string) => Promise<string>;
  enqueueSceneGeneration: (requestId: string, specText: string) => void;
  sceneGenerationTimeoutSeconds: number;
  /** Returns true if generation has been stopped externally (e.g. shared Stop button). */
  isAborted: () => boolean;
}

/**
 * Queues all selected presets for parallel scene generation with a per-scene timeout.
 * Drives the shared batch-generation store so the batch tab reflects progress.
 */
export async function runBatchGeneration({
  selectedPaths,
  loadPresetText,
  enqueueSceneGeneration,
  sceneGenerationTimeoutSeconds,
  isAborted,
}: RunBatchGenerationParams): Promise<void> {
  if (selectedPaths.length === 0) {
    return;
  }
  const paths = [...selectedPaths];
  useBatchGenerationStore.getState().setRunning(true);

  try {
    const labelByPath = new Map<string, string>();
    try {
      const manifest = await loadFunctionalPresetsManifest();
      for (const preset of manifest.presets) {
        labelByPath.set(preset.path, preset.label);
      }
    } catch {
      // Fall back to path-derived labels.
    }

    const jobs = await Promise.all(
      paths.map(async (path) => ({
        presetPath: path,
        label: labelByPath.get(path) ?? formatFunctionalPresetLabel(path),
        requestId: crypto.randomUUID(),
        specText: await loadPresetText(path),
      }))
    );

    const initial: BatchRunResult[] = jobs.map((job) => ({
      presetPath: job.presetPath,
      label: job.label,
      requestId: job.requestId,
      status: "pending",
    }));
    useBatchGenerationStore.getState().setResults(initial);
    useBatchGenerationStore.getState().registerBatchRequestIds(jobs.map((j) => j.requestId));
    useBatchGenerationStore.getState().setBatchTimeoutSeconds(sceneGenerationTimeoutSeconds);

    if (isAborted()) {
      useBatchGenerationStore.getState().markAllBatchStopped();
      return;
    }

    for (const job of jobs) {
      enqueueSceneGeneration(job.requestId, job.specText);
    }

    await Promise.all(
      jobs.map((job) =>
        waitForBatchRequestResult(job.requestId, sceneGenerationTimeoutSeconds, isAborted)
      )
    );
  } catch (error) {
    useBatchGenerationStore.getState().setResults((prev) =>
      prev.map((r) =>
        r.status === "pending" || r.status === "running"
          ? {
              ...r,
              status: "error",
              message: error instanceof Error ? error.message : "Batch failed",
            }
          : r
      )
    );
  } finally {
    useBatchGenerationStore.getState().clearBatchRequestIds();
    useBatchGenerationStore.getState().setBatchTimeoutSeconds(null);
    useBatchGenerationStore.getState().setRunning(false);
  }
}
