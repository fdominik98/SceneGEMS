import { instanceTopic, jobInstanceName } from "./liveProtocol";
import type { OperatorClient } from "./operatorApi";
import type { JobView, NodeView } from "./schemas";

/**
 * The subsystem instances of a node that the Cluster page can show (its instance browser) and follow (design doc 5.2 and
 * 5.3, topic `instance:<node>/<instance>`): the pool instances its slots
 * give (`scene_generation-<n>`, `trajectory_generation-<n>`) and the instances of the jobs
 * it has leased or runs (`job-<job id>-<attempt>`).
 */

export type InstanceKind = "scene_generation" | "trajectory_generation" | "simulation" | "monitoring";

/** Which viewer shows an instance. */
export type ViewerKind = "scene_generation" | "trajectory_search" | "simulation" | "job";

export interface ObservableInstance {
  nodeId: string;
  /** The instance name on the node: `scene_generation-0`, `job-<job id>-<attempt>`. */
  instance: string;
  topic: string;
  kind: InstanceKind;
  origin: "pool" | "job";
  /** The pool slot index, null for a job instance. */
  index: number | null;
  /** The job behind a job instance, null for a pool instance. */
  job: JobView | null;
  /** Short text for the picker. */
  label: string;
  /** The job's state, or the node's status for a pool instance (the snapshot's `state` once viewed). */
  state: string;
}

const POOL_KINDS = ["scene_generation", "trajectory_generation"] as const;

/** Job types to the instance kind the master reports (`JOB_INSTANCE_KINDS` in `cluster/protocol/live.py`). */
export function jobInstanceKind(jobType: string): InstanceKind {
  if (jobType === "scene_generation") {
    return "scene_generation";
  }
  if (jobType === "trajectory_generation") {
    return "trajectory_generation";
  }
  if (jobType === "monitoring.post_hoc") {
    return "monitoring";
  }
  return "simulation";
}

/** The pool instances of a node: one per slot of each pooled subsystem it offers. */
export function poolInstances(node: NodeView): ObservableInstance[] {
  const result: ObservableInstance[] = [];
  for (const kind of POOL_KINDS) {
    const usage = node.slots[kind];
    if (!usage) {
      continue;
    }
    for (let index = 0; index < usage.slots; index += 1) {
      const instance = `${kind}-${index}`;
      result.push({
        nodeId: node.node_id,
        instance,
        topic: instanceTopic(node.node_id, instance),
        kind,
        origin: "pool",
        index,
        job: null,
        label: `${kind === "scene_generation" ? "Scene generation" : "Trajectory generation"} ${index}`,
        state: node.status,
      });
    }
  }
  return result;
}

/** Job states whose instance runs on a node. */
export const OBSERVABLE_JOB_STATES = ["leased", "running"] as const;

/** The instances of the jobs a node holds: jobs leased or running with this node as the lease owner. */
export function jobInstances(node: NodeView, jobs: readonly JobView[]): ObservableInstance[] {
  const seen = new Set<string>();
  const result: ObservableInstance[] = [];
  for (const job of jobs) {
    if (job.lease_owner !== node.node_id || !(OBSERVABLE_JOB_STATES as readonly string[]).includes(job.state)) {
      continue;
    }
    const instance = jobInstanceName(job.job_id, job.attempt);
    if (seen.has(instance)) {
      continue;
    }
    seen.add(instance);
    result.push({
      nodeId: node.node_id,
      instance,
      topic: instanceTopic(node.node_id, instance),
      kind: jobInstanceKind(job.job_type),
      origin: "job",
      index: null,
      job,
      label: `${job.job_type} ${job.job_id.slice(0, 8)}, attempt ${job.attempt}`,
      state: job.state,
    });
  }
  return result;
}

/** The instances of a node, pools first. */
export function nodeInstances(node: NodeView, jobs: readonly JobView[]): ObservableInstance[] {
  return [...poolInstances(node), ...jobInstances(node, jobs)];
}

export function viewerFor(instance: Pick<ObservableInstance, "origin" | "kind">): ViewerKind {
  if (instance.origin === "pool") {
    return instance.kind === "scene_generation" ? "scene_generation" : "trajectory_search";
  }
  return instance.kind === "simulation" ? "simulation" : "job";
}

/** The jobs a node holds, from `GET /cluster/jobs` for each observable state, filtered by lease owner. */
export async function fetchNodeJobs(client: OperatorClient, nodeId: string, signal?: AbortSignal): Promise<JobView[]> {
  const lists = await Promise.all(OBSERVABLE_JOB_STATES.map((state) => client.listJobs({ state, limit: 200 }, signal)));
  return lists.flatMap((list) => list.items).filter((job) => job.lease_owner === nodeId);
}
