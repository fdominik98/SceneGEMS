import type { ReactNode } from "react";
import type { InstanceTopicState } from "../../../domain/cluster/liveTopics";
import type { LiveTopicState } from "../../../domain/cluster/liveTopicWatcher";
import type { ObservableInstance } from "../../../domain/cluster/observableInstances";
import { KindChip, ProgressBar, StateChip } from "./StatusParts";

const KIND_LABELS = {
  scene_generation: "scene generation",
  trajectory_generation: "trajectory search",
  simulation: "simulation",
  monitoring: "monitoring",
} as const;

/** The title row of a viewer: the instance, its kind and state from the snapshot, and the progress it reports. */
export function ViewerHeader({
  instance,
  topic,
  children,
}: {
  instance: ObservableInstance;
  topic: LiveTopicState<InstanceTopicState>;
  children?: ReactNode;
}) {
  const data = topic.data;
  const kind = data?.info.kind ?? instance.kind;
  const label = KIND_LABELS[kind as keyof typeof KIND_LABELS] ?? kind;
  return (
    <header className="instances-viewer-head">
      <div className="instances-viewer-title">
        <h3>{instance.label}</h3>
        <span className="meta">
          {instance.workerNodeId} / <code>{instance.instance}</code>
        </span>
      </div>
      <div className="instances-viewer-chips">
        <KindChip>{label}</KindChip>
        <StateChip state={data?.state ?? instance.state} />
        <span className={`instances-live-dot${topic.status === "live" ? " instances-live-dot--on" : ""}`} title={topic.status === "live" ? "Observing" : topic.status}>
          {topic.status === "live" ? "observing" : topic.status}
        </span>
      </div>
      {data && (data.message || data.progress !== null) && (
        <div className="instances-viewer-progress">
          {data.progress !== null && <ProgressBar progress={data.progress} />}
          {data.message && <span className="meta">{data.message}</span>}
        </div>
      )}
      {children}
    </header>
  );
}
