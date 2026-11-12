import type { ClusterSummary } from "../features/cluster/clusterFormat";
import type { PageStatus } from "../features/workbench/pages/pageStore";
import type { WorkbenchPage } from "../features/workbench/pages/workbenchTarget";

/**
 * The state of the system as the left pane shows it on every page: whether the selected cluster
 * answers and what it runs, how many entries of Campaign History are running, and what each
 * workbench page holds. Pure, so the pane only draws it (`useSystemStatus` reads the stores).
 */

/** `info` is a result to look at: nothing runs and nothing is wrong. */
export type StatusTone = "idle" | "busy" | "ok" | "info" | "warn" | "bad";

export interface ClusterStatusLine {
  tone: StatusTone;
  /** The state in a word or two: "Connected", "Cannot reach the control node". */
  label: string;
  /** What the cluster has and runs now, null while that is not known. */
  detail: string | null;
}

export interface StepIndicator {
  tone: StatusTone;
  label: string;
}

export interface SystemStatus {
  cluster: ClusterStatusLine;
  /** A mark per workbench page that has something to tell; a page without one is idle and empty. */
  steps: Partial<Record<WorkbenchPage, StepIndicator>>;
  /** Entries of Campaign History that run now, null while that is not known. */
  runningEntries: number | null;
}

export const NO_SYSTEM_STATUS: SystemStatus = {
  cluster: { tone: "idle", label: "No cluster selected", detail: null },
  steps: {},
  runningEntries: null,
};

export interface ClusterStatusInput {
  /** Whether a cluster is selected. */
  selected: boolean;
  /** Whether the control node answered with its worker nodes yet. */
  loaded: boolean;
  /** Whether the last request could not reach the control node at all. */
  unreachable: boolean;
  /** The last problem reading the worker nodes, null when there is none. */
  error: string | null;
  summary: ClusterSummary;
}

function countOf(count: number, total: number, noun: string): string {
  return `${count} of ${total} ${noun}${total === 1 ? "" : "s"}`;
}

/** The cluster line of the left pane: the worst thing first, then what the cluster runs. */
export function describeClusterStatus({ selected, loaded, unreachable, error, summary }: ClusterStatusInput): ClusterStatusLine {
  if (!selected) {
    return NO_SYSTEM_STATUS.cluster;
  }
  if (unreachable) {
    return { tone: "bad", label: "Cannot reach the control node", detail: loaded ? "showing what it last reported" : null };
  }
  if (!loaded) {
    return error ? { tone: "bad", label: "Control node error", detail: error } : { tone: "busy", label: "Connecting", detail: null };
  }
  const detail = `${countOf(summary.online, summary.workerNodes, "worker node")} online, ${countOf(summary.slotsInUse, summary.slots, "slot")} in use`;
  if (error) {
    return { tone: "warn", label: "Worker nodes may be stale", detail };
  }
  if (summary.workerNodes === 0) {
    return { tone: "warn", label: "No worker nodes", detail: "nothing can run until one connects" };
  }
  if (summary.online === 0) {
    return { tone: "bad", label: "No worker node online", detail };
  }
  if (summary.offline > 0 || summary.outOfDate > 0) {
    const problems = [summary.offline > 0 ? `${summary.offline} offline` : null, summary.outOfDate > 0 ? `${summary.outOfDate} out of date` : null].filter(Boolean).join(", ");
    return { tone: "warn", label: `Connected, ${problems}`, detail };
  }
  return { tone: "ok", label: "Connected", detail };
}

export interface StepStateInput {
  status: PageStatus;
  /** Whether the page shows an output: a loaded entry or a file. */
  hasOutput: boolean;
}

/** The mark of a workbench page in the navigation: a run in flight, a failure, or a result to look at. */
export function describeStep({ status, hasOutput }: StepStateInput): StepIndicator | null {
  switch (status) {
    case "running":
      return { tone: "busy", label: "Running" };
    case "following":
      return { tone: "busy", label: "Following a run" };
    case "loading":
      return { tone: "busy", label: "Loading" };
    case "failed":
      return { tone: "bad", label: "Failed" };
    default:
      return hasOutput ? { tone: "info", label: "Shows a result" } : null;
  }
}

/** "2 entries running", for the mark beside Campaign History. */
export function describeRunningEntries(count: number): string {
  return `${count} ${count === 1 ? "entry" : "entries"} running`;
}
