import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import type { LoadedScene, LoadedTrajectories } from "./entryLoader";
import { PAGE_STORES } from "./pageStore";
import type { WorkbenchPage, WorkbenchTarget } from "./workbenchTarget";

/**
 * Puts a loaded entry's output on its page: into the page's playback store (each page renders
 * its own frames), and the target into the page store as the latest loaded entry.
 */

/** A scene with the monitor's judgment of it (the first monitored frame of a one-scene log). */
export function withMonitorFields(scene: SimulationFrame, monitored: SimulationFrame | null): SimulationFrame {
  if (monitored === null) {
    return scene;
  }
  return {
    ...scene,
    situationContexts: monitored.situationContexts,
    colregsStates: monitored.colregsStates,
    ruleResults: monitored.ruleResults,
    maneuverStates: monitored.maneuverStates,
    metrics: monitored.metrics,
  };
}

export function showLoadedScene(target: WorkbenchTarget, loaded: LoadedScene): void {
  useScenePlaybackStore.getState().setVisualizedScenario({
    scene: withMonitorFields(loaded.scene, loaded.monitorFrame),
    evaluationData: loaded.evaluationData,
    valid: loaded.valid,
  });
  PAGE_STORES.sceneGeneration.getState().setLoaded({ ...target, caseIndex: loaded.caseIndex }, loaded.valid ? loaded.output : null);
}

export function showLoadedTrajectories(target: WorkbenchTarget, loaded: LoadedTrajectories): void {
  const playback = useTrajectoryPlaybackStore.getState();
  playback.clearPreviewFrames();
  playback.setTrajectoryPreviewFrames(loaded.frames);
  useTrajectoryGenerationStore.getState().markResult({
    valid: loaded.valid,
    complete: loaded.complete,
    scenarioJson: loaded.valid ? JSON.stringify(loaded.trajectoryData) : null,
    errorMessage: null,
  });
  PAGE_STORES.trajectoryGeneration.getState().setLoaded({ ...target, caseIndex: loaded.caseIndex }, loaded.valid ? loaded.output : null);
}

/** Drops what a page shows of its loaded entry; its input stays. */
export function clearPageOutput(page: WorkbenchPage): void {
  switch (page) {
    case "sceneGeneration":
      useScenePlaybackStore.getState().clearVisualizedScenario();
      return;
    case "trajectoryGeneration": {
      const playback = useTrajectoryPlaybackStore.getState();
      const generation = useTrajectoryGenerationStore.getState();
      playback.clearPreviewFrames();
      generation.reset();
      // The input scene stays the page's picture until trajectories are planned from it.
      if (generation.handoffScene) {
        playback.setTrajectoryPreviewFrames([generation.handoffScene.scene]);
      }
      return;
    }
    case "simulation":
      usePlaybackStore.getState().clearSimulationTrajectories();
  }
}
