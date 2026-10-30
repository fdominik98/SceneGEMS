import { describeComponents, jobComponents, listsJob, offersJob } from "../../../domain/cluster/components";
import type { NodeView } from "../../../domain/cluster/schemas";
import { capabilityLabel, nodeProblems } from "../../campaigns/resourcePlan";

/**
 * Whether the selected cluster can run one of the workbench's jobs now: the usable nodes (online,
 * with slots for the job type and every component the job needs up to date), judged as the master's
 * scheduler does, and their slots. Without such a node the workbench does not submit the job; it
 * says why instead.
 */

export interface NodesFeedState {
  /** The selected cluster's operator URL, null when no cluster is selected. */
  operatorUrl: string | null;
  nodes: readonly NodeView[];
  loaded: boolean;
  unreachable: boolean;
}

export interface JobTypeResources {
  jobType: string;
  /** The components the job needs. */
  components: string[];
  /** Usable nodes that offer the job type. */
  nodes: number;
  /** Their slots for it, and the slots no job holds now. */
  slots: number;
  freeSlots: number;
  /** Why the workbench cannot run the job type now, null when it can. */
  blocker: string | null;
}

/** components: what the job needs; a job type's subsystem component (the kinematic replay for a simulation) when left out. */
export function jobTypeResources(feed: NodesFeedState, jobType: string, components: readonly string[] = jobComponents(jobType)): JobTypeResources {
  const offering = feed.nodes.filter((node) => listsJob(node, jobType, components));
  const usable = offering.filter((node) => nodeProblems(node, {}).length === 0 && offersJob(node, jobType, components));
  const slots = usable.reduce((sum, node) => sum + node.slots[jobType].slots, 0);
  const inUse = usable.reduce((sum, node) => sum + Math.min(node.slots[jobType].slots, node.slots[jobType].slots_in_use), 0);
  return { jobType, components: [...components], nodes: usable.length, slots, freeSlots: slots - inUse, blocker: resourceBlocker(feed, jobType, components, offering.length, usable.length) };
}

function resourceBlocker(feed: NodesFeedState, jobType: string, components: readonly string[], offering: number, usable: number): string | null {
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
  if (resources.nodes === 0) {
    return "no machine";
  }
  const machines = `${resources.nodes} machine${resources.nodes === 1 ? "" : "s"}`;
  return `${resources.slots} slot${resources.slots === 1 ? "" : "s"} on ${machines}, ${resources.freeSlots} free`;
}
