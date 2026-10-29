import { useCallback, useEffect, useMemo, useState } from "react";
import type { useSimulationWorkflow } from "../../../domain/simulation/useSimulationWorkflow";
import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../../../domain/playback/playbackStore";
import {
  buildFramesFromTrajectoryData,
  formatScenarioJsonForExport,
} from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import {
  TRAJECTORY_GENERATION_PARAM_DEFAULTS,
  TRAJECTORY_GENERATORS,
  toParamsWire,
  useTrajectoryGenerationStore,
  type TrajectoryGenerationParams,
  type TrajectoryGenerationTab,
} from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import {
  describeTrajectoryRun,
  summarizeTrajectoryResult,
  warnAboutTrajectoryRun,
} from "../../../domain/trajectoryGeneration/summarizeTrajectoryResult";
import type { TrajectoryGeneratorWire } from "../../../domain/simulation/wireTypes";
import { Disclosure } from "../../../components/Disclosure";
import { AnimationPlaybackControls } from "./AnimationPlaybackControls";
import { TRAJECTORY_GENERATION_JOB } from "../cluster/workbenchJobs";
import { describeResources } from "../cluster/workbenchResources";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { PageInputPanel } from "../pages/PageInputPanel";
import { inputOfFile, sceneOfDocument, sceneOfScenePage, setTrajectoryInput, trajectoriesOfTrajectoryPage } from "../pages/pageHandoff";
import { useScenePageStore, useTrajectoryPageStore } from "../pages/pageStore";

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
  const setTrajectoryPreviewFrames = useTrajectoryPlaybackStore((s) => s.setTrajectoryPreviewFrames);
  const input = useTrajectoryPageStore((s) => s.input);
  // The scene page shows a valid scene to take in one click.
  const scenePageHasScene = useScenePlaybackStore((s) => s.latestGeneratedScene?.valid === true && !!s.latestGeneratedScene.evaluationData);
  const scenePageOutput = useScenePageStore((s) => s.output);

  const handoffScene = useTrajectoryGenerationStore((s) => s.handoffScene);
  const params = useTrajectoryGenerationStore((s) => s.params);
  const includeMonitorResults = useTrajectoryGenerationStore((s) => s.includeMonitorResults);
  const generator = useTrajectoryGenerationStore((s) => s.generator);
  const timespan = useTrajectoryGenerationStore((s) => s.timespan);
  const status = useTrajectoryGenerationStore((s) => s.status);
  const iteration = useTrajectoryGenerationStore((s) => s.iteration);
  const errorMessage = useTrajectoryGenerationStore((s) => s.errorMessage);
  const resultValid = useTrajectoryGenerationStore((s) => s.resultValid);
  const resultScenarioJson = useTrajectoryGenerationStore((s) => s.resultScenarioJson);
  const resultComplete = useTrajectoryGenerationStore((s) => s.resultComplete);
  const storedTab = useTrajectoryGenerationStore((s) => s.activeTab);
  // A tab persisted before the monitor tab moved to the Connections page falls back to Generate.
  const activeTab = TABS.some((t) => t.id === storedTab) ? storedTab : "generate";
  const setActiveTab = useTrajectoryGenerationStore((s) => s.setActiveTab);
  const setParam = useTrajectoryGenerationStore((s) => s.setParam);
  const setIncludeMonitorResults = useTrajectoryGenerationStore(
    (s) => s.setIncludeMonitorResults
  );
  const setGenerator = useTrajectoryGenerationStore((s) => s.setGenerator);
  const setTimespan = useTrajectoryGenerationStore((s) => s.setTimespan);
  const resetParams = useTrajectoryGenerationStore((s) => s.resetParams);

  const [localError, setLocalError] = useState<string | null>(null);

  const running = status === "running";
  const straight = generator === "straight";
  const timespanValid = Number.isFinite(timespan) && timespan > 0;
  const connected = streamStatus === "connected";
  // Trajectories are planned by a job on the active cluster: without a node that plans, nothing runs.
  const trajectoryResources = streamControls.clusterResources(TRAJECTORY_GENERATION_JOB);
  const canGenerate =
    trajectoryResources.blocker === null && !running && input !== null && handoffScene?.valid === true && (!straight || timespanValid);
  const hasResult = status === "done" && resultValid && !!resultScenarioJson;

  // Restore the last generated trajectory as the on-canvas preview after a reload (the page's
  // playback store keeps it while the app runs). A live run manages the preview frames itself.
  useEffect(() => {
    if (running || !resultScenarioJson || useTrajectoryPlaybackStore.getState().frames.length > 0) {
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

  // Draw the loaded initial scene on the canvas, so loading one is visible rather than
  // only being announced in the text below. A single scene is a one-frame preview.
  // Skipped while a run is in flight and whenever there is a generated trajectory to
  // show, since either of those owns the canvas and is the more informative picture.
  useEffect(() => {
    if (running || resultScenarioJson || !handoffScene?.scene) {
      return;
    }
    setTrajectoryPreviewFrames([handoffScene.scene]);
  }, [handoffScene, resultScenarioJson, running, setTrajectoryPreviewFrames]);

  // What the finished run actually produced. The backend calls any run of more than one
  // scene valid, so this is what distinguishes a completed plan from one that stopped
  // after two steps.
  const runSummary = useMemo(() => {
    if (running || !resultScenarioJson) {
      return null;
    }
    try {
      const raw = JSON.parse(resultScenarioJson);
      return summarizeTrajectoryResult(raw, buildFramesFromTrajectoryData(raw));
    } catch {
      return null;
    }
  }, [resultScenarioJson, running]);

  const runWarning = runSummary ? warnAboutTrajectoryRun(runSummary) : null;
  // The search reports a partial best path as a result too; only an explicit false says so.
  const partialPlan = resultComplete === false;
  // The straight generator takes the time step only; the rest of the form is the search's.
  const paramFields = straight ? PARAM_FIELDS.filter(({ key }) => key === "timeStep") : PARAM_FIELDS;

  const handleGenerate = useCallback(() => {
    if (!handoffScene?.valid || input === null) {
      return;
    }
    setLocalError(null);
    streamControls.generateTrajectories(crypto.randomUUID(), {
      input,
      scenarioContent: formatScenarioJsonForExport(handoffScene.evaluationData, handoffScene.scene),
      colregsConstraintsContent,
      params: toParamsWire(params, includeMonitorResults, generator, timespan),
    });
  }, [
    colregsConstraintsContent,
    generator,
    handoffScene,
    includeMonitorResults,
    input,
    params,
    streamControls,
    timespan,
  ]);

  // The shown trajectories become the simulation page's input, and the page opens.
  const handleLoadForSimulation = useCallback(() => {
    const handoff = trajectoriesOfTrajectoryPage();
    if (handoff === null) {
      return;
    }
    void streamControls.setSimulationInput(handoff.input, handoff.content, { colregsConstraintsContent });
    onNavigateToSimulation();
  }, [colregsConstraintsContent, onNavigateToSimulation, streamControls]);

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
    ? straight
      ? "Generating straight trajectories…"
      : `Planning… iteration ${iteration}`
    : status === "done"
      ? resultValid
        ? partialPlan || runWarning
          ? "Stopped early - partial trajectory"
          : "Planned trajectory ready"
        : "Finished without a usable trajectory"
      : status === "error"
        ? "Trajectory generation failed"
        : "Idle";

  return (
    <div className="panel">
      <div className="control-panel-heading">
        <div>
          <p className="control-panel-eyebrow">Step 2 of 3</p>
          <h3>Trajectory Generation</h3>
        </div>
        <div className="control-panel-status">
          <span className="meta" role="status">
            {statusLabel}
          </span>
          <span className="meta" title="Trajectory generation runs as jobs on the active cluster">
            Cluster: {describeResources(trajectoryResources)}
          </span>
        </div>
      </div>
      {trajectoryResources.blocker !== null && (
        <p className="meta resource-blocker" role="status">
          {trajectoryResources.blocker}
        </p>
      )}

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
          <PageInputPanel
            title="Input scene"
            input={handoffScene ? input : null}
            emptyText="none yet. Take the scene of the Scene Generation page, an output of Campaign History or a scenario file."
            previousLabel="Use the scene of the Scene Generation page"
            previousAvailable={scenePageHasScene}
            onUsePrevious={() => {
              const handoff = sceneOfScenePage(scenePageOutput?.ref === null ? scenePageOutput.label : null);
              if (handoff !== null) {
                setTrajectoryInput(handoff.input, handoff.scene);
              }
            }}
            historyStep="scene_generation"
            client={streamControls.operatorClient}
            onPickHistory={(picked, document) => setTrajectoryInput(picked, sceneOfDocument(document))}
            onPickFile={async (file) => setTrajectoryInput(inputOfFile(file.name), sceneOfDocument(JSON.parse(await file.text())))}
            disabled={running}
          />
          <PageEntryStatus store={useTrajectoryPageStore} />
          <div className="toolbar-row" style={{ alignItems: "flex-end" }}>
            <label className="field">
              <span>Generator</span>
              <select
                value={generator}
                disabled={running}
                onChange={(e) => setGenerator(e.target.value as TrajectoryGeneratorWire)}
                aria-label="Trajectory generator"
              >
                {TRAJECTORY_GENERATORS.map(({ id, label }) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {straight && (
              <label className="toolbar-timeout">
                <span className="toolbar-timeout-label">Timespan (s)</span>
                <input
                  className="toolbar-timeout-input"
                  type="number"
                  min={1}
                  step={1}
                  value={timespan}
                  disabled={running}
                  onChange={(e) => {
                    const value = Number(e.target.value);
                    if (Number.isFinite(value)) {
                      setTimespan(value);
                    }
                  }}
                  aria-label="Timespan (s)"
                />
              </label>
            )}
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
          <Disclosure
            id="trajectory:about-generator"
            variant="link"
            headingLevel={null}
            title="About this generator"
            openTitle="Hide generator details"
          >
            {straight
              ? "Every vessel goes straight on from its initial state for the timespan. Nothing is searched, so the result is ready at once and always complete."
              : "Searches for compliant manoeuvres, guided by the COLREGS monitor. Tune it on the Advanced settings tab."}
          </Disclosure>

          {status === "done" && runSummary && (
            <div className="trajectory-run-report" role="status">
              <p className="meta">{describeTrajectoryRun(runSummary)}</p>
              {resultComplete !== null && (
                <p className={`meta${partialPlan ? " warning" : ""}`} role={partialPlan ? "alert" : undefined}>
                  {partialPlan
                    ? "Partial plan: the search ended without reaching a complete trajectory, so this is the best path it found."
                    : "Complete plan."}
                </p>
              )}
              {runWarning && (
                <p className="meta warning" role="alert">
                  {runWarning}
                </p>
              )}
            </div>
          )}
          {status === "done" && !resultValid && (
            <p className="meta warning" role="alert">
              The planner returned no usable trajectory. It could not find a single
              compliant step from this scene.
            </p>
          )}
          {(localError || errorMessage) && (
            <p className="error" role="alert">
              {localError ?? errorMessage}
            </p>
          )}

          <section className="animation-control-group" aria-label="Planned trajectory actions">
            <h4 className="animation-control-group-title">Next: use the planned trajectory</h4>
            <div className="toolbar-row">
              <button
                type="button"
                className={hasResult ? "primary-btn accent" : undefined}
                disabled={
                  running ||
                  simulationInitializing ||
                  !connected ||
                  !hasResult
                }
                onClick={handleLoadForSimulation}
              >
                Next: Simulation
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
                ? partialPlan || runWarning
                  ? "The partial trajectory is shown on the canvas and can still be simulated and exported."
                  : "The trajectory is shown on the canvas. Next: Simulation makes it the input of the simulation page."
                : "Generate a trajectory, or open one from Campaign History, to enable simulation and export."}
            </p>
          </section>

        </div>
      ) : activeTab === "advanced" ? (
        <div className="animation-control-stack">
          <section
            className="animation-control-group"
            aria-label={straight ? "Straight generator parameters" : "Advanced RRT parameters"}
          >
            <h4 className="animation-control-group-title">
              {straight ? "Straight parameters" : "RRT parameters"}
            </h4>
            <div className="toolbar-row trajectory-advanced-params">
              {paramFields.map(({ key, label, step }) => (
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
            {straight ? (
              <p className="meta">
                The straight generator samples every vessel at this step for the timespan set on
                the Generate tab. The search settings of the monitor-driven RRT do not apply.
              </p>
            ) : (
              <>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={includeMonitorResults}
                    disabled={running}
                    onChange={(e) => setIncludeMonitorResults(e.target.checked)}
                  />
                  Include monitor results in previews
                </label>
                <Disclosure
                  id="trajectory:about-monitor-results"
                  variant="link"
                  headingLevel={null}
                  title="What does this do?"
                  openTitle="Hide explanation"
                >
                  On, the planner attaches the COLREGS monitor output it recorded for every scene,
                  which fills the side panel and draws the domains on the canvas while planning. Off
                  keeps previews small on long runs with many encounters: the canvas still shows the
                  trajectory, but without monitor data.
                </Disclosure>
                <div className="toolbar-row">
                  <button type="button" disabled={running} onClick={resetParams}>
                    Reset to defaults ({TRAJECTORY_GENERATION_PARAM_DEFAULTS.timeStep}s step)
                  </button>
                </div>
                <Disclosure
                  id="trajectory:about-termination"
                  variant="link"
                  headingLevel={null}
                  title="When does the search stop?"
                  openTitle="Hide explanation"
                >
                  It stops on Stop, the timeout, or the max-iteration cap, whichever comes first. The
                  preview interval controls how often the best trajectory so far is streamed to the
                  canvas.
                </Disclosure>
              </>
            )}
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
                ? "Previewing the last generated trajectory."
                : "No trajectory to preview yet."}
          </p>
        </div>
      )}
    </div>
  );
}
