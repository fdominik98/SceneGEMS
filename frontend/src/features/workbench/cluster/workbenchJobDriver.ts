import { followJob, jobFailureMessage, readResultField, type JobProgressEvent } from "../../../domain/cluster/clusterJobs";
import { createCampaign } from "../../../domain/cluster/campaignApi";
import { instanceTopic, jobInstanceName } from "../../../domain/cluster/liveProtocol";
import { INSTANCE_FRAMES_KEPT, instanceReducer, type InstanceTopicState, type SceneSample, type TrajectoryPreview } from "../../../domain/cluster/liveTopics";
import { LiveTopicWatcher } from "../../../domain/cluster/liveTopicWatcher";
import type { JobSubmission } from "../../../domain/cluster/operatorApi";
import type { CampaignOrigin, JobView } from "../../../domain/cluster/schemas";
import { FrameBuffer } from "../../../domain/cluster/observeFrames";
import { useClusterRunStore } from "./clusterRunStore";

import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../../../domain/playback/playbackStore";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { isFullTrajectoryScenario, parseScenarioFile } from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import { parseFrame, type ParsedServerMessage } from "../../../domain/simulation/protocol";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import type { TrajectoryGenerationParamsWire } from "../../../domain/simulation/wireTypes";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { useUiStore } from "../../../app/uiStore";
import {
  entryName,
  scenarioClassId,
  scenarioInputName,
  sceneEntryConfig,
  simulationEntryConfig,
  toConfigYaml,
  trajectoryEntryConfig,
  WORKBENCH_ORIGIN,
} from "../pages/entryConfig";
import { takeEntrySeed } from "../pages/entrySeedStore";
import { caseEndMessage, createCaseWaiter, isGone, pollCase, waitForCase, waitForCaseEnd, waitForStageJob, type EntryFollowOptions } from "../pages/entryFollower";
import { framesOfRun, loadEntryOutput, type LoadedOutput, type LoadedRun } from "../pages/entryLoader";
import { resolveInputItem, uploadedRef } from "../pages/pageInputs";
import { PAGE_STORES, type PageInput } from "../pages/pageStore";
import { clearPageOutput, showLoadedScene, showLoadedTrajectories } from "../pages/showEntryOutput";
import type { WorkbenchPage, WorkbenchTarget } from "../pages/workbenchTarget";
import type { ReferenceGeofence } from "../connection/referenceGeofence";
import type { ClusterRunPlan } from "./simulationJobs";
import type { JobTypeResources } from "./workbenchResources";
import {
  MONITORING_JOB,
  monitoredFrames,
  monitoringSubmission,
  poolRequestId,
  runClusterJob,
  SCENE_GENERATION_JOB,
  sceneJobResult,
  singleSceneTrajectories,
  TRAJECTORY_GENERATION_JOB,
  trajectoryJobResult,
  watchPoolPreviews,
  type PoolKind,
  type SceneGenerationInput,
  type WorkbenchCluster,
} from "./workbenchJobs";

/**
 * Runs the workbench on the active cluster. Every scene generation (single or batch), trajectory
 * generation and kinematic simulation is a one-step workbench entry (design doc 6.3): the driver
 * creates it through the campaign create route, follows the entry's case and its jobs as the
 * engine submits them, and reports them through the messages the workbench's stores understand
 * (`generated_scene`, `trajectory_generation_preview`, `trajectory_generation_result`), so the
 * pages read the same state whether a job is queued, running or done. When the case ended, the
 * page loads the entry's output like any target from Campaign History. A simulation is an entry
 * whether it runs on the kinematic layer or on ArduPilot SITL or Gazebo (P6.6); a run with no page
 * input and the monitoring of scenes and trajectories loaded from files stay direct jobs.
 */

export interface ClusterAccess {
  cluster: WorkbenchCluster | null;
  resources: (jobType: string) => JobTypeResources;
}

export type SceneJobOutcome =
  | {
      ok: true;
      valid: boolean;
      scene: SimulationFrame;
      /** The scene's metadata as the workbench keeps it (without the scene). */
      evaluationData: EvaluationData;
      /** The job's EvaluationData as a scenario file holds it, with `best_scene`. */
      scenario: Record<string, unknown>;
    }
  | { ok: false; message: string; stopped: boolean };

/** A scene to generate: the functional scenario and what the page calls it. */
export interface SceneEntryRequest extends SceneGenerationInput {
  label: string;
}

export interface BatchSceneRow {
  requestId: string;
  label: string;
  functionalScenarioContent: string;
}

export interface TrajectoryEntryRequest {
  input: PageInput;
  /** The input scene as a scenario file holds it, uploaded when the input is not on the master. */
  scenarioContent: string | null;
  colregsConstraintsContent: string;
  params: TrajectoryGenerationParamsWire;
}

export interface SimulationEntryRequest {
  input: PageInput;
  /** The input trajectories as a full scenario file, uploaded when the input is not on the master. */
  scenarioContent: string | null;
  colregsConstraintsContent: string;
  /** The reference area an ArduPilot run places the local frame with (the Connections page's). */
  geofence?: ReferenceGeofence;
}

/** What the driver needs of the workbench to show a loaded run: its input loaded for a run again, and its frames replayed. */
export interface SimulationPageHooks {
  /** Loads trajectories on the simulation page (the gateway's scenario and the cluster's input); resolves once loaded. */
  loadSimulationInput: (scenarioContent: string, fileName: string, replayFrames: SimulationFrame[]) => Promise<void>;
  /** Fills the setup from a loaded run's stack and environment. */
  fillSetup: (run: LoadedRun) => void;
}

const STOPPED_MESSAGE = "Scene generation stopped.";

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const NO_CLUSTER: ClusterAccess = {
  cluster: null,
  resources: (jobType) => ({ jobType, nodes: 0, slots: 0, freeSlots: 0, blocker: "No cluster is selected." }),
};

const NO_HOOKS: SimulationPageHooks = {
  loadSimulationInput: async () => undefined,
  fillSetup: () => undefined,
};

/**
 * A run or a follow of one page: aborting it stops following, and stops the entry when the page
 * created it. The user's Stop also stops a followed workbench entry (a campaign is only left).
 */
interface PageTask {
  controller: AbortController;
  entryId: string | null;
  ownEntry: boolean;
  /** A followed entry of kind workbench, which the page's Stop stops too. */
  workbenchEntry: boolean;
}

export class WorkbenchJobDriver {
  private access: () => ClusterAccess;
  private dispatch: (message: ParsedServerMessage) => void;
  private hooks: SimulationPageHooks = NO_HOOKS;
  private readonly sceneJobs = new Map<string, PageTask>();
  private trajectoryJob: PageTask | null = null;
  private previewMonitorJob: AbortController | null = null;
  private simulationJob: PageTask | null = null;
  private simulationWatcher: LiveTopicWatcher<InstanceTopicState> | null = null;
  private readonly loads = new Map<WorkbenchPage, AbortController>();
  /** Between two polls of an entry's case; tests make it short. */
  pollMs = 1000;
  /** Between two polls of a followed job without its live topic (`followJob` default when undefined); tests make it short. */
  jobPollMs: number | undefined = undefined;

  constructor(access: () => ClusterAccess = () => NO_CLUSTER, dispatch: (message: ParsedServerMessage) => void = () => undefined) {
    this.access = access;
    this.dispatch = dispatch;
  }

  /** The cluster jobs go to from now on (the active cluster as the workbench sees it). */
  setCluster(access: ClusterAccess): void {
    this.access = () => access;
  }

  /** Where job reports go from now on. */
  setDispatch(dispatch: (message: ParsedServerMessage) => void): void {
    this.dispatch = dispatch;
  }

  setSimulationHooks(hooks: SimulationPageHooks): void {
    this.hooks = hooks;
  }

  /** Why the active cluster cannot run a job type now, null when it can. */
  blocker(jobType: string): string | null {
    const { cluster, resources } = this.access();
    return cluster === null ? resources(jobType).blocker ?? "No cluster is selected." : resources(jobType).blocker;
  }

  /** The step monitor of an entry: post-hoc when a node monitors, else none, so the case does not wait for a job no node takes. */
  private stepMonitor(): "post_hoc" | "empty" {
    return this.blocker(MONITORING_JOB) === null ? "post_hoc" : "empty";
  }

  private follow(signal: AbortSignal): EntryFollowOptions {
    return { signal, pollMs: this.pollMs };
  }

  private async createEntry(cluster: WorkbenchCluster, yaml: string, name: string, origin: CampaignOrigin, task: PageTask): Promise<string> {
    const entry = await createCampaign(cluster.client, yaml, { name, start: true, kind: "workbench", origin });
    task.entryId = entry.campaign_id;
    if (task.controller.signal.aborted) {
      this.stopEntry(task);
    }
    return entry.campaign_id;
  }

  /** Stops the entry a page created (or, on the user's Stop, a followed workbench entry); the engine cancels its jobs. */
  private stopEntry(task: PageTask, byUser = false): void {
    const cluster = this.access().cluster;
    if (cluster !== null && task.entryId !== null && (task.ownEntry || (byUser && task.workbenchEntry))) {
      void cluster.client.controlCampaign(task.entryId, "stop").catch(() => undefined);
    }
  }

  private abortTask(task: PageTask | null, byUser = false): void {
    if (task === null) {
      return;
    }
    task.controller.abort();
    this.stopEntry(task, byUser);
  }

  private newTask(ownEntry: boolean, entryId: string | null = null): PageTask {
    return { controller: new AbortController(), entryId, ownEntry, workbenchEntry: false };
  }

  // Scene generation

  /** One scene as a workbench entry, shown on the scene page as it arrives; resolves with its outcome once generated (the monitor follows). */
  async generateScene(requestId: string, input: SceneEntryRequest): Promise<SceneJobOutcome> {
    useScenePlaybackStore.getState().setActiveSceneGenerationRequestId(requestId);
    const outcome = await this.runSceneEntry(requestId, input);
    if (useScenePlaybackStore.getState().activeSceneGenerationRequestId === requestId) {
      useScenePlaybackStore.getState().setActiveSceneGenerationRequestId(null);
    }
    return outcome;
  }

  private async runSceneEntry(requestId: string, input: SceneEntryRequest): Promise<SceneJobOutcome> {
    const blocker = this.blocker(SCENE_GENERATION_JOB);
    const cluster = this.access().cluster;
    if (blocker !== null || cluster === null) {
      return { ok: false, message: blocker ?? "No cluster is selected.", stopped: false };
    }
    const task = this.newTask(true);
    this.sceneJobs.set(requestId, task);
    const page = PAGE_STORES.sceneGeneration.getState();
    page.setStatus("running", "Creating the workbench entry...", null);
    try {
      const signal = task.controller.signal;
      const ref = await uploadedRef(cluster.client, input.functionalScenarioContent, "functional_scenario", "text/plain", signal);
      const name = scenarioInputName(input.label);
      const config = sceneEntryConfig({
        name: entryName("Scene generation", input.label),
        scenarios: [{ name, ref }],
        domain: input,
        timeoutSeconds: input.timeoutSeconds,
        enforceLowTcpa: input.enforceLowTcpa,
        seed: takeEntrySeed(),
        monitor: this.stepMonitor(),
      });
      const entryId = await this.createEntry(cluster, toConfigYaml(config), config.name, WORKBENCH_ORIGIN.sceneGeneration, task);
      PAGE_STORES.sceneGeneration.getState().setStatus("running", "Waiting for the entry's scene generation job...", entryId);
      const caseView = await waitForCase(cluster.client, entryId, scenarioClassId(name), this.follow(signal));
      return await this.followSceneCase(cluster, requestId, { campaignId: entryId, caseId: caseView.case_id }, task, false);
    } catch (error) {
      return this.sceneFailure(error, task);
    } finally {
      if (this.sceneJobs.get(requestId) === task) {
        this.sceneJobs.delete(requestId);
      }
    }
  }

  private sceneFailure(error: unknown, task: PageTask): SceneJobOutcome {
    const stopped = isAbort(error) || task.controller.signal.aborted;
    const message = stopped ? STOPPED_MESSAGE : `Scene generation on the cluster failed: ${describe(error)}`;
    const page = PAGE_STORES.sceneGeneration.getState();
    if (page.activeEntryId === task.entryId || page.activeEntryId === null) {
      page.setStatus(stopped ? "idle" : "failed", stopped ? null : message, null);
    }
    return { ok: false, message, stopped };
  }

  /**
   * Follows the scene generation of an entry's case: previews while its job runs, the scene once
   * it succeeded, then (not in a batch) the monitored scene loaded from the entry.
   */
  private async followSceneCase(
    cluster: WorkbenchCluster,
    requestId: string,
    entry: { campaignId: string; caseId: number },
    task: PageTask,
    batch: boolean
  ): Promise<SceneJobOutcome> {
    const signal = task.controller.signal;
    const { jobId, detail } = await waitForStageJob(cluster.client, entry.campaignId, entry.caseId, "generate_scene", this.follow(signal));
    if (jobId === null) {
      return { ok: false, message: caseEndMessage(detail), stopped: detail.state === "cancelled" };
    }
    const previews = new PreviewFollower(cluster, "scene_generation", (preview) => this.dispatchSample(requestId, preview as SceneSample));
    let job: JobView;
    try {
      job = await followJob(cluster.client, jobId, {
        pollIntervalMs: this.jobPollMs,
        channel: cluster.channel,
        signal,
        onProgress: (event) => {
          if (batch) {
            useBatchGenerationStore.getState().setBatchRequestStatus(requestId, event.job.state === "running" ? "running" : "pending");
          }
          previews.follow(event, useUiStore.getState().sceneGenerationLivePreview);
        },
      });
    } finally {
      previews.stop();
    }
    if (job.state !== "succeeded") {
      return { ok: false, message: jobFailureMessage(job), stopped: job.state === "cancelled" };
    }
    const result = await sceneJobResult(cluster, job, signal);
    const parsed = parseScenarioFile(JSON.stringify(result.evaluationData));
    this.dispatch({ kind: "generated_scene", requestId, valid: result.valid, scene: parsed.scene, evaluationData: parsed.evaluationData });
    const target = { page: "sceneGeneration", campaignId: entry.campaignId, caseId: entry.caseId, step: "scene_generation" } as const;
    if (batch) {
      useBatchGenerationStore.getState().setBatchRequestTarget(requestId, target);
    } else {
      void this.finishEntry(target, task, "Monitoring the scene on the cluster...");
    }
    return { ok: true, valid: result.valid, scene: parsed.scene, evaluationData: parsed.evaluationData, scenario: result.evaluationData };
  }

  /**
   * After the step's output: waits for the case to end (its monitor job) and loads the entry's
   * output on the page, which then shows the latest loaded entry.
   */
  private async finishEntry(target: WorkbenchTarget, task: PageTask, message: string): Promise<void> {
    const cluster = this.access().cluster;
    if (cluster === null) {
      return;
    }
    const page = PAGE_STORES[target.page];
    page.getState().setStatus("running", message, target.campaignId);
    try {
      await waitForCaseEnd(cluster.client, target.campaignId, target.caseId, this.follow(task.controller.signal));
      await this.loadTarget(target, { quiet: true });
    } catch (error) {
      if (!isAbort(error) && page.getState().activeEntryId === target.campaignId) {
        page.getState().setStatus("failed", `The entry's output could not be loaded: ${describe(error)}`, null);
      }
    }
  }

  /** Every selected scenario as one batch entry with a case per scenario; each row follows its case. Resolves once every row ended. */
  async generateBatch(rows: BatchSceneRow[], input: Omit<SceneGenerationInput, "functionalScenarioContent">): Promise<void> {
    const batch = useBatchGenerationStore.getState();
    const blocker = this.blocker(SCENE_GENERATION_JOB);
    const cluster = this.access().cluster;
    if (blocker !== null || cluster === null) {
      for (const row of rows) {
        batch.setBatchRequestStatus(row.requestId, "error", blocker ?? "No cluster is selected.");
      }
      return;
    }
    const task = this.newTask(true);
    for (const row of rows) {
      this.sceneJobs.set(row.requestId, task);
    }
    const signal = task.controller.signal;
    try {
      const taken = new Set<string>();
      const scenarios = await Promise.all(
        rows.map(async (row) => {
          const name = scenarioInputName(row.label, taken);
          taken.add(name);
          return { row, name, ref: await uploadedRef(cluster.client, row.functionalScenarioContent, "functional_scenario", "text/plain", signal) };
        })
      );
      const config = sceneEntryConfig({
        name: entryName("Batch scene generation", `${rows.length} scenarios`),
        scenarios: scenarios.map(({ name, ref }) => ({ name, ref })),
        domain: input,
        timeoutSeconds: input.timeoutSeconds,
        enforceLowTcpa: input.enforceLowTcpa,
        seed: takeEntrySeed(),
        monitor: this.stepMonitor(),
      });
      const entryId = await this.createEntry(cluster, toConfigYaml(config), config.name, WORKBENCH_ORIGIN.sceneGeneration, task);
      const waiter = createCaseWaiter(cluster.client, entryId, this.follow(signal));
      await Promise.all(
        scenarios.map(async ({ row, name }) => {
          try {
            const caseView = await waiter.waitFor(scenarioClassId(name));
            const outcome = await this.followSceneCase(cluster, row.requestId, { campaignId: entryId, caseId: caseView.case_id }, task, true);
            if (outcome.ok && !outcome.valid) {
              useBatchGenerationStore.getState().setBatchRequestStatus(row.requestId, "timeout", "No valid scene within the timeout.");
            } else if (!outcome.ok) {
              useBatchGenerationStore.getState().setBatchRequestStatus(row.requestId, outcome.stopped ? "cancelled" : "error", outcome.stopped ? "Stopped" : outcome.message);
            }
          } catch (error) {
            const stopped = isAbort(error) || signal.aborted;
            useBatchGenerationStore.getState().setBatchRequestStatus(row.requestId, stopped ? "cancelled" : "error", stopped ? "Stopped" : describe(error));
          }
        })
      );
    } catch (error) {
      const stopped = isAbort(error) || signal.aborted;
      for (const row of rows) {
        useBatchGenerationStore.getState().setBatchRequestStatus(row.requestId, stopped ? "cancelled" : "error", stopped ? "Stopped" : describe(error));
      }
    } finally {
      for (const row of rows) {
        if (this.sceneJobs.get(row.requestId) === task) {
          this.sceneJobs.delete(row.requestId);
        }
      }
    }
  }

  /** Stops the scene page's runs and follows; `byUser` for the page's Stop button. */
  stopScenes(byUser = false): void {
    const tasks = new Set(this.sceneJobs.values());
    for (const task of tasks) {
      this.abortTask(task, byUser);
    }
    this.sceneJobs.clear();
  }

  get runningScenes(): number {
    return this.sceneJobs.size;
  }

  /** A search sample while the job runs: progress only, so it never ends the request early. */
  private dispatchSample(requestId: string, sample: SceneSample): void {
    if (sample.final || sample.scene === undefined || sample.scene === null) {
      return;
    }
    try {
      const evaluationData = typeof sample.evaluation_data === "object" && sample.evaluation_data !== null ? (sample.evaluation_data as EvaluationData) : null;
      this.dispatch({ kind: "generated_scene", requestId, valid: false, scene: parseFrame(sample.scene), evaluationData });
    } catch {
      // A sample that does not parse is only a missed preview.
    }
  }

  /**
   * Monitors one scene loaded from a file with the cluster's post-hoc monitor and merges the
   * verdicts into the shown scene. Without a node that monitors, the scene stays as it is.
   */
  async monitorScene(requestId: string, scenario: Record<string, unknown>, colregsConstraintsContent: string): Promise<void> {
    const cluster = this.access().cluster;
    if (cluster === null || this.blocker(MONITORING_JOB) !== null) {
      return;
    }
    const trajectories = singleSceneTrajectories(scenario);
    if (trajectories === null) {
      return;
    }
    useScenePlaybackStore.getState().beginSceneMonitor(requestId);
    try {
      const job = await runClusterJob(cluster, monitoringSubmission(trajectories, colregsConstraintsContent, requestId));
      if (job.state === "succeeded") {
        const frames = await monitoredFrames(cluster, job);
        if (frames[0]) {
          useScenePlaybackStore.getState().applySceneMonitorResult(requestId, frames[0]);
        }
      }
    } catch {
      // The scene stays unmonitored, as with no node that monitors.
    }
  }

  /**
   * Monitors the trajectories loaded on the simulation page on the cluster and replaces the
   * preview's frames with the monitored ones, while the same scenario is still loaded.
   */
  async monitorPreview(scenarioId: string, scenarioContent: string, colregsConstraintsContent: string): Promise<void> {
    this.previewMonitorJob?.abort();
    const playback = usePlaybackStore.getState();
    let raw: unknown;
    try {
      raw = JSON.parse(scenarioContent);
    } catch {
      return;
    }
    if (!isFullTrajectoryScenario(raw)) {
      playback.setPreviewMonitor({ status: "idle", scenarioId, message: null });
      return;
    }
    const cluster = this.access().cluster;
    const blocker = this.blocker(MONITORING_JOB);
    if (cluster === null || blocker !== null) {
      playback.setPreviewMonitor({ status: "unavailable", scenarioId, message: blocker });
      return;
    }
    const controller = new AbortController();
    this.previewMonitorJob = controller;
    const trajectories = (raw as { trajectories: Record<string, unknown> }).trajectories;
    playback.setPreviewMonitor({ status: "running", scenarioId, message: "Monitoring the trajectory on the cluster..." });
    const stillLoaded = () => usePlaybackStore.getState().activeScenarioId === scenarioId && !controller.signal.aborted;
    try {
      const job = await runClusterJob(cluster, monitoringSubmission(trajectories, colregsConstraintsContent, scenarioId), { signal: controller.signal });
      if (!stillLoaded()) {
        return;
      }
      if (job.state !== "succeeded") {
        usePlaybackStore.getState().setPreviewMonitor({ status: "failed", scenarioId, message: jobFailureMessage(job) });
        return;
      }
      const frames = await monitoredFrames(cluster, job, controller.signal);
      if (!stillLoaded()) {
        return;
      }
      usePlaybackStore.getState().setTrajectoryPreviewFrames(frames);
      usePlaybackStore.getState().setPreviewMonitor({ status: "done", scenarioId, message: null });
    } catch (error) {
      if (stillLoaded()) {
        usePlaybackStore.getState().setPreviewMonitor({ status: "failed", scenarioId, message: describe(error) });
      }
    } finally {
      if (this.previewMonitorJob === controller) {
        this.previewMonitorJob = null;
      }
    }
  }

  // Trajectory generation

  /** Plans trajectories for the page's input scene as a workbench entry; the trajectory page follows the previews and the result. */
  async generateTrajectories(requestId: string, request: TrajectoryEntryRequest): Promise<void> {
    this.abortTask(this.trajectoryJob);
    useTrajectoryPlaybackStore.getState().clearPreviewFrames();
    useTrajectoryGenerationStore.getState().startRun(requestId);
    const cluster = this.access().cluster;
    const blocker = this.blocker(TRAJECTORY_GENERATION_JOB);
    if (cluster === null || blocker !== null) {
      this.dispatchTrajectoryResult(requestId, blocker ?? "No cluster is selected.");
      return;
    }
    const task = this.newTask(true);
    this.trajectoryJob = task;
    const page = PAGE_STORES.trajectoryGeneration;
    page.getState().setStatus("running", "Creating the workbench entry...", null);
    try {
      const signal = task.controller.signal;
      const item = await resolveInputItem(cluster.client, request.input, request.scenarioContent, "scene", signal);
      const config = trajectoryEntryConfig({
        name: entryName("Trajectory generation", request.input.label),
        scene: item,
        colregsConstraintsContent: request.colregsConstraintsContent,
        params: request.params,
        seed: takeEntrySeed(),
        monitor: this.stepMonitor(),
      });
      const entryId = await this.createEntry(cluster, toConfigYaml(config), config.name, WORKBENCH_ORIGIN.trajectoryGeneration, task);
      page.getState().setStatus("running", "Waiting for the entry's trajectory generation job...", entryId);
      const caseView = await waitForCase(cluster.client, entryId, null, this.follow(signal));
      await this.followTrajectoryCase(cluster, requestId, { campaignId: entryId, caseId: caseView.case_id }, task);
    } catch (error) {
      this.trajectoryFailure(requestId, error, task);
    } finally {
      if (this.trajectoryJob === task) {
        this.trajectoryJob = null;
      }
    }
  }

  private trajectoryFailure(requestId: string, error: unknown, task: PageTask): void {
    if (isAbort(error) || task.controller.signal.aborted) {
      useTrajectoryGenerationStore.getState().markStopped();
      PAGE_STORES.trajectoryGeneration.getState().setStatus("idle", null, null);
      return;
    }
    const message = isGone(error) ? "The entry was deleted." : `Trajectory generation on the cluster failed: ${describe(error)}`;
    this.dispatchTrajectoryResult(requestId, message);
    PAGE_STORES.trajectoryGeneration.getState().setStatus("failed", message, null);
  }

  private async followTrajectoryCase(cluster: WorkbenchCluster, requestId: string, entry: { campaignId: string; caseId: number }, task: PageTask): Promise<void> {
    const signal = task.controller.signal;
    const { jobId, detail } = await waitForStageJob(cluster.client, entry.campaignId, entry.caseId, "generate_trajectories", this.follow(signal));
    if (jobId === null) {
      this.dispatchTrajectoryResult(requestId, caseEndMessage(detail));
      return;
    }
    const previews = new PreviewFollower(cluster, "trajectory_generation", (preview) =>
      this.dispatch({ kind: "trajectory_generation_preview", requestId, trajectoryData: (preview as TrajectoryPreview).trajectories as Record<string, unknown> })
    );
    let job: JobView;
    try {
      job = await followJob(cluster.client, jobId, { pollIntervalMs: this.jobPollMs, channel: cluster.channel, signal, onProgress: (event) => previews.follow(event, true) });
    } finally {
      previews.stop();
    }
    if (job.state === "cancelled") {
      useTrajectoryGenerationStore.getState().markStopped();
      return;
    }
    if (job.state !== "succeeded") {
      this.dispatchTrajectoryResult(requestId, jobFailureMessage(job));
      return;
    }
    const result = await trajectoryJobResult(cluster, job, signal);
    this.dispatch({ kind: "trajectory_generation_result", requestId, ...result });
    const target: WorkbenchTarget = { page: "trajectoryGeneration", campaignId: entry.campaignId, caseId: entry.caseId, step: "trajectory_generation" };
    await this.finishEntry(target, task, "Monitoring the planned trajectories on the cluster...");
  }

  stopTrajectories(byUser = false): void {
    this.abortTask(this.trajectoryJob, byUser);
    this.trajectoryJob = null;
    useTrajectoryGenerationStore.getState().markStopped();
  }

  // Simulation

  /**
   * Runs the page's input trajectories as a workbench entry on the plan's stack (kinematic, or
   * ArduPilot SITL or Gazebo); its frames fill the simulation stream as the node sends them.
   */
  async runSimulationEntry(plan: ClusterRunPlan, request: SimulationEntryRequest): Promise<void> {
    this.abortTask(this.simulationJob);
    const run = useClusterRunStore.getState();
    const cluster = this.access().cluster;
    const blocker = this.blocker(plan.jobType);
    if (cluster === null || blocker !== null) {
      run.update({ status: "failed", jobId: null, nodeId: null, message: blocker ?? "No cluster is selected." });
      return;
    }
    const task = this.newTask(true);
    this.simulationJob = task;
    const signal = task.controller.signal;
    usePlaybackStore.getState().clearSimulationTrajectories();
    run.update({ status: "queued", jobId: null, nodeId: null, message: "Creating the workbench entry..." });
    try {
      const item = await resolveInputItem(cluster.client, request.input, request.scenarioContent, "trajectories", signal);
      const config = simulationEntryConfig({
        name: entryName("Simulation", request.input.label),
        trajectories: item,
        plan,
        colregsConstraintsContent: request.colregsConstraintsContent,
        seed: takeEntrySeed(),
        geofence: request.geofence,
      });
      const entryId = await this.createEntry(cluster, toConfigYaml(config), config.name, WORKBENCH_ORIGIN.simulation, task);
      PAGE_STORES.simulation.getState().setStatus("running", null, entryId);
      useClusterRunStore.getState().update({ message: "Waiting for a free slot on the cluster..." });
      const caseView = await waitForCase(cluster.client, entryId, null, this.follow(signal));
      await this.followSimulationCase(cluster, { campaignId: entryId, caseId: caseView.case_id }, task);
    } catch (error) {
      this.simulationFailure(error, task);
    } finally {
      if (this.simulationJob === task) {
        this.simulationJob = null;
      }
    }
  }

  private simulationFailure(error: unknown, task: PageTask): void {
    if (this.simulationJob !== task) {
      return;
    }
    const stopped = isAbort(error) || task.controller.signal.aborted;
    const message = stopped ? "Stopped." : isGone(error) ? "The entry was deleted." : `The run on the cluster failed: ${describe(error)}`;
    useClusterRunStore.getState().update({ status: stopped ? "stopped" : "failed", message });
    PAGE_STORES.simulation.getState().setStatus(stopped ? "idle" : "failed", stopped ? null : message, null);
  }

  /**
   * Follows the simulation of an entry's case: the run is watched at the run store's speed as the
   * node sends its frames; when it ended before the observation reached its node, the frames come
   * from the entry's run record (the frames route).
   */
  private async followSimulationCase(cluster: WorkbenchCluster, entry: { campaignId: string; caseId: number }, task: PageTask): Promise<void> {
    const signal = task.controller.signal;
    const { jobId, detail } = await waitForStageJob(cluster.client, entry.campaignId, entry.caseId, "simulate", this.follow(signal));
    if (jobId === null) {
      useClusterRunStore.getState().update({ status: "failed", message: caseEndMessage(detail) });
      return;
    }
    const job = await this.watchSimulation(cluster, task, (onProgress) => followJob(cluster.client, jobId, { pollIntervalMs: this.jobPollMs, channel: cluster.channel, signal, onProgress }));
    if (job === null || this.simulationJob !== task) {
      return;
    }
    const { value: runRecordId } = await pollCase(cluster.client, entry.campaignId, entry.caseId, (current) => current.run_records[0]?.run_record_id ?? null, this.follow(signal));
    const planned = await this.plannedSteps(cluster, job, signal);
    if (runRecordId !== null && planned > usePlaybackStore.getState().simulationFrames.length) {
      useClusterRunStore.getState().update({ status: "finishing", message: "The run ended before it was watched: loading its frames from the entry..." });
      usePlaybackStore.getState().applyMergedSimulationFrames(await framesOfRun(cluster.client, entry.campaignId, runRecordId, signal));
    }
    if (this.simulationJob !== task) {
      return;
    }
    useClusterRunStore.getState().update({ status: "done", message: `Finished: ${usePlaybackStore.getState().simulationFrames.length} frames.` });
    if (runRecordId !== null) {
      const target: WorkbenchTarget = { page: "simulation", campaignId: entry.campaignId, caseId: entry.caseId, step: "simulation", runRecordId };
      PAGE_STORES.simulation.getState().setLoaded(target, null);
      if (!task.ownEntry) {
        // A followed run of another page or section: its input and setup come with it, so it can run again.
        await this.loadTarget(target, { quiet: true });
      }
    } else {
      PAGE_STORES.simulation.getState().setStatus("shown", null, null);
    }
  }

  private async plannedSteps(cluster: WorkbenchCluster, job: JobView, signal: AbortSignal): Promise<number> {
    const result = isRecord(job.result) ? job.result : {};
    if (result.trajectories === undefined || result.trajectories === null) {
      return 0;
    }
    try {
      const trajectories = await readResultField(cluster.client, result.trajectories, { signal });
      return isRecord(trajectories) && Array.isArray(trajectories.scene_list) ? trajectories.scene_list.length : 0;
    } catch {
      return 0;
    }
  }

  /**
   * Watches a simulation job: its status in the run store, its frames in the simulation stream,
   * observed on its instance topic at the run store's speed. Resolves with the job once it
   * succeeded, null when it ended otherwise (the run store says why).
   */
  private async watchSimulation(cluster: WorkbenchCluster, task: PageTask, follow: (onProgress: (event: JobProgressEvent) => void) => Promise<JobView>): Promise<JobView | null> {
    const frames = new FrameBuffer(INSTANCE_FRAMES_KEPT);
    let watchedKey: string | null = null;
    let unwatch: () => void = () => {};
    const stopWatching = () => {
      unwatch();
      unwatch = () => {};
      this.simulationWatcher = null;
    };
    const current = () => this.simulationJob === task;
    try {
      const job = await follow(({ job, status }) => {
        if (!current()) {
          return;
        }
        const running = job.state === "leased" || job.state === "running";
        useClusterRunStore.getState().update({
          jobId: job.job_id,
          nodeId: job.lease_owner,
          ...(job.state === "queued" ? { status: "queued" } : running ? { status: "running", message: status?.message ?? "Running on the cluster" } : {}),
        });
        const key = running && job.lease_owner ? `${job.lease_owner}/${jobInstanceName(job.job_id, job.attempt)}` : null;
        if (key === null || key === watchedKey || cluster.channel === null) {
          return;
        }
        stopWatching();
        watchedKey = key;
        const watcher = new LiveTopicWatcher(cluster.channel, instanceTopic(job.lease_owner as string, jobInstanceName(job.job_id, job.attempt)), instanceReducer, {
          speed: useClusterRunStore.getState().speed,
        });
        this.simulationWatcher = watcher;
        unwatch = watcher.subscribe(() => {
          const data = watcher.getState().data;
          if (data && current()) {
            usePlaybackStore.getState().applyMergedSimulationFrames(frames.sync(data.frames, data.frameCount));
          }
        });
      });
      if (!current()) {
        return null;
      }
      if (job.state !== "succeeded") {
        useClusterRunStore.getState().update({ status: job.state === "cancelled" ? "stopped" : "failed", message: jobFailureMessage(job) });
        return null;
      }
      return job;
    } finally {
      stopWatching();
    }
  }

  /**
   * Runs a simulation as one direct job, for trajectories the page has no input for (the entry
   * route needs one). A run that ended before the observation reached its node is monitored
   * over its result trajectories.
   */
  async runSimulation(submission: JobSubmission, colregsConstraintsContent: string): Promise<void> {
    this.abortTask(this.simulationJob);
    const run = useClusterRunStore.getState();
    const cluster = this.access().cluster;
    const blocker = this.blocker(submission.job_type);
    if (cluster === null || blocker !== null) {
      run.update({ status: "failed", jobId: null, nodeId: null, message: blocker ?? "No cluster is selected." });
      return;
    }
    const task = this.newTask(false);
    this.simulationJob = task;
    const signal = task.controller.signal;
    usePlaybackStore.getState().clearSimulationTrajectories();
    PAGE_STORES.simulation.getState().setStatus("running", null, null);
    run.update({ status: "queued", jobId: null, nodeId: null, message: "Waiting for a free slot on the cluster..." });
    try {
      const job = await this.watchSimulation(cluster, task, (onProgress) => runClusterJob(cluster, submission, { signal, onProgress }));
      if (job === null) {
        return;
      }
      const result = isRecord(job.result) ? job.result : {};
      const trajectories = await readResultField(cluster.client, result.trajectories, { signal });
      const planned = isRecord(trajectories) && Array.isArray(trajectories.scene_list) ? trajectories.scene_list.length : 0;
      const shown = usePlaybackStore.getState().simulationFrames.length;
      if (planned > shown && isRecord(trajectories) && this.blocker(MONITORING_JOB) === null) {
        useClusterRunStore.getState().update({ status: "finishing", message: "The run ended before it was watched: monitoring its result on the cluster..." });
        const monitorJob = await runClusterJob(cluster, monitoringSubmission(trajectories, colregsConstraintsContent, job.job_id), { signal });
        if (monitorJob.state === "succeeded" && this.simulationJob === task) {
          usePlaybackStore.getState().applyMergedSimulationFrames(await monitoredFrames(cluster, monitorJob, signal));
        }
      }
      if (this.simulationJob === task) {
        useClusterRunStore.getState().update({ status: "done", message: `Finished: ${usePlaybackStore.getState().simulationFrames.length} frames.` });
        PAGE_STORES.simulation.getState().setStatus("shown", null, null);
      }
    } catch (error) {
      this.simulationFailure(error, task);
    } finally {
      if (this.simulationJob === task) {
        this.simulationJob = null;
      }
    }
  }

  /** Changes the pace a running kinematic simulation is watched and run at; an ArduPilot run keeps its speedup (the watch speed only thins its frames). */
  setSimulationSpeed(speed: number): void {
    useClusterRunStore.getState().update({ speed });
    this.simulationWatcher?.configure({ speed });
  }

  stopSimulation(byUser = false): void {
    if (this.simulationJob !== null) {
      this.abortTask(this.simulationJob, byUser);
      useClusterRunStore.getState().update({ status: "stopped", message: "Stopped." });
      PAGE_STORES.simulation.getState().setStatus("idle", null, null);
    }
    this.simulationJob = null;
  }

  // Targets from Campaign History and the pages' own loaded entries

  /**
   * Shows a target on its page: follows the running job when the target is live (scene previews,
   * trajectory previews, a simulation watched at the run store's speed), else loads the output.
   * The page's own run, if any, is stopped first: the page shows one thing.
   */
  async openTarget(target: WorkbenchTarget): Promise<void> {
    if (target.live) {
      await this.followTarget(target);
      return;
    }
    await this.loadTarget(target);
  }

  private async followTarget(target: WorkbenchTarget): Promise<void> {
    const cluster = this.access().cluster;
    if (cluster === null) {
      PAGE_STORES[target.page].getState().setStatus("failed", "No cluster is selected.", null);
      return;
    }
    const entry = { campaignId: target.campaignId, caseId: target.caseId };
    const page = PAGE_STORES[target.page].getState();
    const task = this.newTask(false, target.campaignId);
    void cluster.client
      .getCampaign(target.campaignId, task.controller.signal)
      .then((campaign) => {
        task.workbenchEntry = campaign.kind === "workbench";
      })
      .catch(() => undefined);
    page.setStatus("following", "Following the running entry...", target.campaignId);
    switch (target.page) {
      case "sceneGeneration": {
        this.stopScenes();
        const requestId = `follow-${target.campaignId}-${target.caseId}`;
        this.sceneJobs.set(requestId, task);
        useScenePlaybackStore.getState().setActiveSceneGenerationRequestId(requestId);
        try {
          const outcome = await this.followSceneCase(cluster, requestId, entry, task, false);
          if (!outcome.ok) {
            this.sceneFailure(new Error(outcome.message), task);
          }
        } catch (error) {
          if (isGone(error)) {
            this.clearPage("sceneGeneration", "The entry was deleted.");
          } else {
            this.sceneFailure(error, task);
          }
        } finally {
          this.sceneJobs.delete(requestId);
          if (useScenePlaybackStore.getState().activeSceneGenerationRequestId === requestId) {
            useScenePlaybackStore.getState().setActiveSceneGenerationRequestId(null);
          }
        }
        return;
      }
      case "trajectoryGeneration": {
        this.abortTask(this.trajectoryJob);
        const requestId = `follow-${target.campaignId}-${target.caseId}`;
        this.trajectoryJob = task;
        useTrajectoryPlaybackStore.getState().clearPreviewFrames();
        useTrajectoryGenerationStore.getState().startRun(requestId);
        try {
          await this.followTrajectoryCase(cluster, requestId, entry, task);
        } catch (error) {
          this.trajectoryFailure(requestId, error, task);
        } finally {
          if (this.trajectoryJob === task) {
            this.trajectoryJob = null;
          }
        }
        return;
      }
      case "simulation": {
        this.abortTask(this.simulationJob);
        this.simulationJob = task;
        usePlaybackStore.getState().clearSimulationTrajectories();
        useClusterRunStore.getState().update({ status: "queued", jobId: null, nodeId: null, message: "Following the running entry..." });
        try {
          await this.followSimulationCase(cluster, entry, task);
        } catch (error) {
          this.simulationFailure(error, task);
        } finally {
          if (this.simulationJob === task) {
            this.simulationJob = null;
          }
        }
      }
    }
  }

  /**
   * Loads a target's output on its page. With `quiet`, a failure other than a deleted entry
   * leaves the page as it is (a page refreshing its loaded entry after a reload).
   */
  async loadTarget(target: WorkbenchTarget, options: { quiet?: boolean } = {}): Promise<void> {
    const cluster = this.access().cluster;
    const page = PAGE_STORES[target.page];
    if (cluster === null) {
      if (!options.quiet) {
        page.getState().setStatus("failed", "No cluster is selected.", null);
      }
      return;
    }
    this.loads.get(target.page)?.abort();
    const controller = new AbortController();
    this.loads.set(target.page, controller);
    if (!options.quiet) {
      page.getState().setStatus("loading", "Loading the entry's output...", target.campaignId);
    }
    try {
      const loaded = await loadEntryOutput(cluster.client, target, { signal: controller.signal });
      if (!controller.signal.aborted) {
        await this.showLoaded(target, loaded);
      }
    } catch (error) {
      if (controller.signal.aborted || isAbort(error)) {
        return;
      }
      if (isGone(error)) {
        this.clearPage(target.page, "The entry was deleted, so the page no longer shows it.");
      } else if (!options.quiet) {
        page.getState().setStatus("failed", `The entry's output could not be loaded: ${describe(error)}`, null);
      }
    } finally {
      if (this.loads.get(target.page) === controller) {
        this.loads.delete(target.page);
      }
    }
  }

  private async showLoaded(target: WorkbenchTarget, loaded: LoadedOutput): Promise<void> {
    switch (loaded.step) {
      case "scene_generation":
        showLoadedScene(target, loaded);
        return;
      case "trajectory_generation":
        showLoadedTrajectories(target, loaded);
        return;
      case "simulation": {
        if (loaded.scenario !== null) {
          await this.hooks.loadSimulationInput(JSON.stringify(loaded.scenario), `run_${target.campaignId}_${target.caseId}.json`, loaded.frames);
          if (loaded.input !== null) {
            PAGE_STORES.simulation.getState().setInput({ label: loaded.input.label, origin: "history", ref: loaded.input.ref, source: loaded.input.source });
          }
        } else {
          usePlaybackStore.getState().clearSimulationTrajectories();
          usePlaybackStore.getState().applyMergedSimulationFrames(loaded.frames);
        }
        this.hooks.fillSetup(loaded);
        usePlaybackStore.getState().requestAutoFit();
        PAGE_STORES.simulation.getState().setLoaded({ ...target, runRecordId: loaded.runRecord.run_record_id }, null);
      }
    }
  }

  /** The loaded entry is gone: the page drops its output (its input stays). */
  clearPage(page: WorkbenchPage, message: string | null): void {
    clearPageOutput(page);
    if (page === "simulation") {
      useClusterRunStore.getState().update({ status: "idle", jobId: null, nodeId: null, message: null });
    }
    PAGE_STORES[page].getState().clearLoaded(message);
  }

  /** Stops everything this driver follows (the workbench is closed or switched to another cluster). */
  stopAll(): void {
    this.stopScenes();
    this.abortTask(this.trajectoryJob);
    this.trajectoryJob = null;
    this.previewMonitorJob?.abort();
    this.stopSimulation();
    for (const controller of this.loads.values()) {
      controller.abort();
    }
    this.loads.clear();
  }

  private dispatchTrajectoryResult(requestId: string, errorMessage: string): void {
    this.dispatch({ kind: "trajectory_generation_result", requestId, trajectoryData: null, valid: false, complete: null, errorMessage });
  }
}


/** Follows the previews of a job on the pool of whichever node holds it, switching nodes on a retry. */
class PreviewFollower {
  private readonly cluster: WorkbenchCluster;
  private readonly kind: PoolKind;
  private readonly onPreview: (preview: SceneSample | TrajectoryPreview) => void;
  private watched: string | null = null;
  private unwatch: () => void = () => {};

  constructor(cluster: WorkbenchCluster, kind: PoolKind, onPreview: (preview: SceneSample | TrajectoryPreview) => void) {
    this.cluster = cluster;
    this.kind = kind;
    this.onPreview = onPreview;
  }

  follow({ job }: JobProgressEvent, wanted: boolean): void {
    const key = previewKey(job);
    if (!wanted || this.cluster.channel === null || key === null) {
      if (!wanted || key === null) {
        this.stop();
      }
      return;
    }
    if (key === this.watched) {
      return;
    }
    this.stop();
    this.watched = key;
    this.unwatch = watchPoolPreviews(this.cluster.channel, job.lease_owner as string, this.kind, poolRequestId(job), this.onPreview);
  }

  stop(): void {
    this.unwatch();
    this.unwatch = () => {};
    this.watched = null;
  }
}

function previewKey(job: JobView): string | null {
  if ((job.state !== "leased" && job.state !== "running") || !job.lease_owner) {
    return null;
  }
  return `${job.lease_owner}/${poolRequestId(job)}`;
}
