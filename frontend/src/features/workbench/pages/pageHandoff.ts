import type { ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import type { OutputRow } from "../../../domain/cluster/historyApi";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignRow, CampaignStep } from "../../../domain/cluster/schemas";
import { useScenePlaybackStore } from "../../../domain/playback/playbackStore";
import { parseScenarioFile } from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import type { GeneratedSceneData } from "../../../domain/simulation/types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { configRef } from "./entryConfig";
import { fetchArtifact, trajectoryScenarioOf } from "./entryLoader";
import { inputFromPreviousPage, useScenePageStore, useTrajectoryPageStore, type PageInput } from "./pageStore";
import { clearPageOutput } from "./showEntryOutput";

/**
 * Setting a page's input in one click: from the previous page's output, from an output in
 * Campaign History, or from a file. The trajectory page keeps its input scene in the trajectory
 * generation store (it draws it before anything is planned); the simulation page loads its input
 * trajectories into the gateway session and the cluster run (`useSimulationWorkflow`).
 */

export const PREVIOUS_OUTPUT_LABEL = {
  trajectoryGeneration: "The scene of the Scene Generation page",
  simulation: "The trajectories of the Trajectory Generation page",
} as const;

/** The scene the scene page shows, as the trajectory page's input; null when it shows no valid scene. */
export function sceneOfScenePage(sourceName: string | null): { input: PageInput; scene: GeneratedSceneData } | null {
  const shown = useScenePlaybackStore.getState().latestGeneratedScene;
  if (!shown?.valid || !shown.evaluationData) {
    return null;
  }
  const fromEntry = inputFromPreviousPage(useScenePageStore.getState().output);
  const label = sourceName ? `${PREVIOUS_OUTPUT_LABEL.trajectoryGeneration} (${sourceName})` : PREVIOUS_OUTPUT_LABEL.trajectoryGeneration;
  return {
    input: fromEntry ?? { label, origin: "previous_page", ref: null, source: { file: sourceName ?? "scene_generation.json" } },
    scene: { scene: shown.scene, evaluationData: shown.evaluationData, valid: true },
  };
}

/** Whether two inputs are the same artifact on the master; a file or an output not on the master is always new. */
export function sameStoredInput(a: PageInput | null, b: PageInput | null): boolean {
  return a !== null && b !== null && a.ref !== null && b.ref !== null && a.ref.sha256 === b.ref.sha256;
}

/**
 * Sets the trajectory page's input scene and draws it. Trajectories the page showed belong to
 * the scene they were planned from, so another scene replaces them (they stay in Campaign
 * History); the same scene again keeps them. While the page plans, its run owns the canvas.
 */
export function setTrajectoryInput(input: PageInput, scene: GeneratedSceneData): void {
  const generation = useTrajectoryGenerationStore.getState();
  const page = useTrajectoryPageStore.getState();
  const unchanged = sameStoredInput(page.input, input) && generation.handoffScene !== null;
  generation.setHandoffScene(scene, input.origin === "file" ? input.label : null);
  page.setInput(input);
  if (unchanged || generation.status === "running") {
    return;
  }
  // Draws the new input scene in place of the old trajectories.
  clearPageOutput("trajectoryGeneration");
  page.setLocalOutput(null);
}

/** The trajectories the trajectory page shows, as the simulation page's input; null when it shows none usable. */
export function trajectoriesOfTrajectoryPage(): { input: PageInput; content: string } | null {
  const store = useTrajectoryGenerationStore.getState();
  if (!store.resultValid || store.resultScenarioJson === null) {
    return null;
  }
  const fromEntry = inputFromPreviousPage(useTrajectoryPageStore.getState().output);
  return {
    input: fromEntry ?? { label: PREVIOUS_OUTPUT_LABEL.simulation, origin: "previous_page", ref: null, source: { file: "planned_trajectory.json" } },
    content: store.resultScenarioJson,
  };
}

/** Whether an entry ran a step; a campaign from before Phase 6 ran the whole chain. */
export function entryRanStep(row: Pick<CampaignRow, "steps">, step: CampaignStep): boolean {
  return row.steps === undefined || row.steps === null || row.steps.includes(step);
}

/** A history output as a page's input: its artifact and where it came from. */
export function inputOfHistoryOutput(entry: Pick<CampaignRow, "campaign_id" | "name">, row: OutputRow, step: CampaignStep): PageInput | null {
  if (row.artifact === null) {
    return null;
  }
  return {
    label: `${entry.name}, case ${row.case_index + 1}${row.run_index !== null ? `, run ${row.run_index + 1}` : ""}`,
    origin: "history",
    ref: configRef(row.artifact),
    source: { campaign_id: entry.campaign_id, case_id: row.case_id, step },
  };
}

/** A file as a page's input. */
export function inputOfFile(fileName: string): PageInput {
  return { label: fileName, origin: "file", ref: null, source: { file: fileName } };
}

/** A scene document (a file or a history output) as the trajectory page shows it. */
export function sceneOfDocument(document: unknown): GeneratedSceneData {
  const { scene, evaluationData } = parseScenarioFile(JSON.stringify(document));
  return { scene, evaluationData, valid: true };
}

/** A trajectory document (a file or a history output) as the simulation page loads it; null when it holds no trajectories. */
export function trajectoryContentOfDocument(document: unknown): string | null {
  const scenario = trajectoryScenarioOf(document);
  return scenario === null ? null : JSON.stringify(scenario);
}

/**
 * The trajectories of an input stored on the master, read again (after a reload the simulation
 * page keeps only its input's name and artifact); null when the artifact holds no trajectories.
 */
export async function storedTrajectoryContent(
  client: Pick<OperatorClient, "artifactUrl">,
  ref: Pick<ConfigArtifactRef, "sha256">,
  options: { signal?: AbortSignal; fetch?: typeof fetch } = {}
): Promise<string | null> {
  const { document } = await fetchArtifact(client, ref.sha256, options);
  return trajectoryContentOfDocument(document);
}

/**
 * What the simulation page loads again after a reload: nothing while it shows a loaded run (the
 * run's refresh loads its input) or has trajectories; a stored input from the master; a file, which
 * is gone.
 */
export function simulationInputToRestore(
  page: { input: PageInput | null; loaded: unknown },
  hasTrajectories: boolean
): { kind: "none" } | { kind: "file"; input: PageInput } | { kind: "stored"; input: PageInput; ref: ConfigArtifactRef } {
  const { input } = page;
  if (input === null || page.loaded !== null || hasTrajectories) {
    return { kind: "none" };
  }
  return input.ref === null ? { kind: "file", input } : { kind: "stored", input, ref: input.ref };
}
