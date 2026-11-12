import { followJob, readResultField, type JobProgressEvent } from "../../../domain/cluster/clusterJobs";
import { parseFrames } from "../../../domain/cluster/framesApi";
import type { LiveChannel } from "../../../domain/cluster/liveChannel";
import { instanceTopic } from "../../../domain/cluster/liveProtocol";
import { instanceReducer, type SceneSample, type TrajectoryPreview } from "../../../domain/cluster/liveTopics";
import { LiveTopicWatcher } from "../../../domain/cluster/liveTopicWatcher";
import type { JobSubmission, OperatorClient } from "../../../domain/cluster/operatorApi";
import type { JobView } from "../../../domain/cluster/schemas";
import type { SimulationFrame } from "../../../domain/simulation/types";

/**
 * The workbench's jobs on the selected cluster: scene generation, trajectory generation and
 * post-hoc monitoring, as the job types of `cluster/worker_node/jobs/` define their payloads and
 * results. The cluster's scheduler places them on any worker node with a free slot, so a batch
 * submitted at once uses every slot the cluster has.
 */

export const DESIGN_SPACE_EXPLORATION_JOB = "design_space_exploration";
export const SCENE_GENERATION_JOB = "scene_generation";
export const TRAJECTORY_GENERATION_JOB = "trajectory_generation";
export const MONITORING_JOB = "monitoring.post_hoc";

export interface WorkbenchCluster {
  client: OperatorClient;
  /** The cluster's live channel for pushed job updates and previews; polling alone when null. */
  channel: LiveChannel | null;
}

export interface RunJobOptions {
  signal?: AbortSignal;
  onProgress?: (event: JobProgressEvent) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Submits a job and follows it until it ends. Aborting cancels it on the cluster. */
export async function runClusterJob(cluster: WorkbenchCluster, submission: JobSubmission, options: RunJobOptions = {}): Promise<JobView> {
  const job = await cluster.client.submitJob(submission, options.signal);
  const cancel = () => {
    void cluster.client.cancelJob(job.job_id, "stopped in the workbench").catch(() => undefined);
  };
  if (options.signal?.aborted) {
    cancel();
    throw new DOMException("The job was stopped.", "AbortError");
  }
  options.signal?.addEventListener("abort", cancel, { once: true });
  try {
    options.onProgress?.({ job, status: null });
    return await followJob(cluster.client, job.job_id, { channel: cluster.channel, signal: options.signal, onProgress: options.onProgress });
  } finally {
    options.signal?.removeEventListener("abort", cancel);
  }
}

/** The request id a job's attempt uses on its worker node's pool, which its previews carry. */
export function poolRequestId(job: Pick<JobView, "job_id" | "attempt">): string {
  return `${job.job_id}-${job.attempt}`;
}

// Scene generation (cluster/worker_node/jobs/scene_generation_job.py)

export interface SceneGenerationInput {
  functionalScenarioContent: string;
  colregsConstraintsContent: string;
  vesselTypesContent: string;
  obstacleTypesContent: string;
  timeoutSeconds: number;
  enforceLowTcpa: boolean;
}

export interface SceneJobResult {
  /** The worker's EvaluationData with `best_scene`, as a scenario file holds it. */
  evaluationData: Record<string, unknown>;
  /** Whether the scene meets the specification (penalty 0); false when the generation's timeout came first. */
  valid: boolean;
}

export async function sceneJobResult(cluster: WorkbenchCluster, job: JobView, signal?: AbortSignal): Promise<SceneJobResult> {
  const result = isRecord(job.result) ? job.result : {};
  const evaluationData = await readResultField(cluster.client, result.evaluation_data, { signal });
  if (!isRecord(evaluationData)) {
    throw new Error("The scene generation job returned no scene.");
  }
  return { evaluationData, valid: result.valid === true };
}

// Trajectory generation (cluster/worker_node/jobs/trajectory_generation_job.py)

export interface TrajectoryJobResult {
  /** The TrajectoryData payload (`trajectories`, and `monitor_frames` when the search recorded them), null when nothing was planned. */
  trajectoryData: Record<string, unknown> | null;
  valid: boolean;
  /** False for the best path the planner found: it ends early or still fails a COLREGS rule. */
  complete: boolean | null;
  errorMessage: string | null;
}

export async function trajectoryJobResult(cluster: WorkbenchCluster, job: JobView, signal?: AbortSignal): Promise<TrajectoryJobResult> {
  const result = isRecord(job.result) ? job.result : {};
  const trajectoryData = await readResultField(cluster.client, result.trajectory_data, { signal });
  return {
    trajectoryData: isRecord(trajectoryData) ? trajectoryData : null,
    valid: result.valid === true,
    complete: typeof result.complete === "boolean" ? result.complete : null,
    errorMessage: typeof result.error_message === "string" ? result.error_message : null,
  };
}

// Post-hoc monitoring (cluster/worker_node/jobs/monitoring_post_hoc_job.py)

/**
 * A scenario's first scene as a state log of one step, so the post-hoc monitor judges it like the
 * first frame of a run: `best_scene` of an EvaluationData, or the first scene of a TrajectoryData.
 */
export function singleSceneTrajectories(scenario: Record<string, unknown>): Record<string, unknown> | null {
  const trajectories = scenario.trajectories;
  const firstPlanned = isRecord(trajectories) && Array.isArray(trajectories.scene_list) ? trajectories.scene_list[0] : undefined;
  const scene = scenario.best_scene ?? scenario.bestScene ?? firstPlanned;
  return isRecord(scene) ? { scene_list: [scene], time_step: 1 } : null;
}

export function monitoringSubmission(trajectories: Record<string, unknown>, colregsConstraintsContent: string, scenarioId: string): JobSubmission {
  return {
    job_type: MONITORING_JOB,
    payload: {
      trajectories,
      colregs_constraints_content: colregsConstraintsContent.trim().length > 0 ? colregsConstraintsContent : null,
      scenario_id: scenarioId,
      include_frames: true,
    },
  };
}

export async function monitoredFrames(cluster: WorkbenchCluster, job: JobView, signal?: AbortSignal): Promise<SimulationFrame[]> {
  const result = isRecord(job.result) ? job.result : {};
  return parseFrames(await readResultField(cluster.client, result.frames, { signal }));
}

// Previews of a running job, from its worker node's pool (instance:<worker node>/<subsystem>-0 on the live channel)

export type PoolKind = "scene_generation" | "trajectory_generation";

/** The pool instance a worker node runs a subsystem's jobs in: one pool per subsystem and worker node (service_pools.POOL_INDEX). */
export function poolTopic(workerNodeId: string, kind: PoolKind): string {
  return instanceTopic(workerNodeId, `${kind}-0`);
}

/**
 * Calls `onPreview` with every new scene sample or trajectory preview of one request on a
 * worker node's pool, until the returned function is called. The pool serves every request on the
 * worker node, so the others' previews are left out by their request id.
 */
export function watchPoolPreviews(
  channel: LiveChannel,
  workerNodeId: string,
  kind: PoolKind,
  requestId: string,
  onPreview: (preview: SceneSample | TrajectoryPreview) => void
): () => void {
  const watcher = new LiveTopicWatcher(channel, poolTopic(workerNodeId, kind), instanceReducer);
  let last: SceneSample | TrajectoryPreview | null = null;
  return watcher.subscribe(() => {
    const data = watcher.getState().data;
    const preview = kind === "scene_generation" ? (data?.sceneSample ?? null) : (data?.trajectoryPreview ?? null);
    if (preview && preview !== last && preview.request_id === requestId) {
      last = preview;
      onPreview(preview);
    }
  });
}
