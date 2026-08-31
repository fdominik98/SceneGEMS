import { useCallback, useRef, useState } from "react";
import type { useSimulationWorkflow } from "../../domain/simulation/useSimulationWorkflow";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import {
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "../../domain/sceneGeneration/parseEvaluationDataFile";
import {
  TRAJECTORY_GENERATION_PARAM_DEFAULTS,
  toParamsWire,
  useTrajectoryGenerationStore,
  type TrajectoryGenerationParams,
} from "../../domain/trajectoryGeneration/trajectoryGenerationStore";

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

export function TrajectoryGenerationControls({
  streamControls,
  colregsConstraintsContent,
  onNavigateToSimulation,
}: TrajectoryGenerationControlsProps) {
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const simulationInitializing = usePlaybackStore((s) => s.simulationInitializing);
  const handoffScene = useTrajectoryGenerationStore((s) => s.handoffScene);
  const handoffSourceName = useTrajectoryGenerationStore((s) => s.handoffSourceName);
  const params = useTrajectoryGenerationStore((s) => s.params);
  const status = useTrajectoryGenerationStore((s) => s.status);
  const iteration = useTrajectoryGenerationStore((s) => s.iteration);
  const errorMessage = useTrajectoryGenerationStore((s) => s.errorMessage);
  const resultValid = useTrajectoryGenerationStore((s) => s.resultValid);
  const resultScenarioJson = useTrajectoryGenerationStore((s) => s.resultScenarioJson);
  const setParam = useTrajectoryGenerationStore((s) => s.setParam);
  const resetParams = useTrajectoryGenerationStore((s) => s.resetParams);
  const setHandoffScene = useTrajectoryGenerationStore((s) => s.setHandoffScene);

  const [localError, setLocalError] = useState<string | null>(null);
  const sceneFileInputRef = useRef<HTMLInputElement | null>(null);

  const running = status === "running";
  const connected = streamStatus === "connected";
  const canGenerate = connected && !running && handoffScene?.valid === true;

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

  return (
    <div className="bottom-slot bottom-slot-controls">
      <div className="toolbar-row scene-generation-toolbar">
        <div className="scene-generation-trigger-group">
          <button
            className="primary-btn accent"
            type="button"
            disabled={!canGenerate}
            onClick={handleGenerate}
          >
            Generate Trajectories
          </button>
          <button type="button" disabled={!running} onClick={streamControls.stopTrajectoryGeneration}>
            Stop
          </button>
          <span className="meta">
            {running
              ? `Planning… iteration ${iteration}`
              : status === "done"
                ? resultValid
                  ? "Planned trajectory ready"
                  : "Finished without a usable trajectory"
                : status === "error"
                  ? "Trajectory generation failed"
                  : "Idle"}
          </span>
        </div>
        <div className="scene-scenario-actions">
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
          <button type="button" disabled={running} onClick={() => sceneFileInputRef.current?.click()}>
            Load Scenario File...
          </button>
          <button
            type="button"
            disabled={
              running ||
              simulationInitializing ||
              !connected ||
              status !== "done" ||
              !resultValid ||
              !resultScenarioJson
            }
            onClick={handleLoadForSimulation}
          >
            Load for Simulation
          </button>
        </div>
      </div>

      <details className="trajectory-advanced-params">
        <summary>Advanced parameters</summary>
        <div className="toolbar-row">
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
          <button type="button" disabled={running} onClick={resetParams}>
            Reset to defaults ({TRAJECTORY_GENERATION_PARAM_DEFAULTS.timeStep}s step)
          </button>
        </div>
      </details>

      <p className="meta">
        Initial scene:{" "}
        {handoffScene
          ? handoffSourceName
            ? `from file (${handoffSourceName})`
            : "from Scene Generation"
          : "none - load a valid scene on the Scene Generation page, or load a scenario file here"}
      </p>
      <p className="meta">
        Backend socket: <span className={`status-text ${streamStatus}`}>{streamStatus}</span>
      </p>
      {(localError || errorMessage) && (
        <p className="meta" role="alert">
          {localError ?? errorMessage}
        </p>
      )}
    </div>
  );
}
