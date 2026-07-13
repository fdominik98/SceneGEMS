import { useCallback, useEffect, useRef } from "react";
import { usePlaybackStore } from "../playback/playbackStore";
import { BackendWsClient } from "./wsClient";
import type { ParsedServerMessage } from "./protocol";
import { getSimulationWsUrl } from "./simulationConfig";
import type { SimulationFrame } from "./types";
import type { ClientToServerMessage } from "./wireTypes";
import { useUiStore } from "../../app/uiStore";
import {
  mergeFramesInWorker,
  shouldMergeFramesInWorker,
} from "../playback/mergeFramesInWorker";
import { useRecordingStore } from "../playback/recordingStore";
import { useBatchGenerationStore } from "../sceneGeneration/batchGenerationStore";

let previewTrajectoryChunkQueue = Promise.resolve();
let simulationTrajectoryChunkQueue = Promise.resolve();
let simulationModelsToken = 0;

function enqueuePreviewTrajectoryChunk(task: () => Promise<void>): void {
  previewTrajectoryChunkQueue = previewTrajectoryChunkQueue.then(task, task);
}

function enqueueSimulationTrajectoryChunk(task: () => Promise<void>): void {
  simulationTrajectoryChunkQueue = simulationTrajectoryChunkQueue.then(task, task);
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

export function useSimulationWorkflow() {
  const ingestFrames = usePlaybackStore((s) => s.ingestFrames);
  const applyMergedPreviewFrames = usePlaybackStore((s) => s.applyMergedPreviewFrames);
  const ingestSimulationFrames = usePlaybackStore((s) => s.ingestSimulationFrames);
  const applyMergedSimulationFrames = usePlaybackStore((s) => s.applyMergedSimulationFrames);
  const ingestPushFrame = usePlaybackStore((s) => s.ingestPushFrame);
  const clearSimulationTrajectories = usePlaybackStore((s) => s.clearSimulationTrajectories);
  const resetForNewScene = usePlaybackStore((s) => s.resetForNewScene);
  const markSimulationInitialized = usePlaybackStore((s) => s.markSimulationInitialized);
  const setSimulationStatus = usePlaybackStore((s) => s.setSimulationStatus);
  const setStreamStatus = usePlaybackStore((s) => s.setStreamStatus);
  const setError = usePlaybackStore((s) => s.setError);
  const setWarapsStatus = usePlaybackStore((s) => s.setWarapsStatus);
  const setMonitorStatus = usePlaybackStore((s) => s.setMonitorStatus);
  const setPlaying = usePlaybackStore((s) => s.setPlaying);
  const setLatestTimestamp = usePlaybackStore((s) => s.setLatestTimestamp);
  const setActiveScenarioId = usePlaybackStore((s) => s.setActiveScenarioId);
  const setFollowLatestPush = usePlaybackStore((s) => s.setFollowLatestPush);
  const setSpeed = usePlaybackStore((s) => s.setSpeed);
  const seek = usePlaybackStore((s) => s.seek);
  const setActiveSceneGenerationRequestId = usePlaybackStore(
    (s) => s.setActiveSceneGenerationRequestId
  );
  const completeSceneGeneration = usePlaybackStore((s) => s.completeSceneGeneration);
  const setReceivedSimulationModels = usePlaybackStore((s) => s.setReceivedSimulationModels);
  const setControlPanelMode = useUiStore((s) => s.setControlPanelMode);
  const clientRef = useRef<BackendWsClient | null>(null);
  const dispatchMessageRef = useRef<(message: ParsedServerMessage) => void>(() => {});
  const handleTransportError = useCallback(
    (message: string) => {
      if (message === "WebSocket transport issue.") {
        return;
      }
      setError(message);
    },
    [setError]
  );

  const recordPreviewFrames = useCallback((frames: SimulationFrame[]) => {
    const recording = useRecordingStore.getState();
    if (!recording.isRecording) return;
    for (const frame of frames) {
      recording.appendPreviewFrame(frame);
    }
  }, []);

  const ingestPreviewChunk = useCallback(
    async (existing: Parameters<typeof mergeFramesInWorker>[0], incoming: Parameters<typeof mergeFramesInWorker>[1]) => {
      if (shouldMergeFramesInWorker(incoming.length)) {
        const merged = await mergeFramesInWorker(existing, incoming);
        applyMergedPreviewFrames(merged);
        recordPreviewFrames(incoming);
        return;
      }
      ingestFrames(incoming);
      recordPreviewFrames(incoming);
    },
    [applyMergedPreviewFrames, ingestFrames, recordPreviewFrames]
  );

  const ingestSimulationChunk = useCallback(
    async (existing: Parameters<typeof mergeFramesInWorker>[0], incoming: Parameters<typeof mergeFramesInWorker>[1]) => {
      const recording = useRecordingStore.getState();
      if (shouldMergeFramesInWorker(incoming.length)) {
        const merged = await mergeFramesInWorker(existing, incoming);
        applyMergedSimulationFrames(merged);
        if (recording.isRecording) {
          for (const frame of incoming) recording.appendSimulationFrame(frame);
        }
        return;
      }
      ingestSimulationFrames(incoming);
      if (recording.isRecording) {
        for (const frame of incoming) recording.appendSimulationFrame(frame);
      }
    },
    [applyMergedSimulationFrames, ingestSimulationFrames]
  );

  const dispatchMessage = useCallback(
    (message: ParsedServerMessage) => {
      switch (message.kind) {
        case "initial_state":
          resetForNewScene();
          setControlPanelMode("simulation");
          if (message.scenarioId !== null) {
            setActiveScenarioId(message.scenarioId);
          }
          markSimulationInitialized();
          setPlaying(false);
          if (message.totalTrajectoryLength !== null) {
            setLatestTimestamp(message.totalTrajectoryLength);
          }
          break;
        case "preview_trajectory_chunk": {
          const store = usePlaybackStore.getState();
          if (!trajectoryChunkMatchesActiveScenario(store.activeScenarioId, message.scenarioId)) {
            break;
          }
          const incoming = message.frames;
          enqueuePreviewTrajectoryChunk(async () => {
            const latest = usePlaybackStore.getState();
            if (!trajectoryChunkMatchesActiveScenario(latest.activeScenarioId, message.scenarioId)) {
              return;
            }
            await ingestPreviewChunk(latest.frames, incoming);
          });
          break;
        }
        case "simulation_trajectory_chunk": {
          const store = usePlaybackStore.getState();
          if (!trajectoryChunkMatchesActiveScenario(store.activeScenarioId, message.scenarioId)) {
            break;
          }
          const incoming = message.frames;
          enqueueSimulationTrajectoryChunk(async () => {
            const latest = usePlaybackStore.getState();
            if (!trajectoryChunkMatchesActiveScenario(latest.activeScenarioId, message.scenarioId)) {
              return;
            }
            await ingestSimulationChunk(latest.simulationFrames, incoming);
          });
          break;
        }
        case "generated_scene": {
          const store = usePlaybackStore.getState();
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
              completeSceneGeneration(message.requestId);
            } else if (message.evaluationData) {
              store.recordSceneGenerationEvaluation(message.requestId, message.evaluationData);
            }
          } else {
            if (shouldVisualize) {
              store.setVisualizedScenario(scenePayload);
            }
            if (message.valid) {
              setActiveSceneGenerationRequestId(null);
            }
          }
          break;
        }
        case "frame": {
          ingestPushFrame(message.frame);
          const recording = useRecordingStore.getState();
          if (recording.isRecording) {
            recording.appendPreviewFrame(message.frame);
          }
          break;
        }
        case "error":
          setError(message.message);
          break;
        case "ack":
          setError(null);
          break;
        case "waraps_status":
          setWarapsStatus(message.status);
          break;
        case "monitor_status":
          setMonitorStatus(message.status);
          break;
        case "simulation_status":
          setSimulationStatus(message.status);
          break;
        case "simulation_models":
          simulationModelsToken += 1;
          setReceivedSimulationModels({
            vesselModelsByAgentId: message.vesselModelsByAgentId,
            receivedToken: simulationModelsToken,
          });
          break;
        case "unknown":
          console.warn("[SimulationWorkflow] Unknown server message shape", message.raw);
          break;
        default:
          break;
      }
    },
    [
      ingestPreviewChunk,
      ingestSimulationChunk,
      completeSceneGeneration,
      ingestPushFrame,
      markSimulationInitialized,
      resetForNewScene,
      setError,
      setLatestTimestamp,
      setPlaying,
      setSimulationStatus,
      setWarapsStatus,
      setMonitorStatus,
      setActiveScenarioId,
      setControlPanelMode,
      setActiveSceneGenerationRequestId,
      setReceivedSimulationModels,
    ]
  );

  useEffect(() => {
    dispatchMessageRef.current = dispatchMessage;
  }, [dispatchMessage]);

  const prepareForSimulationReset = useCallback(() => {
    // Keep loaded scenario/animation chunks, but clear simulation stream data and rewind playback.
    clearSimulationTrajectories();
    setReceivedSimulationModels(null);
    setPlaying(false);
    setFollowLatestPush(false);
    const { frames } = usePlaybackStore.getState();
    if (frames.length > 0) {
      seek(0);
    }
  }, [clearSimulationTrajectories, seek, setFollowLatestPush, setPlaying, setReceivedSimulationModels]);

  useEffect(() => {
    const client = new BackendWsClient(getSimulationWsUrl(), {
      onServerMessage: (message) => dispatchMessageRef.current(message),
      onStatus: (status) => {
        setStreamStatus(status);
        if (status === "connected") {
          setError(null);
          return;
        }
        setWarapsStatus("disconnected");
        setMonitorStatus("disconnected");
        if (status === "disconnected" || status === "error") {
          usePlaybackStore.getState().setActiveScenarioId(null);
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
  }, [handleTransportError, setError, setStreamStatus, setWarapsStatus, setMonitorStatus]);

  const loadScenarioFromFile = useCallback(
    async (file: File | null) => {
      if (!file) {
        return;
      }
      if (usePlaybackStore.getState().streamStatus !== "connected") {
        setError("Backend socket is not connected.");
        return;
      }
      resetForNewScene();
      clearSimulationTrajectories();
      setPlaying(false);
      setFollowLatestPush(false);
      setError(null);
      const scenarioId = crypto.randomUUID();
      setActiveScenarioId(scenarioId);
      const fileContent = await file.text();
      clientRef.current?.send({
        type: "load_scenario_file",
        scenarioId,
        fileName: file.name,
        filePath: file.webkitRelativePath || file.name,
        fileContent,
      });
    },
    [
      clearSimulationTrajectories,
      resetForNewScene,
      setActiveScenarioId,
      setError,
      setFollowLatestPush,
      setPlaying,
    ]
  );

  return {
    /** @deprecated Use loadScenarioFromFile: loads scenario JSON via load_scenario_file. */
    initializeSimulation: loadScenarioFromFile,
    loadScenarioFromFile,
    startSimulation: () => {
      const currentStatus = usePlaybackStore.getState().simulationStatus;
      if (currentStatus !== "ready to start") {
        return;
      }
      clearSimulationTrajectories();
      setSimulationStatus("agents are preparing");
      clientRef.current?.send({ type: "start_simulation" });
    },
    resetSimulation: () => {
      prepareForSimulationReset();
      clientRef.current?.send({ type: "reset_simulation" });
    },
    setSpeed: (value: number) => {
      setSpeed(value);
    },
    seek: (value: number) => {
      seek(value);
    },
    sendMessage: (message: ClientToServerMessage) => {
      if (message.type === "initialize_simulation") {
        prepareForSimulationReset();
      }
      clientRef.current?.send(message);
    },
    enqueueSceneGeneration: (
      requestId: string,
      functionalScenarioContent: string,
      colregsConstraintsContent: string,
      vesselTypesContent: string,
      obstacleTypesContent: string,
      timeoutSeconds: number
    ) => {
      clientRef.current?.send({
        type: "generate_scene",
        requestId,
        functionalScenarioContent,
        colregsConstraintsContent,
        vesselTypesContent,
        obstacleTypesContent,
        timeout: timeoutSeconds,
      });
    },
    generateScene: (
      requestId: string,
      functionalScenarioContent: string,
      colregsConstraintsContent: string,
      vesselTypesContent: string,
      obstacleTypesContent: string,
      timeoutSeconds: number
    ) => {
      setActiveSceneGenerationRequestId(requestId);
      clientRef.current?.send({
        type: "generate_scene",
        requestId,
        functionalScenarioContent,
        colregsConstraintsContent,
        vesselTypesContent,
        obstacleTypesContent,
        timeout: timeoutSeconds,
      });
    },
    stopSceneGeneration: () => {
      usePlaybackStore.getState().cancelSceneGeneration();
      useBatchGenerationStore.getState().markAllBatchStopped();
      clientRef.current?.send({ type: "stop_scene_generation" });
    },
  };
}
