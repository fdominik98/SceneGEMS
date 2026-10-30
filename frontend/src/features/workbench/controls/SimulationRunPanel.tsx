import { useCallback, useRef, useState } from "react";
import "./simulationPanel.css";
import { useUiStore } from "../../../app/uiStore";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import { isClusterRunActive, useClusterRunStore, type ClusterRunStatus } from "../cluster/clusterRunStore";
import { describeClusterPlan, isPacedByWatchSpeed, KINEMATIC_SIMULATION_JOB, planSimulationRun, type SimulationSetup } from "../cluster/simulationJobs";
import { describeResources } from "../cluster/workbenchResources";
import { formatClock } from "../scene/encounterGeometry";
import { activateLiveMode, getLatestSimulationTimestamp } from "./livePlayback";
import { groundControlEndpointLabels } from "./simulationInitConfig";
import { SimulationInitControls, type SimulationInitControlsHandle } from "./SimulationInitControls";
import type { SimulationStreamControls } from "./types";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { EntrySeedField } from "../pages/EntrySeedField";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { PageInputPanel } from "../pages/PageInputPanel";
import { forgetSimulationRun, inputOfFile, trajectoriesOfTrajectoryPage, trajectoryContentOfDocument } from "../pages/pageHandoff";
import { useSimulationPageStore, type PageInput } from "../pages/pageStore";
import { RunRecordingStatus } from "../pages/RunRecordingStatus";
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

const SESSION_STATUS: Record<string, StepStatus> = {
  running: { label: "Running", tone: "live" },
  starting: { label: "Starting", tone: "busy" },
  "agents are preparing": { label: "Agents are preparing", tone: "busy" },
  initializing: { label: "Initializing", tone: "busy" },
  "ready to start": { label: "Agents are ready", tone: "ok" },
  offline: { label: "No simulator connected", tone: "error" },
  "not initialized": { label: "Not initialized", tone: "idle" },
};

/**
 * The simulation page's panel. The setup decides where the run happens: on the cluster as one
 * job (Run on the cluster), or as a live session on the master over the MQTT broker
 * (Initialize, then Start). Playback is in the bar under the canvas; the frames export from
 * the monitoring panel and every run is kept as an entry of Campaign History.
 */
export function SimulationRunPanel({ streamControls, colregsConstraintsContent }: Props) {
  const setWorkbenchView = useUiStore((s) => s.setWorkbenchView);
  const simulationStatus = usePlaybackStore((s) => s.simulationStatus);
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const brokerStatus = usePlaybackStore((s) => s.mqttBrokerStatus);
  const followSimulationLive = usePlaybackStore((s) => s.followSimulationLive);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const groundControlPorts = usePlaybackStore((s) => s.groundControlPortsByAgentId);
  const previewMonitor = usePlaybackStore((s) => s.previewMonitor);
  const run = useClusterRunStore();
  const input = useSimulationPageStore((s) => s.input);
  const trajectoryPageHasResult = useTrajectoryGenerationStore((s) => s.resultValid && s.resultScenarioJson !== null);
  const streamStatus = usePlaybackStore((s) => s.streamStatus);

  const simInitRef = useRef<SimulationInitControlsHandle>(null);
  const [setup, setSetup] = useState<SimulationSetup | null>(null);
  const onSetupChange = useCallback((next: SimulationSetup) => setSetup(next), []);

  const plan = setup ? planSimulationRun(setup) : null;
  const onCluster = plan?.where === "cluster";
  const resources = streamControls.clusterResources(plan?.where === "cluster" ? plan.jobType : KINEMATIC_SIMULATION_JOB);
  const clusterActive = isClusterRunActive(run.status);
  const sessionStatus = SESSION_STATUS[simulationStatus] ?? { label: simulationStatus, tone: "idle" as const };
  const status = onCluster ? CLUSTER_STATUS[run.status] : sessionStatus;
  const endpoints = groundControlEndpointLabels(groundControlPorts);
  const latestTimestamp = getLatestSimulationTimestamp(simulationFrames);
  const firstTimestamp = simulationFrames[0]?.timestamp ?? null;

  // A cluster run needs only the input (a loaded run replays and runs again without the gateway session).
  const hasInput = simulationInitialized || (onCluster && input !== null && simulationFrames.length > 0);
  const needsInput = hasInput ? undefined : "Take the input trajectories first";
  const notices: StepNotice[] = [];
  if (onCluster && resources.blocker) {
    notices.push({ text: resources.blocker });
  }
  if (!onCluster && brokerStatus !== "connected") {
    notices.push({ text: "A live session needs the MQTT broker.", action: { label: "Connect it on the Connections page", onClick: () => setWorkbenchView("connections") } });
  }

  const canRunOnCluster = onCluster && hasInput && notices.length === 0 && !clusterActive;
  const canInitialize = !onCluster && hasInput && notices.length === 0;
  const canStart = !onCluster && simulationStatus === "ready to start";
  const sessionStarted = simulationStatus === "running" || simulationStatus === "starting";
  const sessionBusy = sessionStarted || simulationStatus === "initializing" || simulationStatus === "agents are preparing";
  const locked = clusterActive || sessionBusy;

  // The input's trajectories go to the gateway session and the cluster run; a new input replaces the shown run.
  const takeInput = async (picked: PageInput, content: string | null) => {
    if (content === null) {
      throw new Error("The file holds no trajectories (a trajectories.scene_list).");
    }
    forgetSimulationRun();
    await streamControls.setSimulationInput(picked, content, { colregsConstraintsContent });
  };

  const runOnCluster = () => {
    if (plan?.where !== "cluster") {
      return;
    }
    streamControls.runSimulationOnCluster(plan, colregsConstraintsContent);
    activateLiveMode({ followSimulationLive });
  };

  const where =
    plan === null
      ? "Take the input trajectories to set up the vessels."
      : plan.where === "cluster"
        ? `${describeClusterPlan(plan)} Cluster: ${describeResources(resources)}.`
        : `Runs as a live session on the master over the MQTT broker. ${plan.reason}`;

  const actions = onCluster ? (
    clusterActive ? (
      <>
        {plan?.where === "cluster" && isPacedByWatchSpeed(plan) ? (
          <label className="step-setting">
            <span className="step-setting-label">Watch at</span>
            <select value={run.speed} onChange={(e) => streamControls.setClusterRunSpeed(Number(e.target.value))}>
              {RUN_SPEEDS.map((speed) => (
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
    )
  ) : (
    <>
      {canStart ? (
        <button
          type="button"
          className="primary-btn accent"
          onClick={() => {
            streamControls.startSimulation();
            activateLiveMode({ followSimulationLive });
          }}
        >
          Start
        </button>
      ) : (
        <button
          type="button"
          className="primary-btn accent"
          disabled={!canInitialize || sessionBusy}
          title={needsInput ?? "Start the vessels' simulators and agents for these trajectories"}
          onClick={() => simInitRef.current?.initializeSimulation()}
        >
          Initialize
        </button>
      )}
      <button type="button" disabled={simulationStatus === "not initialized"} title="Stop the session and its agents" onClick={streamControls.resetSimulation}>
        Reset
      </button>
    </>
  );

  return (
    <StepPanel step={3} title="Simulation" status={status} where={where} notices={notices} actions={actions}>
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
        ref={simInitRef}
        streamControls={streamControls}
        onSetupChange={onSetupChange}
        liveSession={plan !== null && !onCluster}
        paceApplies={!(plan?.where === "cluster" && isPacedByWatchSpeed(plan))}
        extraSettings={onCluster ? <EntrySeedField disabled={locked} /> : null}
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
        {onCluster && run.message && run.status !== "idle" ? <p className="step-line step-row-full">{run.message}</p> : null}
        {!onCluster ? (
          <div className="step-row-full">
            <RunRecordingStatus />
          </div>
        ) : null}
        {previewMonitor.status === "running" || previewMonitor.status === "failed" ? (
          <p className={`step-line step-row-full${previewMonitor.status === "failed" ? " warning" : ""}`}>
            {previewMonitor.status === "running" ? previewMonitor.message : `The preview stays unmonitored: ${previewMonitor.message}`}
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
