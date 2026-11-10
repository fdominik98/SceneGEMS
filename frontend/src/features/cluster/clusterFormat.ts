import type { WorkerNodeView } from "../../domain/cluster/schemas";

/** Readable text for the Cluster section's values. */

const JOB_TYPE_LABELS: Record<string, string> = {
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
  "monitoring.post_hoc": "Monitoring, post hoc",
  "calibration.deviation": "Calibration deviation",
};

export function jobTypeLabel(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType;
}

/** Megabytes as MB below 1 GB, otherwise GB with one decimal. */
export function formatMegabytes(mb: number): string {
  if (!Number.isFinite(mb)) {
    return "?";
  }
  if (Math.abs(mb) < 1024) {
    return `${Math.round(mb)} MB`;
  }
  return `${(mb / 1024).toFixed(1)} GB`;
}

/** How long ago an ISO time was, coarsely ("12 s ago", "5 min ago", "3 h ago", "2 d ago"). */
export function formatAge(iso: string | null | undefined, nowMs: number): string {
  if (!iso) {
    return "never";
  }
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) {
    return iso;
  }
  const seconds = Math.round((nowMs - at) / 1000);
  if (seconds < 0) {
    return "just now";
  }
  if (seconds < 60) {
    return `${seconds} s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.floor(hours / 24)} d ago`;
}

/** The start of a long hash or fingerprint, with any "sha256:" prefix dropped. */
export function shortHash(value: string | null | undefined, length = 12): string {
  if (!value) {
    return "none";
  }
  const bare = value.replace(/^sha256:/, "");
  return bare.length > length ? bare.slice(0, length) : bare;
}

export interface SlotTotals {
  slots: number;
  inUse: number;
}

export function workerNodeSlotTotals(workerNode: WorkerNodeView): SlotTotals {
  let slots = 0;
  let inUse = 0;
  for (const usage of Object.values(workerNode.slots)) {
    slots += usage.slots;
    inUse += usage.slots_in_use;
  }
  return { slots, inUse };
}

export interface ClusterSummary {
  workerNodes: number;
  online: number;
  draining: number;
  offline: number;
  connected: number;
  outOfDate: number;
  slots: number;
  slotsInUse: number;
  leases: number;
}

export function summarizeWorkerNodes(workerNodes: readonly WorkerNodeView[]): ClusterSummary {
  const summary: ClusterSummary = {
    workerNodes: workerNodes.length,
    online: 0,
    draining: 0,
    offline: 0,
    connected: 0,
    outOfDate: 0,
    slots: 0,
    slotsInUse: 0,
    leases: 0,
  };
  for (const workerNode of workerNodes) {
    summary[workerNode.status] += 1;
    if (workerNode.connected) summary.connected += 1;
    if (workerNode.out_of_date) summary.outOfDate += 1;
    const totals = workerNodeSlotTotals(workerNode);
    summary.slots += totals.slots;
    summary.slotsInUse += totals.inUse;
    summary.leases += workerNode.leases.length;
  }
  return summary;
}

/** Memory in use as a share of the total, in [0, 1]. */
export function memoryUseFraction(memoryMb: number, freeMemoryMb: number): number {
  if (memoryMb <= 0) {
    return 0;
  }
  return Math.min(1, Math.max(0, (memoryMb - freeMemoryMb) / memoryMb));
}
