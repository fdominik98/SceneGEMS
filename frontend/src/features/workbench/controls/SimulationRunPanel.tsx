import { useCallback, useEffect, useState } from "react";
import "./simulationPanel.css";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import { isClusterRunActive, useClusterRunStore, type ClusterRunStatus } from "../cluster/clusterRunStore";
import { describeClusterPlan, isPacedByWatchSpeed, planSimulationRun, type SimulationSetup } from "../cluster/simulationJobs";
import { describeResources } from "../cluster/workbenchResources";
import { formatClock } from "../scene/encounterGeometry";
import { activateLiveMode, getLatestSimulationTimestamp, watchClusterRun } from "./livePlayback";
import { groundControlEndpointLabels, vesselReadinessLabels } from "./simulationInitConfig";
import { SimulationInitControls } from "./SimulationInitControls";
import type { SimulationStreamControls } from "./types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { EntrySeedField } from "../pages/EntrySeedField";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { PageInputPanel } from "../pages/PageInputPanel";
import { inputOfFile, trajectoriesOfTrajectoryPage, trajectoryContentOfDocument } from "../pages/pageHandoff";
import { useSimulationPageStore, type PageInput } from "../pages/pageStore";
import { StepPanel, StepRow, type StepNotice, type StepStatus } from "../pages/StepPanel";

interface Props {
  streamControls: SimulationStreamControls;
  colregsConstraintsContent: string;
}

const RUN_SPEEDS = [1, 5, 10, 50, 200] as const;

const CLUSTER_STATUS: Record<ClusterRunStatus, StepStatus> = {
  idle: { label: "Ready to run", tone: "idle" },
  queued: { label: "Queued", tone: "busy" },
  running: { label: "Running", tone: "live" },
  finishing: { label: "Finishing", tone: "busy" },
  done: { label: "Finished", tone: "ok" },
  failed: { label: "Failed", tone: "error" },
  stopped: { label: "Stopped", tone: "idle" },
};

const READY_TO_START: StepStatus = { label: "Ready to start", tone: "ok" };
const NO_INPUT: StepStatus = { label: "No input yet", tone: "idle" };

/**
 * The simulation page's panel. Every run is one job on a worker node of the cluster (Run on the
 * cluster): the setup decides which runner takes it, and an attended job then waits for Start once
 * its vessels are up. Playback is in the bar under the canvas; the frames export from the
 * monitoring panel and every run is kept as an entry of Campaign History.
 */
export function SimulationRunPanel({ streamControls, colregsConstraintsContent }: Props) {
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const followSimulationLive = usePlaybackStore((s) => s.followSimulationLive);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const previewMonitor = usePlaybackStore((s) => s.previewMonitor);
  const run = useClusterRunStore();
  const playbackSpeed = usePlaybackStore((s) => s.speed);
  const setPlaying = usePlaybackStore((s) => s.setPlaying);
  const setHoldAtLiveEdge = usePlaybackStore((s) => s.setHoldAtLiveEdge);
  const input = useSimulationPageStore((s) => s.input);
  const trajectoryPageHasResult = useTrajectoryGenerationStore((s) => s.resultValid && s.resultScenarioJson !== null);
  const streamStatus = usePlaybackStore((s) => s.streamStatus);

  const [setup, setSetup] = useState<SimulationSetup | null>(null);
  const onSetupChange = useCallback((next: SimulationSetup) => setSetup(next), []);

  // The job the setup runs as; null until a scenario with vessels is loaded
  const plan = setup ? planSimulationRun(setup) : null;
  const resources = plan !== null ? streamControls.clusterResources(plan.jobType, plan.components) : null;
  const clusterActive = isClusterRunActive(run.status);
  // An attended job brings the vessels up and waits: its Start is the operator's
  const attendedPlan = plan?.runner === "attended";
  const awaitsStart = attendedPlan && run.status === "running" && run.phase === "ready_to_start";
  const status = plan === null && !clusterActive ? NO_INPUT : awaitsStart ? READY_TO_START : CLUSTER_STATUS[run.status];
  const endpoints = groundControlEndpointLabels(clusterActive ? run.groundControlPorts : {}, run.workerNodeAddress ?? (run.workerNodeId ? `worker node ${run.workerNodeId}` : "the worker node"));
  // With a real vessel the job is ready to start only when every vessel is: until then it says what each one lacks
  const waitingVessels = attendedPlan && run.status === "running" && run.phase === "preparing" ? vesselReadinessLabels(run.vesselStates) : [];
  const latestTimestamp = getLatestSimulationTimestamp(simulationFrames);
  const firstTimestamp = simulationFrames[0]?.timestamp ?? null;

  // The run needs only the input (a loaded run replays and runs again without the gateway).
  const hasInput = simulationInitialized || (plan !== null && input !== null && simulationFrames.length > 0);
  const needsInput = hasInput ? undefined : "Take the input trajectories first";
  const notices: StepNotice[] = [];
  if (resources?.blocker) {
    notices.push({ text: resources.blocker });
  }

  const canRunOnCluster = plan !== null && hasInput && notices.length === 0 && !clusterActive;
  const locked = clusterActive;
  // SITL runs free, so the watch speed of an ArduPilot run is the speed it plays at in the browser
  const pacedOnWorkerNode = plan !== null ? isPacedByWatchSpeed(plan) : true;

  useEffect(() => {
    if (!clusterActive) {
      setHoldAtLiveEdge(false); // no more frames are coming
    }
  }, [clusterActive, setHoldAtLiveEdge]);

  // The input's trajectories go to the gateway (which shows them) and to the cluster run; a new input replaces the shown run.
  const takeInput = async (picked: PageInput, content: string | null) => {
    if (content === null) {
      throw new Error("The file holds no trajectories (a trajectories.scene_list).");
    }
    await streamControls.setSimulationInput(picked, content, { colregsConstraintsContent });
  };

  const runOnCluster = () => {
    if (plan === null) {
      return;
    }
    streamControls.runSimulationOnCluster(plan, colregsConstraintsContent);
    watchClusterRun(isPacedByWatchSpeed(plan), { followSimulationLive, setPlaying, setHoldAtLiveEdge });
  };

  const where =
    plan === null || resources === null ? "Take the input trajectories to set up the vessels." : `${describeClusterPlan(plan)} Cluster: ${describeResources(resources)}.`;

  const actions =
    clusterActive ? (
      <>
        {attendedPlan ? (
          <button
            type="button"
            className="primary-btn accent"
            disabled={!awaitsStart}
            title={awaitsStart ? "Start the run on the vessels the job brought up" : "The job is bringing the vessels up"}
            onClick={() => {
              streamControls.startSimulationOnCluster();
              activateLiveMode({ followSimulationLive });
            }}
          >
            Start
          </button>
        ) : plan !== null ? (
          <label className="step-setting" title={pacedOnWorkerNode ? "The pace the worker node runs the simulation at while you watch" : "SITL runs free at the job's speedup, so this is the speed the arriving run plays at here, as the playback bar's"}>
            <span className="step-setting-label">Watch at</span>
            <select
              value={pacedOnWorkerNode ? run.speed : playbackSpeed}
              onChange={(e) => (pacedOnWorkerNode ? streamControls.setClusterRunSpeed(Number(e.target.value)) : streamControls.setSpeed(Number(e.target.value)))}
            >
              {(pacedOnWorkerNode || (RUN_SPEEDS as readonly number[]).includes(playbackSpeed) ? RUN_SPEEDS : [...RUN_SPEEDS, playbackSpeed].sort((a, b) => a - b)).map((speed) => (
                <option key={speed} value={speed}>
                  {speed}x real time
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button type="button" onClick={streamControls.stopSimulationOnCluster}>
          Stop
        </button>
      </>
    ) : (
      <button type="button" className="primary-btn accent" disabled={!canRunOnCluster} title={needsInput} onClick={runOnCluster}>
        Run on the cluster
      </button>
    );

  return (
    <StepPanel page="simulation" title="Simulation" status={status} where={where} notices={notices} actions={actions}>
      <PageInputPanel
        noun="Trajectories"
        input={input}
        previousLabel="Trajectory page"
        previousTitle="Take the trajectories planned on the Trajectory Generation page"
        previousAvailable={trajectoryPageHasResult && streamStatus === "connected"}
        onUsePrevious={async () => {
          const handoff = trajectoriesOfTrajectoryPage();
          if (handoff !== null) {
            await takeInput(handoff.input, handoff.content);
          }
        }}
        historyStep="trajectory_generation"
        client={streamControls.operatorClient}
        onPickHistory={(picked, document) => takeInput(picked, trajectoryContentOfDocument(document))}
        onPickFile={async (file) => takeInput(inputOfFile(file.name), trajectoryContentOfDocument(JSON.parse(await file.text())))}
        disabled={locked || streamStatus !== "connected"}
      />

      <SimulationInitControls
        streamControls={streamControls}
        onSetupChange={onSetupChange}
        attended={attendedPlan}
        paceApplies={!(plan !== null && isPacedByWatchSpeed(plan))}
        extraSettings={plan !== null ? <EntrySeedField disabled={locked} /> : null}
        disabled={locked}
      />

      <StepRow label="Result">
        <span className="step-value">
          <span className="step-value-name">Run</span>{" "}
          <span className={`step-value-text${simulationFrames.length > 0 ? "" : " is-empty"}`}>
            {simulationFrames.length > 0 && firstTimestamp !== null && latestTimestamp !== null
              ? `${simulationFrames.length} frames, ${formatClock(firstTimestamp)} to ${formatClock(latestTimestamp)}`
              : "none yet"}
          </span>
        </span>
        <PageEntryStatus store={useSimulationPageStore} />
        {run.message && run.status !== "idle" ? <p className="step-line step-row-full">{run.message}</p> : null}
        {previewMonitor.status === "running" || previewMonitor.status === "failed" ? (
          <p className={`step-line step-row-full${previewMonitor.status === "failed" ? " warning" : ""}`}>
            {previewMonitor.status === "running" ? previewMonitor.message : `The preview stays unmonitored: ${previewMonitor.message}`}
          </p>
        ) : null}
        {waitingVessels.length > 0 ? (
          <p className="step-line step-row-full" title="The run can start when every vessel is on the broker, at its start point and, when commanded, armable">
            Not ready to start: {waitingVessels.join("; ")}
          </p>
        ) : null}
        {endpoints.length > 0 ? (
          <p className="step-line step-row-full" title="Connect Mission Planner over TCP to fly these vessels">
            Mission Planner: {endpoints.join(", ")}
          </p>
        ) : null}
      </StepRow>
    </StepPanel>
  );
}
