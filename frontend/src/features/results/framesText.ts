import type { FramesPhase } from "../../domain/cluster/framesApi";
import { formatBytes } from "./resultsFormat";

/** The follow-up of the request in words, one line per step. */
export function describeFramesPhase(phase: FramesPhase): string {
  switch (phase.phase) {
    case "idle":
      return "";
    case "submitting":
      return "Asking the control node for the monitor frames.";
    case "submitted":
      return phase.job.state === "leased" ? "A worker node has taken the monitoring job and is starting it." : "The monitoring job is waiting for a free worker node.";
    case "running":
      return phase.job.progress?.message ? `Monitoring the run: ${phase.job.progress.message}.` : "Monitoring the run on a worker node.";
    case "downloading":
      return `Downloading the frames${phase.sizeBytes ? ` (${formatBytes(phase.sizeBytes)})` : ""}.`;
    case "done":
      return `${phase.frames.length} frames loaded.`;
    case "unavailable":
      return phase.message;
    case "failed":
      return phase.message;
    case "error":
      return phase.message;
  }
}
