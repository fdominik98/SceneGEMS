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
} from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import {
  describeTrajectoryRun,
  summarizeTrajectoryResult,
  warnAboutTrajectoryRun,
} from "../../../domain/trajectoryGeneration/summarizeTrajectoryResult";
import type { TrajectoryGeneratorWire } from "../../../domain/simulation/wireTypes";
import { Disclosure } from "../../../components/Disclosure";
import { saveBlob } from "../../../components/saveBlob";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon } from "../../../components/icons";
import { TRAJECTORY_GENERATION_JOB } from "../cluster/workbenchJobs";
import { describeResources } from "../cluster/workbenchResources";
import { EntrySeedField } from "../pages/EntrySeedField";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { PageInputPanel } from "../pages/PageInputPanel";
import { inputOfFile, sceneOfDocument, sceneOfScenePage, setTrajectoryInput, trajectoriesOfTrajectoryPage } from "../pages/pageHandoff";
import { useScenePageStore, useTrajectoryPageStore } from "../pages/pageStore";
import { NumberSetting, Setting, StepPanel, StepRow, type StepNotice, type StepStatus } from "../pages/StepPanel";
import { describeWhere, NO_INPUT_STATUS, readyStatus } from "../pages/stepWords";

interface TrajectoryGenerationControlsProps {
  streamControls: ReturnType<typeof useSimulationWorkflow>;
  colregsConstraintsContent: string;
  onNavigateToSimulation: () => void;
}

const PARAM_FIELDS: { key: keyof TrajectoryGenerationParams; label: string; unit?: string; integer?: boolean }[] = [
  { key: "timeStep", label: "Time step", unit: "s" },
  { key: "timeout", label: "Timeout", unit: "s", integer: true },
  { key: "maxIterations", label: "Max seed steps", integer: true },
  { key: "directionThreshold", label: "Rejoin tolerance", unit: "m" },
  { key: "bestRandomNodesK", label: "Leaves expanded per round", integer: true },
  { key: "previewInterval", label: "Preview every", unit: "seed steps", integer: true },
];

const GENERATOR_HINTS: Record<TrajectoryGeneratorWire, string> = {
  monitor_driven_rrt: "Follows a maneuvering corridor for every give-way vessel and repairs each step the COLREGS monitor fails with a short tree search. It stops on Stop, the timeout or the seed step cap.",
  straight: "Every vessel goes straight on from its initial state for the timespan: nothing is searched, so it is ready at once and always complete.",
};

function downloadJson(text: string, fileName: string) {
  saveBlob(new Blob([text], { type: "application/json" }), fileName);
}

/**
 * The trajectory page's panel: its input scene, the generator and its settings, and the
 * planned trajectory it shows, with the way on to the simulation page. Playback is in the
 * bar under the canvas.
 */
export function TrajectoryGenerationControls({
  streamControls,
  colregsConstraintsContent,
  onNavigateToSimulation,
}: TrajectoryGenerationControlsProps) {
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
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
  const setParam = useTrajectoryGenerationStore((s) => s.setParam);
  const setIncludeMonitorResults = useTrajectoryGenerationStore((s) => s.setIncludeMonitorResults);
  const setGenerator = useTrajectoryGenerationStore((s) => s.setGenerator);
  const setTimespan = useTrajectoryGenerationStore((s) => s.setTimespan);
  const resetParams = useTrajectoryGenerationStore((s) => s.resetParams);

  const [localError, setLocalError] = useState<string | null>(null);

  const running = status === "running";
  const straight = generator === "straight";
  const timespanValid = Number.isFinite(timespan) && timespan > 0;
  const connected = streamStatus === "connected";
  // Trajectories are planned by a job on the active cluster: without a worker node that plans, nothing runs.
  const trajectoryResources = streamControls.clusterResources(TRAJECTORY_GENERATION_JOB);
  const hasInput = input !== null && handoffScene?.valid === true;
  const canGenerate = trajectoryResources.blocker === null && !running && hasInput && (!straight || timespanValid);
  const hasResult = status === "done" && resultValid && !!resultScenarioJson;

  // After a reload the page's playback store is empty: draw the last planned trajectory, else the
  // input scene. From then on runs, loaded entries and new inputs draw for themselves
  // (`setTrajectoryInput`, `showEntryOutput.ts`), and Stop keeps the best path found so far.
  useEffect(() => {
    const generation = useTrajectoryGenerationStore.getState();
    if (generation.status === "running" || useTrajectoryPlaybackStore.getState().frames.length > 0) {
      return;
    }
    if (generation.resultScenarioJson) {
      try {
        const frames = buildFramesFromTrajectoryData(JSON.parse(generation.resultScenarioJson));
        if (frames.length > 0) {
          setTrajectoryPreviewFrames(frames);
          return;
        }
      } catch {
        // A malformed stored result: the input scene is drawn instead.
      }
    }
    if (generation.handoffScene?.scene) {
      setTrajectoryPreviewFrames([generation.handoffScene.scene]);
    }
  }, [setTrajectoryPreviewFrames]);

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
  // The planner reports its best path as a result too, when it ends early or still fails a rule; only an explicit false says so.
  const incompletePlan = resultComplete === false;
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
      downloadJson(JSON.stringify(JSON.parse(resultScenarioJson), null, 2), "planned_trajectory.json");
    } catch {
      downloadJson(resultScenarioJson, "planned_trajectory.json");
    }
  }, [resultScenarioJson]);

  const panelStatus: StepStatus = running
    ? { label: straight ? "Generating" : `Planning, seed step ${iteration}`, tone: "busy" }
    : status === "done"
      ? resultValid
        ? incompletePlan || runWarning
          ? { label: "Incomplete trajectory", tone: "warn" }
          : { label: "Trajectory ready", tone: "ok" }
        : { label: "No usable trajectory", tone: "error" }
      : status === "error"
        ? { label: "Failed", tone: "error" }
        : hasInput
          ? readyStatus("plan")
          : NO_INPUT_STATUS;

  const notices: StepNotice[] = [];
  if (trajectoryResources.blocker !== null) {
    notices.push({ text: trajectoryResources.blocker });
  }
  if (straight && !timespanValid) {
    notices.push({ text: "The straight generator needs a timespan above 0 s." });
  }

  // A disabled button says what it waits for: the input first, then what blocks the run elsewhere.
  const disabledReason = hasInput ? notices[0]?.text : "Take an input scene first";

  const runError = localError ?? errorMessage;

  return (
    <StepPanel
      page="trajectoryGeneration"
      title="Trajectory Generation"
      status={panelStatus}
      where={describeWhere(describeResources(trajectoryResources))}
      notices={notices}
      actions={
        running ? (
          <button type="button" onClick={streamControls.stopTrajectoryGeneration}>
            Stop
          </button>
        ) : (
          <button
            className="primary-btn accent"
            type="button"
            disabled={!canGenerate}
            title={canGenerate ? undefined : disabledReason}
            onClick={handleGenerate}
          >
            Generate trajectories
          </button>
        )
      }
    >
      <PageInputPanel
        noun="Scene"
        input={handoffScene ? input : null}
        previousLabel="Scene page"
        previousTitle="Take the scene shown on the Scene Generation page"
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

      <StepRow label="Setup">
        <Setting label="Generator" title={GENERATOR_HINTS[generator]}>
          <select value={generator} disabled={running} onChange={(e) => setGenerator(e.target.value as TrajectoryGeneratorWire)} aria-label="Trajectory generator">
            {TRAJECTORY_GENERATORS.map(({ id, label }) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </Setting>
        {straight ? <NumberSetting label="Timespan" unit="s" integer min={1} width={6} value={timespan} disabled={running} onChange={setTimespan} /> : null}
        <EntrySeedField disabled={running} />
        <Disclosure
          id="trajectory:advanced"
          variant="link"
          headingLevel={null}
          title={straight ? "Time step" : "Search settings"}
          openTitle={straight ? "Hide the time step" : "Hide the search settings"}
          hint={straight ? `${params.timeStep} s` : `${params.timeStep} s step, ${params.timeout} s timeout`}
          className="step-more"
        >
          <div className="step-more-body">
            {paramFields.map(({ key, label, unit, integer }) => (
              <NumberSetting
                key={key}
                label={label}
                unit={unit}
                integer={integer}
                width={unit === "iterations" ? 4 : 6}
                value={params[key]}
                disabled={running}
                onChange={(value) => setParam(key, value)}
              />
            ))}
            {!straight ? (
              <>
                <label
                  className="step-check"
                  title="On, the planner sends the COLREGS monitor output of every scene with the preview: the side panel fills and the domains are drawn while planning. Off keeps previews small on long runs."
                >
                  <input type="checkbox" checked={includeMonitorResults} disabled={running} onChange={(e) => setIncludeMonitorResults(e.target.checked)} />
                  Monitor results in previews
                </label>
                <button type="button" className="link-btn" disabled={running} onClick={resetParams}>
                  Reset to the defaults ({TRAJECTORY_GENERATION_PARAM_DEFAULTS.timeStep} s step)
                </button>
              </>
            ) : null}
          </div>
        </Disclosure>
      </StepRow>

      <StepRow
        label="Result"
        aside={
          <>
            <IconButton label="Export the trajectory (JSON)" icon={<DownloadIcon />} disabled={!resultScenarioJson} onClick={handleExportTrajectory} />
            <button
              type="button"
              className={hasResult ? "primary-btn accent" : undefined}
              disabled={running || !connected || !hasResult}
              title={hasResult ? "Make this trajectory the simulation page's input and open it" : "Plan a trajectory, or open one from Campaign History, first"}
              onClick={handleLoadForSimulation}
            >
              Next: Simulation
            </button>
          </>
        }
      >
        <span className="step-value">
          <span className="step-value-name">Trajectory</span>{" "}
          <span className={`step-value-text${runSummary ? "" : " is-empty"}`}>
            {running
              ? straight
                ? "being generated"
                : `best so far, seed step ${iteration}`
              : runSummary
                ? incompletePlan
                  ? "incomplete plan"
                  : resultComplete === true
                    ? "complete plan"
                    : "planned"
                : "none yet"}
          </span>
        </span>
        {runSummary && status === "done" ? <p className="step-line">{describeTrajectoryRun(runSummary)}</p> : null}
        <PageEntryStatus store={useTrajectoryPageStore} />
        {incompletePlan && status === "done" ? (
          <p className="step-line warning step-row-full" role="alert">
            The planner found no complete plan, so this is the best path it found: it ends early or still fails a COLREGS rule. It can still be simulated and exported.
          </p>
        ) : null}
        {runWarning ? (
          <p className="step-line warning step-row-full" role="alert">
            {runWarning}
          </p>
        ) : null}
        {status === "done" && !resultValid ? (
          <p className="step-line warning step-row-full" role="alert">
            The planner returned no usable trajectory: it found no compliant step from this scene.
          </p>
        ) : null}
        {runError ? (
          <p className="step-line error step-row-full" role="alert">
            {runError}
          </p>
        ) : null}
      </StepRow>
    </StepPanel>
  );
}
