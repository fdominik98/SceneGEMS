import { useMemo } from "react";
import type { ObservableInstance } from "../../../domain/cluster/observableInstances";
import { useObservedInstance } from "../../../domain/cluster/useObservedInstance";
import { EncounterView } from "./encounterView";
import { trajectoryPreviewFrames } from "../../../domain/cluster/observeFrames";
import { TopicNotice } from "./StatusParts";
import { ViewerHeader } from "./ViewerHeader";

/** A trajectory generation pool instance: the latest search preview's paths over time, and the verdict of the final result. */
export function TrajectoryViewer({ instance }: { instance: ObservableInstance }) {
  const { state: topic } = useObservedInstance(instance.topic);
  const preview = topic.data?.trajectoryPreview ?? null;
  const converted = useMemo(() => trajectoryPreviewFrames(preview), [preview]);
  const timeStep = converted.frames[0]?.timeStep ?? null;

  return (
    <div className="instances-viewer">
      <ViewerHeader instance={instance} topic={topic} />
      <TopicNotice topic={topic} noun="instance" />
      {topic.status === "live" && preview === null && (
        <p className="instances-empty" role="status">
          No preview yet. This instance sends previews while a trajectory search runs on it.
        </p>
      )}
      {preview && (
        <>
          <div className="instances-sample-flags">
            <span className={`instances-flag ${preview.final ? "instances-flag--ok" : "instances-flag--run"}`}>{preview.final ? "final result" : "search preview"}</span>
            {preview.final && preview.valid !== null && preview.valid !== undefined && (
              <span className={`instances-flag ${preview.valid ? "instances-flag--ok" : "instances-flag--bad"}`}>{preview.valid ? "valid" : "not valid"}</span>
            )}
            {preview.final && preview.complete !== null && preview.complete !== undefined && (
              <span className={`instances-flag ${preview.complete ? "instances-flag--ok" : "instances-flag--warn"}`}>
                {preview.complete ? "complete path" : "incomplete path"}
              </span>
            )}
            <span className="meta">
              request <code>{preview.request_id}</code>, {converted.frames.length} {converted.frames.length === 1 ? "scene" : "scenes"}
            </span>
          </div>
          {preview.final && preview.error_message && <p className="instances-notice instances-notice--bad">{preview.error_message}</p>}
          {converted.error && <p className="instances-notice instances-notice--warn">{converted.error}</p>}
          <EncounterView frames={converted.frames} timeStep={timeStep} title="Planned paths" />
        </>
      )}
    </div>
  );
}
