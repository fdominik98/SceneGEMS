import { useCallback, useEffect, useRef, useState } from "react";
import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../playback/playbackStore";
import { BackendWsClient } from "./wsClient";
import type { ParsedServerMessage } from "./protocol";
import { gatewayWsUrl } from "./simulationConfig";
import type { SimulationFrame } from "./types";
import { RETIRED_GATEWAY_MESSAGES, type ClientToServerMessage } from "./wireTypes";
import { useUiStore } from "../../app/uiStore";
import { useBatchGenerationStore } from "../sceneGeneration/batchGenerationStore";
import { buildFramesFromTrajectoryData } from "../sceneGeneration/parseEvaluationDataFile";
import { useTrajectoryGenerationStore } from "../trajectoryGeneration/trajectoryGenerationStore";
import { useConnectionStore } from "../../features/workbench/connection/connectionStore";
import { useWorkbenchCluster } from "../../features/workbench/cluster/useWorkbenchCluster";
import {
  WorkbenchJobDriver,
  type BatchSceneRow,
  type ExplorationEntryRequest,
  type SceneEntryRequest,
  type TrajectoryEntryRequest,
} from "../../features/workbench/cluster/workbenchJobDriver";
import type { SceneGenerationInput } from "../../features/workbench/cluster/workbenchJobs";
import { simulationSubmission, type ClusterRunPlan } from "../../features/workbench/cluster/simulationJobs";
import { useSimulationSetupRequestStore } from "../../features/workbench/controls/simulationSetupRequest";
import type { LoadedRun } from "../../features/workbench/pages/entryLoader";
import { simulationInputToRestore, storedTrajectoryContent } from "../../features/workbench/pages/pageHandoff";
import { OperatorApiError } from "../cluster/operatorApi";
import { useSimulationPageStore, type PageInput } from "../../features/workbench/pages/pageStore";
import type { WorkbenchTarget } from "../../features/workbench/pages/workbenchTarget";
import {
  GATEWAY_SCENARIO_LIMIT_BYTES,
  gatewayClosedMessage,
  gatewayScenarioContent,
  gatewayTooLargeMessage,
  hasMonitorFrames,
  isFullTrajectoryScenario,
} from "../sceneGeneration/parseEvaluationDataFile";
import { NO_TRAJECTORIES_MESSAGE } from "./trajectoryGuard";

let simulationModelsToken = 0;

/** Whether an unknown gateway message is one of the former live session's, which a control node of an earlier release still sends. */
export function isRetiredGatewayMessage(raw: unknown): boolean {
  const type = typeof raw === "object" && raw !== null ? (raw as { type?: unknown }).type : undefined;
  return typeof type === "string" && RETIRED_GATEWAY_MESSAGES.includes(type);
}

/**
 * Whether a gateway error is a control node of an earlier release refusing `query_vessel_model_presets`, which it
 * does not know: it has no presets, so every vessel keeps the automatic model and there is nothing to tell.
 */
export function isUnknownVesselModelPresetsQuery(message: string): boolean {
  return message.trim() === "Unknown message type: query_vessel_model_presets";
}

function trajectoryChunkMatchesActiveScenario(
  activeScenarioId: string | null,
  chunkScenarioId: string | null
): boolean {
  if (activeScenarioId === null && chunkScenarioId === null) {
    return true;
  }
  if (activeScenarioId === null || chunkScenarioId === null) {
    return false;
  }
  return activeScenarioId === chunkScenarioId;
}

export interface LoadScenarioOptions {
  /** COLREGS constants for the cluster's monitoring of the loaded trajectory; the trajectory stays unmonitored without them. */
  colregsConstraintsContent?: string;
  /** A loaded run's frames, replayed as the simulation stream once the gateway took the scenario. */
  replayFrames?: SimulationFrame[];
}

/** The simulator a recorded simulation layer is selected as (`planSimulationRun` plans these layers on the cluster). */
const SIMULATOR_OF_LAYER = { ardupilot_sim: "ArduPilot Sim", gazebo: "Gazebo" } as const;

/** The setup of a loaded run as the simulation controls take it: the kinematic layer, ArduPilot on SITL or Gazebo, or the custom controller on Gazebo. */
export function setupRequestOf(run: LoadedRun) {
  const waves = run.setup.waves;
  const layer = run.setup.simulationLayer;
  const arduPilot = layer === "ardupilot_sim" || layer === "gazebo";
  const custom = layer === "gazebo" && run.setup.controlLayer === "custom";
  return {
    simulatorType: arduPilot ? SIMULATOR_OF_LAYER[layer] : ("Kinematic" as const),
    controlLayer: custom ? ("custom" as const) : arduPilot ? ("ardupilot" as const) : ("none" as const),
    speedup: arduPilot && !custom ? run.setup.speedup : null,
    mode: run.setup.mode === "usv_navigation" ? ("usv_navigation" as const) : run.setup.mode === "moos_ivp" ? ("moos_ivp" as const) : ("replay" as const),
    windVector: run.setup.windVector,
    wave: waves === null ? null : { amplitude: waves.amplitude, period: waves.period, steepness: waves.steepness, east: waves.direction[0], north: waves.direction[1] },
  };
}

/**
 * The workbench's backend: design space exploration, scene generation, trajectory generation,
 * simulation and monitoring run as jobs on the active cluster's worker nodes (`WorkbenchJobDriver`).
 * The gateway WebSocket of the cluster's control node only loads scenario files, generates vessel
 * models and lists the stack options and the vessel model presets of the loaded scenario: it runs
 * no simulation and connects to no broker.
 */
export function useSimulationWorkflow() {
  const ingestFrames = usePlaybackStore((s) => s.ingestFrames);
  const ingestSimulationFrames = usePlaybackStore((s) => s.ingestSimulationFrames);
  const clearSimulationTrajectories = usePlaybackStore((s) => s.clearSimulationTrajectories);
  const resetForNewScene = usePlaybackStore((s) => s.resetForNewScene);
  const markSimulationInitialized = usePlaybackStore((s) => s.markSimulationInitialized);
  const setStreamStatus = usePlaybackStore((s) => s.setStreamStatus);
  const setError = usePlaybackStore((s) => s.setError);
  const setPlaying = usePlaybackStore((s) => s.setPlaying);
  const setLatestTimestamp = usePlaybackStore((s) => s.setLatestTimestamp);
  const setScenarioTrajectoryLength = usePlaybackStore((s) => s.setScenarioTrajectoryLength);
  const setActiveScenarioId = usePlaybackStore((s) => s.setActiveScenarioId);
  const setFollowLatestPush = usePlaybackStore((s) => s.setFollowLatestPush);
  const setSpeed = usePlaybackStore((s) => s.setSpeed);
  const seek = usePlaybackStore((s) => s.seek);
  const setReceivedSimulationModels = usePlaybackStore((s) => s.setReceivedSimulationModels);
  const clientRef = useRef<BackendWsClient | null>(null);
  const dispatchMessageRef = useRef<(message: ParsedServerMessage) => void>(() => {});
  const workbenchCluster = useWorkbenchCluster();
  const [driver] = useState(() => new WorkbenchJobDriver());
  useEffect(() => {
    driver.setCluster(workbenchCluster);
  }, [driver, workbenchCluster]);
  useEffect(() => () => driver.stopAll(), [driver]);
  // The trajectories of the loaded scenario, which a simulation on the cluster replays, and the
  // scenario file itself, uploaded as the entry's input when it is not on the control node.
  const loadedTrajectoriesRef = useRef<Record<string, unknown> | null>(null);
  const loadedScenarioContentRef = useRef<string | null>(null);
  // A loaded run's frames, waiting for the gateway's initial state of its scenario.
  const pendingReplayRef = useRef<{ scenarioId: string; frames: SimulationFrame[] } | null>(null);
  // The judged preview of a scenario that carries the monitor's frames, waiting for the same.
  const pendingPreviewRef = useRef<{ scenarioId: string; frames: SimulationFrame[] } | null>(null);
  // The scenario file the gateway was sent and has not answered for yet, with its size: a socket that closes meanwhile took it down.
  const pendingLoadRef = useRef<{ scenarioId: string; bytes: number } | null>(null);
  const handleTransportError = useCallback(
    (message: string) => {
      if (message === "WebSocket transport issue.") {
        return;
      }
      setError(message);
    },
    [setError]
  );

  const dispatchMessage = useCallback(
    (message: ParsedServerMessage) => {
      switch (message.kind) {
        case "initial_state": {
          // `scenarioId` is contractually always present and drives routing of the
          // trajectory chunks that follow; fall back to the client-proposed id
          // (captured before the reset) if a message ever omits it.
          const priorScenarioId = usePlaybackStore.getState().activeScenarioId;
          resetForNewScene();
          setActiveScenarioId(message.scenarioId ?? priorScenarioId);
          markSimulationInitialized();
          setPlaying(false);
          setScenarioTrajectoryLength(message.totalTrajectoryLength);
          if (message.totalTrajectoryLength !== null) {
            setLatestTimestamp(message.totalTrajectoryLength);
          }
          // The gateway holds the scenario now: which preset vessel models each of its vessels can take.
          // The reset above dropped the former scenario's list; the answer names this one.
          clientRef.current?.send({ type: "query_vessel_model_presets" });
          const loadedScenarioId = usePlaybackStore.getState().activeScenarioId;
          pendingLoadRef.current = null;
          const preview = pendingPreviewRef.current;
          if (preview !== null && preview.scenarioId === loadedScenarioId) {
            // The file's own monitor frames are the judged preview: the gateway's plain chunks that follow are dropped.
            pendingPreviewRef.current = null;
            usePlaybackStore.getState().setTrajectoryPreviewFrames(preview.frames);
            usePlaybackStore.getState().setPreviewMonitor({ status: "done", scenarioId: preview.scenarioId, message: null });
          }
          const replay = pendingReplayRef.current;
          if (replay !== null && replay.scenarioId === loadedScenarioId) {
            pendingReplayRef.current = null;
            ingestSimulationFrames(replay.frames);
          }
          break;
        }
        case "preview_trajectory_chunk": {
          const store = usePlaybackStore.getState();
          if (!trajectoryChunkMatchesActiveScenario(store.activeScenarioId, message.scenarioId)) {
            break;
          }
          // The cluster's monitored frames replaced the gateway's plain ones already.
          if (store.previewMonitor.status === "done" && store.previewMonitor.scenarioId === store.activeScenarioId) {
            break;
          }
          // Merged into the store's current frames in one step (linear for sorted chunks), so a
          // chunk never lands on a stale copy of the frames.
          ingestFrames(message.frames);
          break;
        }
        case "generated_scene": {
          const store = useScenePlaybackStore.getState();
          // Answer to a `monitor_scene` request for a scene loaded from disk.
          if (
            message.requestId !== null &&
            message.requestId === store.pendingSceneMonitorRequestId
          ) {
            store.applySceneMonitorResult(message.requestId, message.scene);
            break;
          }
          const scenePayload = {
            scene: message.scene,
            evaluationData: message.evaluationData ?? undefined,
            valid: message.valid,
          };
          const isBatchRequest =
            !!message.requestId &&
            useBatchGenerationStore.getState().isBatchRequest(message.requestId);
          const livePreview = useUiStore.getState().sceneGenerationLivePreview;
          const shouldVisualize =
            livePreview || (!isBatchRequest && message.valid);
          if (isBatchRequest && message.requestId) {
            if (shouldVisualize) {
              store.setVisualizedScenario(scenePayload);
            }
            useBatchGenerationStore.getState().handleBatchGeneratedScene(message.requestId, scenePayload);
            break;
          }
          const { activeSceneGenerationRequestId } = store;
          if (
            activeSceneGenerationRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== activeSceneGenerationRequestId
          ) {
            break;
          }
          if (message.requestId) {
            if (message.valid) {
              if (shouldVisualize) {
                store.setVisualizedScenario(scenePayload);
              }
              store.completeSceneGeneration(message.requestId);
            } else if (message.evaluationData) {
              store.recordSceneGenerationEvaluation(message.requestId, message.evaluationData);
            }
          } else {
            if (shouldVisualize) {
              store.setVisualizedScenario(scenePayload);
            }
            if (message.valid) {
              store.setActiveSceneGenerationRequestId(null);
            }
          }
          break;
        }
        case "trajectory_generation_preview": {
          const tgStore = useTrajectoryGenerationStore.getState();
          if (
            tgStore.activeRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== tgStore.activeRequestId
          ) {
            break;
          }
          const frames = buildFramesFromTrajectoryData(message.trajectoryData);
          if (frames.length > 0) {
            useTrajectoryPlaybackStore.getState().setTrajectoryPreviewFrames(frames);
          }
          const iterNumbers = (message.trajectoryData?.iter_numbers ?? {}) as Record<string, number>;
          const iteration = Object.values(iterNumbers)[0] ?? tgStore.iteration;
          tgStore.markPreview(iteration);
          break;
        }
        case "trajectory_generation_result": {
          const tgStore = useTrajectoryGenerationStore.getState();
          if (
            tgStore.activeRequestId !== null &&
            message.requestId !== null &&
            message.requestId !== tgStore.activeRequestId
          ) {
            break;
          }
          if (message.trajectoryData) {
            const frames = buildFramesFromTrajectoryData(message.trajectoryData);
            if (frames.length > 0) {
              useTrajectoryPlaybackStore.getState().setTrajectoryPreviewFrames(frames);
            }
          }
          tgStore.markResult({
            valid: message.valid,
            complete: message.complete,
            scenarioJson:
              message.valid && message.trajectoryData
                ? JSON.stringify(message.trajectoryData)
                : null,
            errorMessage: message.errorMessage ?? null,
          });
          if (message.errorMessage) {
            setError(message.errorMessage);
          }
          break;
        }
        case "error":
          if (!isUnknownVesselModelPresetsQuery(message.message)) {
            // The gateway answered, also for a scenario file it could not load
            pendingLoadRef.current = null;
            setError(message.message);
          }
          break;
        case "ack":
          setError(null);
          break;
        case "stack_options":
          usePlaybackStore.getState().setStackOptions(message.options);
          break;
        case "simulation_models":
          simulationModelsToken += 1;
          setReceivedSimulationModels({
            vesselModelsByAgentId: message.vesselModelsByAgentId,
            vesselModelPresetByAgentId: message.vesselModelPresetByAgentId,
            receivedToken: simulationModelsToken,
          });
          break;
        case "vessel_model_presets":
          // Kept only when it is for the active scenario: the answer to a load that another one replaced is dropped.
          usePlaybackStore.getState().setVesselModelPresets(message.presets);
          break;
        case "unknown":
          // A control node of an earlier release still sends the statuses of its live session: they mean nothing here.
          if (!isRetiredGatewayMessage(message.raw)) {
            console.warn("[SimulationWorkflow] Unknown server message shape", message.raw);
          }
          break;
        default:
          break;
      }
    },
    [
      ingestFrames,
      ingestSimulationFrames,
      markSimulationInitialized,
      resetForNewScene,
      setError,
      setLatestTimestamp,
      setScenarioTrajectoryLength,
      setPlaying,
      setActiveScenarioId,
      setReceivedSimulationModels,
    ]
  );

  useEffect(() => {
    dispatchMessageRef.current = dispatchMessage;
    driver.setDispatch(dispatchMessage);
  }, [dispatchMessage, driver]);

  const gatewayUrl = gatewayWsUrl(workbenchCluster.operatorUrl);
  useEffect(() => {
    if (gatewayUrl === null) {
      // No cluster is selected, so there is no control-node-api whose gateway the workbench could use.
      setStreamStatus("disconnected");
      usePlaybackStore.getState().setActiveScenarioId(null);
      return;
    }
    const client = new BackendWsClient(gatewayUrl, {
      onServerMessage: (message) => dispatchMessageRef.current(message),
      onStatus: (status) => {
        setStreamStatus(status);
        if (status === "connected") {
          setError(null);
          // The simulator, ASV system and control layer choices come from the backend's stack resolver.
          client.send({ type: "query_stack_options" });
          return;
        }
        if (status === "disconnected" || status === "error") {
          // The gateway's scenario session is gone with the socket. Jobs on the cluster do not
          // depend on it: they keep running and keep reporting.
          usePlaybackStore.getState().setActiveScenarioId(null);
          const unanswered = pendingLoadRef.current;
          if (unanswered !== null) {
            // The socket closed over the scenario file: nothing will answer for it, so the page says so instead of waiting
            pendingLoadRef.current = null;
            pendingReplayRef.current = null;
            pendingPreviewRef.current = null;
            useSimulationPageStore.getState().setStatus("failed", gatewayClosedMessage(unanswered.bytes), null);
          }
        }
      },
      onError: handleTransportError,
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [gatewayUrl, handleTransportError, setError, setStreamStatus]);

  const loadScenarioFromFile = useCallback(
    async (file: File | null, options: LoadScenarioOptions = {}) => {
      if (!file) {
        return;
      }
      if (usePlaybackStore.getState().streamStatus !== "connected") {
        setError("The workbench server is not connected.");
        return;
      }
      resetForNewScene();
      clearSimulationTrajectories();
      setPlaying(false);
      setFollowLatestPush(false);
      setError(null);
      const scenarioId = crypto.randomUUID();
      setActiveScenarioId(scenarioId);
      pendingReplayRef.current = options.replayFrames && options.replayFrames.length > 0 ? { scenarioId, frames: options.replayFrames } : null;
      pendingPreviewRef.current = null;
      const fileContent = await file.text();
      loadedScenarioContentRef.current = fileContent;
      let raw: unknown = null;
      try {
        raw = JSON.parse(fileContent);
      } catch {
        raw = null;
      }
      loadedTrajectoriesRef.current = isFullTrajectoryScenario(raw) ? (raw as { trajectories: Record<string, unknown> }).trajectories : null;
      // The gateway gets the file without the monitor's frames: with them a planned trajectory is larger than its socket takes.
      const gatewayContent = gatewayScenarioContent(raw, fileContent);
      const gatewayBytes = new Blob([gatewayContent]).size;
      if (gatewayBytes > GATEWAY_SCENARIO_LIMIT_BYTES) {
        pendingReplayRef.current = null;
        setActiveScenarioId(null);
        pendingLoadRef.current = null;
        setError(gatewayTooLargeMessage(gatewayBytes));
        return;
      }
      pendingLoadRef.current = { scenarioId, bytes: gatewayBytes };
      clientRef.current?.send({
        type: "load_scenario_file",
        scenarioId,
        fileName: file.name,
        filePath: file.webkitRelativePath || file.name,
        fileContent: gatewayContent,
      });
      if (hasMonitorFrames(raw)) {
        // The planner judged every scene already: no monitoring job for the preview.
        driver.cancelPreviewMonitor();
        usePlaybackStore.getState().setPreviewMonitor({ status: "idle", scenarioId, message: null });
        pendingPreviewRef.current = { scenarioId, frames: buildFramesFromTrajectoryData(raw) };
        return;
      }
      void driver.monitorPreview(scenarioId, raw, options.colregsConstraintsContent ?? "");
    },
    [
      driver,
      clearSimulationTrajectories,
      resetForNewScene,
      setActiveScenarioId,
      setError,
      setFollowLatestPush,
      setPlaying,
    ]
  );

  const setSimulationInput = useCallback(
    async (input: PageInput, content: string, options: LoadScenarioOptions = {}) => {
      // The input and the run share the canvas and the session: a new input replaces the shown run.
      useSimulationPageStore.getState().setLocalOutput(null);
      useSimulationPageStore.getState().setInput(input);
      const fileName = "file" in input.source && input.source.file ? input.source.file : "trajectories.json";
      await loadScenarioFromFile(new File([content], fileName, { type: "application/json" }), options);
    },
    [loadScenarioFromFile]
  );

  /**
   * After a reload the simulation page keeps its input's name and artifact but not its
   * trajectories: reads them again from the control node and loads them as taking the input did. A file
   * that never reached the control node cannot be read again, so the page drops it and says so. Does
   * nothing while the page shows a loaded run (its refresh loads the run's input) or has
   * trajectories already.
   */
  const restoreSimulationInput = useCallback(
    async (colregsConstraintsContent: string) => {
      const page = useSimulationPageStore.getState();
      const client = workbenchCluster.cluster?.client ?? null;
      const restore = simulationInputToRestore(page, loadedTrajectoriesRef.current !== null);
      if (restore.kind === "none" || client === null) {
        return;
      }
      const { input } = restore;
      if (restore.kind === "file") {
        page.setInput(null);
        page.setStatus("idle", `The input "${input.label}" was a file, which is not kept after a reload: take it again.`);
        return;
      }
      // The user may have taken another input while this read.
      const stillWanted = () => {
        const now = useSimulationPageStore.getState();
        return now.input === input && now.loaded === null && loadedTrajectoriesRef.current === null;
      };
      try {
        const content = await storedTrajectoryContent(client, restore.ref);
        if (!stillWanted()) {
          return;
        }
        if (content === null) {
          throw new Error("it holds no trajectories");
        }
        const fileName = "file" in input.source && input.source.file ? input.source.file : "trajectories.json";
        await loadScenarioFromFile(new File([content], fileName, { type: "application/json" }), { colregsConstraintsContent });
      } catch (error) {
        if (!stillWanted()) {
          return;
        }
        const gone = error instanceof OperatorApiError && error.status === 404;
        if (gone) {
          page.setInput(null);
        }
        page.setStatus(
          "idle",
          gone
            ? "The input trajectories were deleted from the control node: take them again."
            : `The input trajectories could not be read again: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    },
    [loadScenarioFromFile, workbenchCluster]
  );

  const colregsRef = useRef("");
  useEffect(() => {
    driver.setSimulationHooks({
      loadSimulationInput: async (content, fileName, replayFrames) => {
        if (usePlaybackStore.getState().streamStatus === "connected") {
          await loadScenarioFromFile(new File([content], fileName, { type: "application/json" }), { colregsConstraintsContent: colregsRef.current, replayFrames });
          return;
        }
        // Without the gateway the run still replays and can run again on the cluster.
        try {
          const raw: unknown = JSON.parse(content);
          loadedTrajectoriesRef.current = isFullTrajectoryScenario(raw) ? (raw as { trajectories: Record<string, unknown> }).trajectories : null;
        } catch {
          loadedTrajectoriesRef.current = null;
        }
        loadedScenarioContentRef.current = content;
        clearSimulationTrajectories();
        ingestSimulationFrames(replayFrames);
      },
      replaceRunFrames: (frames) => {
        // Frames still waiting for the gateway's initial state are replaced where they wait.
        if (pendingReplayRef.current !== null) {
          pendingReplayRef.current = { ...pendingReplayRef.current, frames };
          return;
        }
        usePlaybackStore.getState().applyMergedSimulationFrames(frames);
      },
      fillSetup: (run) => useSimulationSetupRequestStore.getState().requestSetup(setupRequestOf(run)),
    });
  }, [clearSimulationTrajectories, driver, ingestSimulationFrames, loadScenarioFromFile]);

  return {
    loadScenarioFromFile,
    setSpeed: (value: number) => {
      setSpeed(value);
    },
    seek: (value: number) => {
      seek(value);
    },
    /** Sends the gateway one of its helper requests (generate_simulation_models). */
    sendMessage: (message: ClientToServerMessage) => {
      clientRef.current?.send(message);
    },
    /** What the active cluster offers for a job type, and why the workbench cannot run it when it cannot. */
    clusterResources: workbenchCluster.resources,
    operatorUrl: workbenchCluster.operatorUrl,
    /** The active cluster's operator client (Campaign History for the pages' inputs), null without one. */
    operatorClient: workbenchCluster.cluster?.client ?? null,
    /** Explores the design space as a workbench entry; the page follows the job and then shows the explored FECs. */
    exploreDesignSpace: (request: ExplorationEntryRequest) => {
      void driver.exploreDesignSpace(request);
    },
    stopDesignSpaceExploration: () => driver.stopExploration(true),
    /** The selected scenarios as one batch entry; resolves when every row's case ended. */
    generateBatch: (rows: BatchSceneRow[], input: Omit<SceneGenerationInput, "functionalScenarioContent">) => driver.generateBatch(rows, input),
    /** One scene as a workbench entry, shown on the scene page as it arrives; resolves with its outcome. */
    generateScene: (requestId: string, input: SceneEntryRequest) => driver.generateScene(requestId, input),
    /** Monitors a scene (a scenario file's first scene) on the cluster and merges the verdicts into the shown scene. */
    monitorScene: (requestId: string, scenario: Record<string, unknown>, colregsConstraintsContent: string) =>
      driver.monitorScene(requestId, scenario, colregsConstraintsContent),
    stopSceneGeneration: () => {
      driver.stopScenes(true);
      useScenePlaybackStore.getState().cancelSceneGeneration();
      useBatchGenerationStore.getState().markAllBatchStopped();
    },
    /** Plans trajectories for the trajectory page's input as a workbench entry. */
    generateTrajectories: (requestId: string, request: TrajectoryEntryRequest) => {
      void driver.generateTrajectories(requestId, request);
    },
    stopTrajectoryGeneration: () => {
      driver.stopTrajectories(true);
    },
    /**
     * Runs the loaded trajectories on the cluster; the frames fill the simulation stream. A run on
     * the kinematic layer or on ArduPilot SITL or Gazebo is a workbench entry with the page's input;
     * trajectories without a page input run as a direct job.
     */
    runSimulationOnCluster: (plan: ClusterRunPlan, colregsConstraintsContent: string) => {
      const trajectories = loadedTrajectoriesRef.current;
      if (trajectories === null) {
        setError(NO_TRAJECTORIES_MESSAGE);
        return;
      }
      setFollowLatestPush(false);
      const input = useSimulationPageStore.getState().input;
      const geofence = useConnectionStore.getState().geofence;
      if (input !== null) {
        void driver.runSimulationEntry(plan, { input, scenarioContent: loadedScenarioContentRef.current, colregsConstraintsContent, geofence });
        return;
      }
      void driver.runSimulation(simulationSubmission(plan, { trajectories, colregsConstraintsContent, geofence }), colregsConstraintsContent);
    },
    /** Sets the simulation page's input and loads its trajectories. */
    setSimulationInput,
    /** Loads the simulation page's stored input again after a reload. */
    restoreSimulationInput,
    /** Shows a target on its page: follows a live one, loads a finished one. */
    openTarget: (target: WorkbenchTarget, colregsConstraintsContent: string) => {
      colregsRef.current = colregsConstraintsContent;
      return driver.openTarget(target);
    },
    /** Refreshes a page's loaded entry from the control node (after a reload); a deleted entry clears the page. */
    refreshLoaded: (target: WorkbenchTarget, colregsConstraintsContent: string) => {
      colregsRef.current = colregsConstraintsContent;
      return driver.loadTarget(target, { quiet: true });
    },
    stopSimulationOnCluster: () => driver.stopSimulation(true),
    startSimulationOnCluster: () => void driver.startSimulation(),
    setClusterRunSpeed: (speed: number) => driver.setSimulationSpeed(speed),
  };
}
