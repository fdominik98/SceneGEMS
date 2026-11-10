import { describeComponents, jobComponents, listsJob, offersJob } from "../../../domain/cluster/components";
import type { WorkerNodeView } from "../../../domain/cluster/schemas";
import { capabilityLabel, workerNodeProblems } from "../../campaigns/resourcePlan";

/**
 * Whether the selected cluster can run one of the workbench's jobs now: the usable worker nodes (online,
 * with slots for the job type and every component the job needs up to date), judged as the control node's
 * scheduler does, and their slots. Without such a worker node the workbench does not submit the job; it
 * says why instead.
 */

export interface WorkerNodesFeedState {
  /** The selected cluster's operator URL, null when no cluster is selected. */
  operatorUrl: string | null;
  workerNodes: readonly WorkerNodeView[];
  loaded: boolean;
  unreachable: boolean;
}

export interface JobTypeResources {
  jobType: string;
  /** The components the job needs. */
  components: string[];
  /** Usable worker nodes that offer the job type. */
  workerNodes: number;
  /** Their slots for it, and the slots no job holds now. */
  slots: number;
  freeSlots: number;
  /** Why the workbench cannot run the job type now, null when it can. */
  blocker: string | null;
}

/** components: what the job needs; a job type's subsystem component (the kinematic replay for a simulation) when left out. */
export function jobTypeResources(feed: WorkerNodesFeedState, jobType: string, components: readonly string[] = jobComponents(jobType)): JobTypeResources {
  const offering = feed.workerNodes.filter((workerNode) => listsJob(workerNode, jobType, components));
  const usable = offering.filter((workerNode) => workerNodeProblems(workerNode, {}).length === 0 && offersJob(workerNode, jobType, components));
  const slots = usable.reduce((sum, workerNode) => sum + workerNode.slots[jobType].slots, 0);
  const inUse = usable.reduce((sum, workerNode) => sum + Math.min(workerNode.slots[jobType].slots, workerNode.slots[jobType].slots_in_use), 0);
  return { jobType, components: [...components], workerNodes: usable.length, slots, freeSlots: slots - inUse, blocker: resourceBlocker(feed, jobType, components, offering.length, usable.length) };
}

function resourceBlocker(feed: WorkerNodesFeedState, jobType: string, components: readonly string[], offering: number, usable: number): string | null {
  const capability = jobType === "simulation" ? `simulation with ${describeComponents(components)}` : capabilityLabel(jobType).toLowerCase();
  if (feed.operatorUrl === null) {
    return "No cluster is selected: choose the active cluster in the left pane, since the workbench runs its jobs there.";
  }
  if (usable > 0) {
    return null;
  }
  if (feed.unreachable) {
    return "The active cluster cannot be reached, so nothing can run on it.";
  }
  if (!feed.loaded) {
    return "Looking for the active cluster's machines...";
  }
  if (offering > 0) {
    return `The machines that offer ${capability} are offline, draining or out of date.`;
  }
  return `No machine of the active cluster offers ${capability}.`;
}

/** A short line on what the cluster offers, such as "6 slots on 2 machines, 4 free". */
export function describeResources(resources: JobTypeResources): string {
  if (resources.workerNodes === 0) {
    return "no machine";
  }
  const machines = `${resources.workerNodes} machine${resources.workerNodes === 1 ? "" : "s"}`;
  return `${resources.slots} slot${resources.slots === 1 ? "" : "s"} on ${machines}, ${resources.freeSlots} free`;
}
