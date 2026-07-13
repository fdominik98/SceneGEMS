import type { TrajectoryStream } from "../../app/uiStore";
import { useUiStore } from "../../app/uiStore";
import { usePlaybackStore } from "../../domain/playback/playbackStore";

interface ActorVisibilityPanelProps {
  /** Which trajectory column this panel belongs to. */
  stream: TrajectoryStream;
}

export function ActorVisibilityPanel({ stream }: ActorVisibilityPanelProps) {
  const previewOverlays = useUiStore((s) => s.previewOverlays);
  const simulationOverlays = useUiStore((s) => s.simulationOverlays);
  const setPreviewOverlay = useUiStore((s) => s.setPreviewOverlay);
  const setSimulationOverlay = useUiStore((s) => s.setSimulationOverlay);
  const hidePreviewStream = useUiStore((s) => s.hidePreviewStream);
  const hideSimulationStream = useUiStore((s) => s.hideSimulationStream);
  const setHidePreviewStream = useUiStore((s) => s.setHidePreviewStream);
  const setHideSimulationStream = useUiStore((s) => s.setHideSimulationStream);

  const hasSimulationTrajectory = usePlaybackStore((s) => s.hasSimulationTrajectoryChunk);

  const isPreview = stream === "animation";
  const overlays = isPreview ? previewOverlays : simulationOverlays;
  const setOverlay = isPreview ? setPreviewOverlay : setSimulationOverlay;

  return (
    <details className="panel panel-collapsible collapsible-section">
      <summary>
        <h3>{isPreview ? "Preview" : "Simulation"} layers</h3>
      </summary>
      {isPreview ? (
        <label className="check">
          <input
            type="checkbox"
            checked={!hidePreviewStream}
            onChange={(event) => setHidePreviewStream(!event.target.checked)}
          />
          Show preview layers on map
        </label>
      ) : (
        <label className="check">
          <input
            type="checkbox"
            checked={!hideSimulationStream}
            disabled={!hasSimulationTrajectory}
            onChange={(event) => setHideSimulationStream(!event.target.checked)}
          />
          Show simulation layers on map
          {!hasSimulationTrajectory ? " (no simulation data yet)" : ""}
        </label>
      )}
      <p className="meta">Layer toggles for the {isPreview ? "preview" : "simulation"} trajectory.</p>
      {(
        [
          ["dot", "Dot"],
          ["velocity", "Velocity"],
          ["safetyRadius", "Safety radius ring"],
          ["trajectory", "Trajectory"],
          ["safetyDomain", "Safety Domains"],
        ] as const
      ).map(([key, label]) => (
        <label className="check" key={key}>
          <input
            type="checkbox"
            checked={overlays[key]}
            onChange={(event) => setOverlay(key, event.target.checked)}
          />
          {label}
        </label>
      ))}
    </details>
  );
}
