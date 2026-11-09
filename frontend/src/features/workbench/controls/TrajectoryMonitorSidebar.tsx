import { useEffect, useMemo, useRef } from "react";
import "./simulationPanel.css";
import { useUiStore, type TrajectoryStream } from "../../../app/uiStore";
import { usePersistedState } from "../../../app/usePersistedState";
import { IconButton } from "../../../components/IconButton";
import { saveBlob } from "../../../components/saveBlob";
import { DownloadIcon, PanelRightCloseIcon } from "../../../components/icons";
import { useShownPlayback } from "../../../domain/playback/playbackContext";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { MetricsView } from "../metrics/MetricsView";
import { pickDefaultRelationId } from "../metrics/metricsRelations";
import { BasicActorInfoPanel } from "../monitor/BasicActorInfoPanel";
import { WorkbenchPairCards } from "../monitor/WorkbenchEncounterPanels";

function exportTrajectoryFrames(stream: "preview" | "simulation", scenarioId: string | null, frames: SimulationFrame[]) {
  const sortedFrames = [...frames].sort((a, b) => a.timestamp - b.timestamp);
  const payload = {
    stream,
    scenarioId,
    exportedAt: new Date().toISOString(),
    frameCount: sortedFrames.length,
    frames: sortedFrames,
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  saveBlob(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }), `${stream}_trajectory_${stamp}.json`);
}

const STREAM_LABELS: Record<TrajectoryStream, string> = { animation: "Preview", simulation: "Simulation" };

/**
 * The monitoring panel beside the canvas: one stream at a time (the planned preview, or the
 * simulation once it has frames), as live data (pairs, frame data) or charts. The layers
 * are set on the canvas itself.
 */
export function TrajectoryMonitorSidebar({ previewOnly = false }: { previewOnly?: boolean }) {
  const monitorPanelView = useUiStore((s) => s.monitorPanelView);
  const setMonitorPanelView = useUiStore((s) => s.setMonitorPanelView);
  const selectedMetricsRelationId = useUiStore((s) => s.selectedMetricsRelationId);
  const setSelectedMetricsRelationId = useUiStore((s) => s.setSelectedMetricsRelationId);
  const setRightPaneVisible = useUiStore((s) => s.setRightPaneVisible);
  const activeScenarioId = useShownPlayback((s) => s.activeScenarioId);
  const previewFrames = useShownPlayback((s) => s.frames);
  const simulationFrames = useShownPlayback((s) => s.simulationFrames);
  const [chosenStream, setChosenStream] = usePersistedState<TrajectoryStream>("monitor-panel-stream", "animation");

  const hasSimulation = !previewOnly && simulationFrames.length > 0;
  const stream: TrajectoryStream = hasSimulation ? chosenStream : "animation";

  // A run that starts producing frames is what the user wants to see.
  const hadSimulation = useRef(hasSimulation);
  useEffect(() => {
    if (hasSimulation && !hadSimulation.current) {
      setChosenStream("simulation");
    }
    hadSimulation.current = hasSimulation;
  }, [hasSimulation, setChosenStream]);

  // The stores keep both streams sorted by time.
  const sortedFrames = stream === "simulation" ? simulationFrames : previewFrames;

  return (
    <aside className="right-pane right-pane-trajectory">
      <header className="right-pane-toolbar">
        <div className="scene-gen-tabs right-pane-tabs" role="tablist" aria-label="Monitoring panel view">
          {(
            [
              ["runtime_data", "Live data"],
              ["overall_analysis", "Charts"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={monitorPanelView === id}
              className={`scene-gen-tab${monitorPanelView === id ? " active" : ""}`}
              onClick={() => setMonitorPanelView(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <IconButton label="Hide monitoring panel" icon={<PanelRightCloseIcon />} onClick={() => setRightPaneVisible(false)} />
      </header>
      <div className="monitor-stream-bar">
        {hasSimulation ? (
          <div className="monitor-stream-switch" role="radiogroup" aria-label="Stream shown">
            {(["animation", "simulation"] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={stream === option}
                className={`monitor-stream-option${stream === option ? " active" : ""}`}
                onClick={() => setChosenStream(option)}
              >
                {STREAM_LABELS[option]}
              </button>
            ))}
          </div>
        ) : (
          <span className="meta">{STREAM_LABELS.animation}: the planned trajectory</span>
        )}
        <IconButton
          label={`Export the ${stream === "simulation" ? "simulation" : "preview"} frames (JSON)`}
          icon={<DownloadIcon />}
          disabled={sortedFrames.length === 0}
          onClick={() => exportTrajectoryFrames(stream === "simulation" ? "simulation" : "preview", activeScenarioId, sortedFrames)}
        />
      </div>
      <div className="right-trajectory-column-scroll">
        {monitorPanelView === "runtime_data" ? (
          <>
            <WorkbenchPairCards stream={stream} />
            <BasicActorInfoPanel stream={stream} />
          </>
        ) : (
          <MetricsCharts frames={sortedFrames} relationId={selectedMetricsRelationId} onRelationIdChange={setSelectedMetricsRelationId} />
        )}
      </div>
    </aside>
  );
}

/** The Charts tab: the only part of the panel that follows the play head, so the rest does not re-render every frame. */
function MetricsCharts({
  frames,
  relationId,
  onRelationIdChange,
}: {
  frames: SimulationFrame[];
  relationId: string | null;
  onRelationIdChange: (id: string) => void;
}) {
  const cursor = useShownPlayback((s) => (s.frames.length > 0 || s.simulationFrames.length > 0 ? s.playbackCursor : null));
  const seek = useShownPlayback((s) => s.seek);
  const defaultRelation = useMemo(() => pickDefaultRelationId(frames), [frames]);
  return <MetricsView frames={frames} cursor={cursor} relationId={relationId ?? defaultRelation} onRelationIdChange={onRelationIdChange} onSeek={seek} />;
}
