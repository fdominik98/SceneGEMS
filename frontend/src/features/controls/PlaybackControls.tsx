import { useCallback, useRef, useState } from "react";
import { useUiStore } from "../../app/uiStore";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import type { SimulationStreamControls } from "./types";
import { AnimationPlaybackControls } from "./AnimationPlaybackControls";
import {
  activateLiveMode,
  getLatestSimulationTimestamp,
  handleLivePlayback,
} from "./livePlayback";
import {
  SimulationInitControls,
  type SimulationInitControlsHandle,
} from "./SimulationInitControls";
import { MonitorControls } from "./MonitorControls";
import { RecordingControls } from "./RecordingControls";

interface Props {
  streamControls: SimulationStreamControls;
  colregsConstraintsContent: string;
}

function getSimulationStatusPresentation(
  status:
    | "running"
    | "starting"
    | "ready to start"
    | "agents are preparing"
    | "initializing"
    | "offline"
    | "not initialized"
): {
  label: string;
  tone:
    | "running"
    | "preparing"
    | "ready"
    | "offline"
    | "initializing"
    | "not-initialized"
    | "unknown";
} {
  switch (status) {
    case "running":
      return { label: "running", tone: "running" };
    case "starting":
      return { label: "starting", tone: "preparing" };
    case "agents are preparing":
      return { label: "agents are preparing", tone: "preparing" };
    case "initializing":
      return { label: "initializing", tone: "initializing" };
    case "ready to start":
      return { label: "agents are ready", tone: "ready" };
    case "offline":
      return { label: "No simulator is connected", tone: "offline" };
    case "not initialized":
      return { label: "not initialized", tone: "not-initialized" };
    default:
      return { label: "unknown", tone: "unknown" };
  }
}

export function PlaybackControls({ streamControls, colregsConstraintsContent }: Props) {
  const controlPanelMode = useUiStore((s) => s.controlPanelMode);
  const setControlPanelMode = useUiStore((s) => s.setControlPanelMode);

  const isPlaying = usePlaybackStore((s) => s.isPlaying);
  const followLatestPush = usePlaybackStore((s) => s.followLatestPush);
  const followSimulationLive = usePlaybackStore((s) => s.followSimulationLive);
  const simulationStatus = usePlaybackStore((s) => s.simulationStatus);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const warapsStatus = usePlaybackStore((s) => s.warapsStatus);
  const latestSimulationTimestamp = getLatestSimulationTimestamp(simulationFrames);
  const simulationStatusUi = getSimulationStatusPresentation(simulationStatus);
  const isSimulationStatusUnknownOrOffline =
    simulationStatus === "offline" ||
    simulationStatus === "not initialized" ||
    simulationStatus === "initializing";
  const canStartSimulation =
    simulationStatus === "ready to start" && !isSimulationStatusUnknownOrOffline;
  const areSimulationControlsDisabled = isSimulationStatusUnknownOrOffline;

  const simInitRef = useRef<SimulationInitControlsHandle>(null);
  const [simInitVesselCount, setSimInitVesselCount] = useState(0);
  const onSimInitVesselCount = useCallback((n: number) => {
    setSimInitVesselCount(n);
  }, []);
  const initializeSimulationDisabled =
    !simulationInitialized || warapsStatus !== "connected";

  return (
    <div className="panel">
      <div className="toolbar-row control-panel-header">
        <h3>Control Panel</h3>
      </div>
      <div className="scene-gen-tabs" role="tablist" aria-label="Playback source">
        <button
          type="button"
          role="tab"
          aria-selected={controlPanelMode === "animation"}
          className={`scene-gen-tab${controlPanelMode === "animation" ? " active" : ""}`}
          onClick={() => setControlPanelMode("animation")}
        >
          Animation
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={controlPanelMode === "simulation"}
          className={`scene-gen-tab${controlPanelMode === "simulation" ? " active" : ""}`}
          onClick={() => setControlPanelMode("simulation")}
        >
          Simulation
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={controlPanelMode === "monitor"}
          className={`scene-gen-tab${controlPanelMode === "monitor" ? " active" : ""}`}
          onClick={() => setControlPanelMode("monitor")}
        >
          Monitor
        </button>
      </div>

      {controlPanelMode === "simulation" ? (
        <div className="simulation-panel-status-bar simulation-panel-status-bar--below-tabs">
          <span className="meta simulation-status-heading">Simulation status</span>
          <span className={`simulation-status-label simulation-status-label--inline ${simulationStatusUi.tone}`}>
            {simulationStatusUi.label}
          </span>
          <span className="simulation-status-sep" aria-hidden="true">
            |
          </span>
          <span className="meta simulation-panel-status-meta">
            Buffered frames: {simulationFrames.length}
          </span>
        </div>
      ) : null}

      {controlPanelMode === "animation" ? (
        <div className="animation-control-stack">
          <AnimationPlaybackControls
            seek={streamControls.seek}
            setSpeed={streamControls.setSpeed}
          />

          <section className="animation-control-group" aria-label="Record and replay controls">
            <RecordingControls />
          </section>
        </div>
      ) : controlPanelMode === "simulation" ? (
        <div className="simulation-control-stack">
          <div className="toolbar-row simulation-actions-toolbar">
            <button
              className="primary-btn"
              type="button"
              disabled={initializeSimulationDisabled}
              onClick={() => simInitRef.current?.initializeSimulation()}
            >
              Initialize Simulation
            </button>
            <button
              type="button"
              onClick={() => {
                streamControls.startSimulation();
                activateLiveMode({ followSimulationLive });
              }}
              disabled={!canStartSimulation}
            >
              Start
            </button>
            <button type="button" onClick={streamControls.resetSimulation}>
              Reset Simulation
            </button>
            <button
              className={`live-btn${followLatestPush && !isPlaying ? " active" : ""}`}
              type="button"
              onClick={() =>
                handleLivePlayback({
                  liveTimestamp: latestSimulationTimestamp,
                  followSimulationLive,
                })
              }
              disabled={latestSimulationTimestamp === null || areSimulationControlsDisabled}
            >
              Live
            </button>
            <button
              type="button"
              onClick={() => simInitRef.current?.generateSimulationWorld()}
              disabled={simInitVesselCount === 0}
              title={
                simInitVesselCount === 0
                  ? "Load a scenario to generate vessel physics models"
                  : undefined
              }
            >
              Generate Vessel Physics Models
            </button>
          </div>
          <p className="meta simulation-actions-hint">
            Initialize when scenario is ready and WARA-PS is connected. Vessels in table:{" "}
            {simInitVesselCount}
          </p>

          <SimulationInitControls
            ref={simInitRef}
            streamControls={streamControls}
            onScenarioVesselCount={onSimInitVesselCount}
          />
        </div>
      ) : (
        <MonitorControls
          streamControls={streamControls}
          colregsConstraintsContent={colregsConstraintsContent}
        />
      )}
    </div>
  );
}
