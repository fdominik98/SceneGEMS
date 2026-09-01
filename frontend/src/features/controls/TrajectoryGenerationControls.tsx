import { useCallback, useEffect, useRef, useState } from "react";
import type { useSimulationWorkflow } from "../../domain/simulation/useSimulationWorkflow";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import {
  buildFramesFromTrajectoryData,
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "../../domain/sceneGeneration/parseEvaluationDataFile";
import {
  TRAJECTORY_GENERATION_PARAM_DEFAULTS,
  toParamsWire,
  useTrajectoryGenerationStore,
  type TrajectoryGenerationParams,
  type TrajectoryGenerationTab,
} from "../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { AnimationPlaybackControls } from "./AnimationPlaybackControls";

interface TrajectoryGenerationControlsProps {
  streamControls: ReturnType<typeof useSimulationWorkflow>;
  colregsConstraintsContent: string;
  onNavigateToSimulation: () => void;
}

const PARAM_FIELDS: { key: keyof TrajectoryGenerationParams; label: string; step?: number }[] = [
  { key: "timeStep", label: "Time step (s)" },
  { key: "timeout", label: "Timeout (s)" },
  { key: "maxIterations", label: "Max iterations" },
  { key: "goalSampleRate", label: "Goal sample rate" },
  { key: "bestLeafSampleRate", label: "Best-leaf sample rate" },
  { key: "maxLeafs", label: "Max leafs" },
  { key: "directionThreshold", label: "Direction threshold (m)", step: 0.1 },
  { key: "bestRandomNodesK", label: "Best random nodes K" },
  { key: "previewInterval", label: "Preview interval (iters)" },
];

const TABS: { id: TrajectoryGenerationTab; label: string }[] = [
  { id: "generate", label: "Generate" },
  { id: "advanced", label: "Advanced settings" },
  { id: "preview", label: "Preview" },
];

function downloadJson(text: string, fileName: string) {
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function TrajectoryGenerationControls({
  streamControls,
  colregsConstraintsContent,
  onNavigateToSimulation,
}: TrajectoryGenerationControlsProps) {
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const simulationInitializing = usePlaybackStore((s) => s.simulationInitializing);
  const setTrajectoryPreviewFrames = usePlaybackStore((s) => s.setTrajectoryPreviewFrames);

  const handoffScene = useTrajectoryGenerationStore((s) => s.handoffScene);
  const handoffSourceName = useTrajectoryGenerationStore((s) => s.handoffSourceName);
  const params = useTrajectoryGenerationStore((s) => s.params);
  const status = useTrajectoryGenerationStore((s) => s.status);
  const iteration = useTrajectoryGenerationStore((s) => s.iteration);
  const errorMessage = useTrajectoryGenerationStore((s) => s.errorMessage);
  const resultValid = useTrajectoryGenerationStore((s) => s.resultValid);
  const resultScenarioJson = useTrajectoryGenerationStore((s) => s.resultScenarioJson);
  const activeTab = useTrajectoryGenerationStore((s) => s.activeTab);
  const setActiveTab = useTrajectoryGenerationStore((s) => s.setActiveTab);
  const setParam = useTrajectoryGenerationStore((s) => s.setParam);
  const resetParams = useTrajectoryGenerationStore((s) => s.resetParams);
  const setHandoffScene = useTrajectoryGenerationStore((s) => s.setHandoffScene);

  const [localError, setLocalError] = useState<string | null>(null);
  const sceneFileInputRef = useRef<HTMLInputElement | null>(null);

  const running = status === "running";
  const connected = streamStatus === "connected";
  const canGenerate = connected && !running && handoffScene?.valid === true;
  const hasResult = status === "done" && resultValid && !!resultScenarioJson;

  // Restore the last generated trajectory as the on-canvas preview whenever the page
  // is (re)opened. A live run manages the preview frames itself.
  useEffect(() => {
    if (running || !resultScenarioJson) {
      return;
    }
    try {
      const frames = buildFramesFromTrajectoryData(JSON.parse(resultScenarioJson));
      if (frames.length > 0) {
        setTrajectoryPreviewFrames(frames);
      }
    } catch {
      /* ignore malformed persisted result */
    }
    // Run once on mount; deliberately not reacting to later changes here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGenerate = useCallback(() => {
    if (!handoffScene?.valid) {
      return;
    }
    setLocalError(null);
    const scenarioContent = formatScenarioJsonForExport(
      handoffScene.evaluationData,
      handoffScene.scene
    );
    streamControls.generateTrajectories(
      crypto.randomUUID(),
      scenarioContent,
      colregsConstraintsContent,
      toParamsWire(params)
    );
  }, [colregsConstraintsContent, handoffScene, params, streamControls]);

  const handleSceneFileSelected = useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        const { evaluationData, scene } = parseScenarioFile(text);
        setHandoffScene({ scene, evaluationData, valid: true }, file.name);
        setLocalError(null);
      } catch (error) {
        setLocalError(
          error instanceof Error ? error.message : "Failed to parse scenario file."
        );
      }
    },
    [setHandoffScene]
  );

  const handleLoadForSimulation = useCallback(() => {
    if (!resultScenarioJson) {
      return;
    }
    const file = new File([resultScenarioJson], "planned_trajectory.json", {
      type: "application/json",
    });
    void streamControls.loadScenarioFromFile(file);
    onNavigateToSimulation();
  }, [onNavigateToSimulation, resultScenarioJson, streamControls]);

  const handleExportTrajectory = useCallback(() => {
    if (!resultScenarioJson) {
      return;
    }
    try {
      downloadJson(
        JSON.stringify(JSON.parse(resultScenarioJson), null, 2),
        "planned_trajectory.json"
      );
    } catch {
      downloadJson(resultScenarioJson, "planned_trajectory.json");
    }
  }, [resultScenarioJson]);

  const statusLabel = running
    ? `Planning… iteration ${iteration}`
    : status === "done"
      ? resultValid
        ? "Planned trajectory ready"
        : "Finished without a usable trajectory"
      : status === "error"
        ? "Trajectory generation failed"
        : "Idle";

  return (
    <div className="panel">
      <div className="toolbar-row control-panel-header">
        <h3>Trajectory Generation</h3>
        <span className="meta">{statusLabel}</span>
      </div>

      <div className="scene-gen-tabs" role="tablist" aria-label="Trajectory generation">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activeTab === id}
            className={`scene-gen-tab${activeTab === id ? " active" : ""}`}
            onClick={() => setActiveTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "generate" ? (
        <div className="animation-control-stack">
          <section className="animation-control-group" aria-label="Trajectory generation run">
            <h4 className="animation-control-group-title">Run</h4>
            <div className="toolbar-row">
              <button
                className="primary-btn accent"
                type="button"
                disabled={!canGenerate}
                onClick={handleGenerate}
              >
                Generate Trajectories
              </button>
              <button
                type="button"
                disabled={!running}
                onClick={streamControls.stopTrajectoryGeneration}
              >
                Stop
              </button>
            </div>
            <p className="meta">
              Initial scene:{" "}
              {handoffScene
                ? handoffSourceName
                  ? `from file (${handoffSourceName})`
                  : "from Scene Generation"
                : "none - load a valid scene on the Scene Generation page, or load a scenario file here"}
            </p>
            <div className="toolbar-row">
              <input
                ref={sceneFileInputRef}
                type="file"
                accept="application/json,.json"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    void handleSceneFileSelected(file);
                  }
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                disabled={running}
                onClick={() => sceneFileInputRef.current?.click()}
              >
                Load Scenario File...
              </button>
            </div>
          </section>

          <section className="animation-control-group" aria-label="Planned trajectory actions">
            <h4 className="animation-control-group-title">Planned trajectory</h4>
            <div className="toolbar-row">
              <button
                type="button"
                disabled={
                  running ||
                  simulationInitializing ||
                  !connected ||
                  !hasResult
                }
                onClick={handleLoadForSimulation}
              >
                Load for Simulation
              </button>
              <button
                type="button"
                disabled={!resultScenarioJson}
                onClick={handleExportTrajectory}
              >
                Export Trajectory
              </button>
            </div>
            <p className="meta">
              {hasResult
                ? "The last generated trajectory is restored here and shown on the canvas."
                : "Generate or load a trajectory to enable simulation and export."}
            </p>
          </section>

          <p className="meta">
            Backend socket:{" "}
            <span className={`status-text ${streamStatus}`}>{streamStatus}</span>
          </p>
          {(localError || errorMessage) && (
            <p className="meta" role="alert">
              {localError ?? errorMessage}
            </p>
          )}
        </div>
      ) : activeTab === "advanced" ? (
        <div className="animation-control-stack">
          <section className="animation-control-group" aria-label="Advanced RRT parameters">
            <h4 className="animation-control-group-title">RRT parameters</h4>
            <div className="toolbar-row trajectory-advanced-params">
              {PARAM_FIELDS.map(({ key, label, step }) => (
                <label key={key} className="toolbar-timeout">
                  <span className="toolbar-timeout-label">{label}</span>
                  <input
                    className="toolbar-timeout-input"
                    type="number"
                    step={step ?? 1}
                    value={params[key]}
                    disabled={running}
                    onChange={(e) => {
                      const value = Number(e.target.value);
                      if (Number.isFinite(value)) {
                        setParam(key, value);
                      }
                    }}
                    aria-label={label}
                  />
                </label>
              ))}
            </div>
            <div className="toolbar-row">
              <button type="button" disabled={running} onClick={resetParams}>
                Reset to defaults ({TRAJECTORY_GENERATION_PARAM_DEFAULTS.timeStep}s step)
              </button>
            </div>
            <p className="meta">
              Terminates on Stop, the timeout, or the max-iteration cap - whichever
              comes first. Preview interval controls how often the best-so-far
              trajectory is streamed to the canvas.
            </p>
          </section>
        </div>
      ) : (
        <div className="animation-control-stack">
          <AnimationPlaybackControls
            seek={streamControls.seek}
            setSpeed={streamControls.setSpeed}
            title="Preview playback"
          />
          <p className="meta">
            {running
              ? `Previewing the best trajectory so far (iteration ${iteration}).`
              : hasResult
                ? "Previewing the last generated trajectory. COLREGS metrics in the side panel populate after Load for Simulation."
                : "No trajectory to preview yet."}
          </p>
        </div>
      )}
    </div>
  );
}
