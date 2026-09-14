import { usePlaybackStore } from "../../domain/playback/playbackStore";
import { BasicActorInfoPanel } from "../monitor/BasicActorInfoPanel";
import { ActorVisibilityPanel } from "./ActorVisibilityPanel";
import { SceneGenerationPaneViewSelect } from "./SceneGenerationPaneViewSelect";

/**
 * Monitor output for the scene shown on the scene generation page, whether it was
 * generated, picked from batch results, or loaded from disk. The backend runs every
 * such scene through the active monitor (live or empty) before sending it.
 */
export function SceneMonitorPreview() {
  const scene = usePlaybackStore((s) => s.latestGeneratedScene?.scene ?? null);
  const waitingForMonitor = usePlaybackStore((s) => s.pendingSceneMonitorRequestId !== null);

  return (
    <aside className="right-pane right-pane-trajectory">
      <SceneGenerationPaneViewSelect />
      <div className="right-trajectory-column-scroll">
        {waitingForMonitor ? <p className="meta">Waiting for the monitor result…</p> : null}
        <ActorVisibilityPanel stream="animation" />
        <BasicActorInfoPanel stream="animation" frame={scene} />
      </div>
    </aside>
  );
}
