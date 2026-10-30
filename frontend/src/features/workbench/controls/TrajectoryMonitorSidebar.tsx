import { useEffect, useMemo, useRef } from "react";
import "./simulationPanel.css";
import { useUiStore, type TrajectoryStream } from "../../../app/uiStore";
import { usePersistedState } from "../../../app/usePersistedState";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon, PanelRightCloseIcon } from "../../../components/icons";
import { useShownPlayback } from "../../../domain/playback/playbackContext";
import { framesAtOrBeforeCursor } from "../../../domain/playback/playbackFrameResolve";
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
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${stream}_trajectory_${stamp}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
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
  const playbackCursor = useShownPlayback((s) => s.playbackCursor);
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

  const frames = stream === "simulation" ? simulationFrames : previewFrames;
  const sortedFrames = useMemo(() => [...frames].sort((a, b) => a.timestamp - b.timestamp), [frames]);
  const metricsFrames = useMemo(() => framesAtOrBeforeCursor(sortedFrames, playbackCursor), [sortedFrames, playbackCursor]);
  const activeRelation = selectedMetricsRelationId ?? pickDefaultRelationId(metricsFrames);

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
          <MetricsView frames={metricsFrames} relationId={activeRelation} onRelationIdChange={setSelectedMetricsRelationId} />
        )}
      </div>
    </aside>
  );
}
