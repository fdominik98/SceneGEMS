import { create } from "zustand";

/**
 * The workbench simulation that runs as a job on the cluster: where it stands, and the pace it
 * is watched at. The frames themselves go to the playback store's simulation stream.
 */

export type ClusterRunStatus = "idle" | "queued" | "running" | "finishing" | "done" | "failed" | "stopped";

export const DEFAULT_RUN_SPEED = 10;

export interface ClusterRunState {
  status: ClusterRunStatus;
  jobId: string | null;
  /** The worker node that runs the job, once one took it. */
  workerNodeId: string | null;
  /** What happens now, or why the run ended as it did. */
  message: string | null;
  /** Multiple of real time the control node paces the observed run to. */
  speed: number;
  update: (patch: Partial<Omit<ClusterRunState, "update">>) => void;
}

export const useClusterRunStore = create<ClusterRunState>()((set) => ({
  status: "idle",
  jobId: null,
  workerNodeId: null,
  message: null,
  speed: DEFAULT_RUN_SPEED,
  update: (patch) => set(patch),
}));

export function isClusterRunActive(status: ClusterRunStatus): boolean {
  return status === "queued" || status === "running" || status === "finishing";
}
