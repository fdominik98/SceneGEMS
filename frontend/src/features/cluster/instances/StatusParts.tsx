import type { ReactNode } from "react";
import type { LiveTopicState } from "../../../domain/cluster/liveTopicWatcher";

/** Small display parts shared by the instance viewers of the Cluster page. */

const STATE_TONES: Record<string, "ok" | "run" | "warn" | "bad" | "idle"> = {
  online: "ok",
  running: "run",
  leased: "run",
  succeeded: "ok",
  queued: "idle",
  draining: "warn",
  superseded: "idle",
  offline: "idle",
  cancelled: "idle",
  failed: "bad",
};

export function StateChip({ state }: { state: string }) {
  return <span className={`instances-chip instances-chip--${STATE_TONES[state] ?? "idle"}`}>{state}</span>;
}

export function KindChip({ children }: { children: ReactNode }) {
  return <span className="instances-chip instances-chip--kind">{children}</span>;
}

export function ProgressBar({ progress, label }: { progress: number | null; label?: string }) {
  const percent = progress === null ? null : Math.round(Math.min(1, Math.max(0, progress)) * 100);
  return (
    <div className="instances-progress" role="progressbar" aria-label={label ?? "Progress"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
      <span className="instances-progress-bar">
        <span className="instances-progress-fill" style={{ width: `${percent ?? 0}%` }} />
      </span>
      <span className="instances-progress-text">{percent === null ? "no progress reported" : `${percent}%`}</span>
    </div>
  );
}

/** What to say when a topic has no data to show yet, or lost its feed. */
export function TopicNotice({ topic, noun }: { topic: LiveTopicState<unknown>; noun: string }) {
  if (topic.status === "error") {
    return (
      <p className="instances-notice instances-notice--bad" role="alert">
        {topic.error ?? `The control node refused the ${noun}.`}
      </p>
    );
  }
  if (topic.status === "offline") {
    return (
      <p className="instances-notice instances-notice--warn" role="status">
        The live channel is down. The last {noun} stays on screen and updates again once the connection returns.
      </p>
    );
  }
  if (topic.status === "waiting") {
    return (
      <p className="instances-notice" role="status">
        Waiting for the {noun} from the control node.
      </p>
    );
  }
  if (topic.error) {
    return (
      <p className="instances-notice instances-notice--warn" role="status">
        {topic.error}
      </p>
    );
  }
  return null;
}
