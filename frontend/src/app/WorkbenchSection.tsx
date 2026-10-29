import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { Disclosure } from "../components/Disclosure";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { usePlaybackTicker } from "../domain/playback/usePlaybackTicker";
import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../domain/playback/playbackStore";
import { PlaybackStoreContext } from "../domain/playback/playbackContext";
import { getClassContent } from "../domain/cluster/presetsApi";
import { useOperatorClient } from "../features/campaigns/useCampaignData";
import { useClusterDomain } from "../features/domain/useClusterDomain";
import { sceneInputSpecification } from "../features/workbench/pages/inputSpecification";
import { PageEntryStatus } from "../features/workbench/pages/PageEntryStatus";
import { inputOfFile, sceneOfScenePage, setTrajectoryInput } from "../features/workbench/pages/pageHandoff";
import { useScenePageStore } from "../features/workbench/pages/pageStore";
import { useLoadedRefresh, useTargetConsumer } from "../features/workbench/pages/useWorkbenchTargets";
import type { WorkbenchPage, WorkbenchTarget } from "../features/workbench/pages/workbenchTarget";
import { useUiStore, type WorkbenchView } from "./uiStore";
import { usePersistedState } from "./usePersistedState";
import {
  buildConnectMessage,
  connectionFormIsValid,
  useConnectionStore,
} from "../features/workbench/connection/connectionStore";
import { useSimulationWorkflow } from "../domain/simulation/useSimulationWorkflow";
import type { ClientToServerMessage } from "../domain/simulation/wireTypes";
import { SimulationRunPanel } from "../features/workbench/controls/SimulationRunPanel";
import { SceneGenerationSidebar } from "../features/workbench/controls/SceneGenerationSidebar";
import { SceneMonitorPreview } from "../features/workbench/controls/SceneMonitorPreview";
import { runBatchGeneration } from "../features/workbench/controls/runBatchGeneration";
import { TrajectoryGenerationControls } from "../features/workbench/controls/TrajectoryGenerationControls";
import { TrajectoryMonitorSidebar } from "../features/workbench/controls/TrajectoryMonitorSidebar";
import { MqttBrokerPanel } from "../features/workbench/connection/MqttBrokerPanel";
import { buildInitializeMonitorMessage, canInitializeMonitor } from "../features/workbench/controls/monitorConfig";
import { SCENE_GENERATION_JOB } from "../features/workbench/cluster/workbenchJobs";
import { describeResources } from "../features/workbench/cluster/workbenchResources";
import { SceneCanvas } from "../features/workbench/scene/SceneCanvas";
import { WorkbenchEncounterStrip } from "../features/workbench/monitor/WorkbenchEncounterPanels";
import { useBatchGenerationStore } from "../domain/sceneGeneration/batchGenerationStore";
import {
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "../domain/sceneGeneration/parseEvaluationDataFile";
import type { EvaluationData, SimulationFrame } from "../domain/simulation/types";
import { resolveGlobalErrorMessage } from "./globalErrorMessage";

interface WorkbenchSectionProps {
  /** Whether the workbench is the shown section. It stays mounted while hidden, so its socket and state survive. */
  active: boolean;
  /** Where the workbench's error bar is rendered (below the app body), or null before it exists. */
  errorSlot: HTMLElement | null;
}

/**
 * The workbench section: scene and trajectory generation, simulation and connections over the
 * workbench gateway socket (`VITE_WS_URL`). Its view is the `workbenchView` of `uiStore`. The
 * domain configuration is the active cluster's (the Domain Configuration section edits it), and
 * the functional scenarios to start from are the master's catalog.
 */
export function WorkbenchSection({ active, errorSlot }: WorkbenchSectionProps) {
  const RIGHT_PANE_MIN_WIDTH = 300;
  // The width of the expanded left pane (shell.css), to size the panes from the space that is left.
  const LEFT_PANE_WIDTH = 280;
  const RIGHT_PANE_MAX_WIDTH = 900;
  const RIGHT_PANE_MAX_WIDTH_RATIO = 0.85;
  const RIGHT_PANE_RESIZER_WIDTH = 6;
  const RIGHT_PANE_DEFAULT_CENTER_FRACTION = 3;
  const RIGHT_PANE_DEFAULT_RIGHT_FRACTION = 2;
  const BOTTOM_PANEL_MIN_HEIGHT = 140;
  const BOTTOM_PANEL_MAX_HEIGHT_RATIO = 0.85;
  const BOTTOM_PANEL_RESIZER_HEIGHT = 6;

  const streamControls = useSimulationWorkflow();
  const streamControlsRef = useRef(streamControls);
  streamControlsRef.current = streamControls;
  const autoConnectAttemptedRef = useRef(false);
  // Each page plays its own frames.
  usePlaybackTicker(usePlaybackStore);
  usePlaybackTicker(useScenePlaybackStore);
  usePlaybackTicker(useTrajectoryPlaybackStore);
  const rightPaneVisible = useUiStore((s) => s.rightPaneVisible);
  const setRightPaneVisible = useUiStore((s) => s.setRightPaneVisible);
  const errorMessage = usePlaybackStore((s) => s.errorMessage);
  const setError = usePlaybackStore((s) => s.setError);
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const simulationInitializing = usePlaybackStore((s) => s.simulationInitializing);
  const activeSceneGenerationRequestId = useScenePlaybackStore((s) => s.activeSceneGenerationRequestId);
  const batchGenerationRunning = useBatchGenerationStore((s) => s.running);
  const selectedBatchClassIds = useBatchGenerationStore((s) => s.selectedClassIds);
  const sceneGenerationTab = useUiStore((s) => s.sceneGenerationTab);
  const sceneGenerationLivePreview = useUiStore((s) => s.sceneGenerationLivePreview);
  const setSceneGenerationLivePreview = useUiStore((s) => s.setSceneGenerationLivePreview);
  const sceneGenerationPaneView = useUiStore((s) => s.sceneGenerationPaneView);
  const setControlPanelMode = useUiStore((s) => s.setControlPanelMode);
  const isSceneGenerationBusy =
    activeSceneGenerationRequestId !== null || batchGenerationRunning;
  const latestGeneratedScene = useScenePlaybackStore((s) => s.latestGeneratedScene);

  useEffect(() => {
    setSceneValidityBadgeDismissed(false);
  }, [latestGeneratedScene]);
  const clearVisualizedScenario = useScenePlaybackStore((s) => s.clearVisualizedScenario);
  const setVisualizedScenario = useScenePlaybackStore((s) => s.setVisualizedScenario);
  const requestAutoFit = usePlaybackStore((s) => s.requestAutoFit);
  const [scenarioSourceName, setScenarioSourceName] = usePersistedState<string | null>(
    "scenario-source-name",
    null
  );
  const [loadedScenarioFileContent, setLoadedScenarioFileContent] = useState<string | null>(null);
  const [rightPaneWidth, setRightPaneWidth] = useState<number | null>(null);
  const [sceneGenPaneWidth, setSceneGenPaneWidth] = useState(() =>
    typeof window !== "undefined"
      ? Math.max(RIGHT_PANE_MIN_WIDTH, Math.round((window.innerWidth - LEFT_PANE_WIDTH) * 0.45))
      : 600
  );
  const [isResizingRightPane, setIsResizingRightPane] = useState(false);
  const [bottomPanelHeight, setBottomPanelHeight] = useState<number | null>(null);
  const [isResizingBottomPanel, setIsResizingBottomPanel] = useState(false);
  const activeView = useUiStore((s) => s.workbenchView);
  const setActiveView = useUiStore((s) => s.setWorkbenchView);
  // The cluster's domain configuration, global for the cluster and kept on the master.
  const clusterDomain = useClusterDomain();
  const colregsConstraintsText = clusterDomain.data?.colregs_constants ?? "";
  const vesselTypesText = clusterDomain.data?.vessel_types ?? "";
  const obstacleTypesText = clusterDomain.data?.obstacle_types ?? "";
  const operatorClient = useOperatorClient();
  const [functionalSpecText, setFunctionalSpecText] = usePersistedState("functional-spec-text", "");
  // What the scene page calls its functional scenario: the preset or file it came from.
  const [functionalSpecLabel, setFunctionalSpecLabel] = usePersistedState<string | null>("functional-spec-label", null);
  const [sceneGenerationTimeoutSeconds, setSceneGenerationTimeoutSeconds] = usePersistedState(
    "scene-gen-timeout",
    240
  );
  const [enforceLowTcpa, setEnforceLowTcpa] = usePersistedState(
    "scene-generation-enforce-low-tcpa",
    false
  );
  const [sceneGenerationError, setSceneGenerationError] = useState<string | null>(null);
  const [sceneValidityBadgeDismissed, setSceneValidityBadgeDismissed] = useState(false);
  const mainLayoutRef = useRef<HTMLElement | null>(null);
  const simulationCenterRef = useRef<HTMLDivElement | null>(null);
  const previousViewRef = useRef<WorkbenchView>("simulation");
  const scenarioFileInputRef = useRef<HTMLInputElement | null>(null);

  /** A functional scenario of the master's catalog, by class id. */
  const loadScenarioText = useCallback(
    async (classId: string): Promise<string> => {
      if (operatorClient === null) {
        throw new Error("Select a cluster first: the functional scenarios come from its master.");
      }
      return getClassContent(operatorClient, classId);
    },
    [operatorClient]
  );

  useEffect(() => {
    let wasInitialized = usePlaybackStore.getState().simulationInitialized;
    const unsubscribe = usePlaybackStore.subscribe((state) => {
      if (!wasInitialized && state.simulationInitialized) {
        setControlPanelMode("animation");
        setActiveView("simulation");
      }
      wasInitialized = state.simulationInitialized;
    });
    return unsubscribe;
  }, [setActiveView, setControlPanelMode]);

  useEffect(() => {
    if (
      (activeView === "simulation" || activeView === "sceneGeneration") &&
      previousViewRef.current !== activeView
    ) {
      if (activeView === "simulation") {
        requestAutoFit();
      }
    }
    previousViewRef.current = activeView;
  }, [activeView, requestAutoFit]);

  // Auto-connect to the configured MQTT broker (the master's by default) once the server
  // socket connects, so a reconnect or refresh re-establishes the session hands-free.
  useEffect(() => {
    const attemptAutoConnect = () => {
      const conn = useConnectionStore.getState();
      if (usePlaybackStore.getState().mqttBrokerStatus === "connected") {
        return;
      }
      // Honour an explicit user Disconnect: do not silently reconnect on a
      // transient backend-socket blip.
      if (conn.userDisconnected) {
        return;
      }
      if (!connectionFormIsValid(conn)) {
        return;
      }
      // Mark the attempt so a failure lands in the connection panel with its hints,
      // exactly as it would for a Connect click.
      conn.beginConnectionAttempt();
      streamControlsRef.current.sendMessage(buildConnectMessage(conn));
    };
    const unsubscribe = usePlaybackStore.subscribe((state, prev) => {
      if (state.streamStatus === "connected" && prev.streamStatus !== "connected") {
        if (!autoConnectAttemptedRef.current) {
          autoConnectAttemptedRef.current = true;
          attemptAutoConnect();
        }
      } else if (state.streamStatus !== "connected" && prev.streamStatus === "connected") {
        autoConnectAttemptedRef.current = false;
      }
    });
    return unsubscribe;
  }, []);

  // The live monitor of the interactive simulation starts with the broker connection: it is
  // part of the session, not something to set up by hand.
  const colregsTextRef = useRef(colregsConstraintsText);
  useEffect(() => {
    colregsTextRef.current = colregsConstraintsText;
  }, [colregsConstraintsText]);

  // A scene loaded on the scene page brings its functional scenario into the editor, so it can be generated again or changed.
  const loadInputSpecification = useCallback(
    (target: WorkbenchTarget) => {
      if (target.page !== "sceneGeneration" || operatorClient === null) {
        return;
      }
      void sceneInputSpecification(operatorClient, target)
        .then((specification) => {
          if (specification !== null) {
            setFunctionalSpecText(specification.text);
            setFunctionalSpecLabel(specification.label);
          }
        })
        .catch((error: unknown) => {
          setSceneGenerationError(`The scene's functional scenario could not be loaded: ${error instanceof Error ? error.message : String(error)}`);
        });
    },
    [operatorClient, setFunctionalSpecLabel, setFunctionalSpecText]
  );

  // Outputs other sections open here (`openInWorkbench`), and the pages' loaded entries after a reload.
  const openTarget = useCallback(
    (target: WorkbenchTarget) => {
      if (target.page === "simulation") {
        usePlaybackStore.getState().requestAutoFit();
      }
      if (!target.live) {
        loadInputSpecification(target);
      }
      void streamControlsRef.current.openTarget(target, colregsTextRef.current);
    },
    [loadInputSpecification]
  );
  const refreshLoaded = useCallback((target: WorkbenchTarget) => {
    void streamControlsRef.current.refreshLoaded(target, colregsTextRef.current);
  }, []);
  const activePage: WorkbenchPage | null =
    activeView === "sceneGeneration" || activeView === "trajectoryGeneration" || activeView === "simulation" ? activeView : null;
  useTargetConsumer(active ? activePage : null, openTarget);
  useLoadedRefresh(streamControls.operatorUrl, refreshLoaded);
  useEffect(() => {
    const unsubscribe = usePlaybackStore.subscribe((state, prev) => {
      if (state.mqttBrokerStatus === "connected" && prev.mqttBrokerStatus !== "connected") {
        if (canInitializeMonitor(state.mqttBrokerStatus, state.monitorStatus, colregsTextRef.current)) {
          streamControlsRef.current.sendMessage(buildInitializeMonitorMessage(colregsTextRef.current));
        }
      }
    });
    return unsubscribe;
  }, []);

  const getClampedPaneWidth = useCallback((clientX: number) => {
    const rect = mainLayoutRef.current?.getBoundingClientRect();
    if (!rect) {
      return 420;
    }
    const widthFromRight = rect.right - clientX;
    const minCenterWidth = RIGHT_PANE_MIN_WIDTH;
    const maxByCenter = Math.max(
      RIGHT_PANE_MIN_WIDTH,
      rect.width - RIGHT_PANE_RESIZER_WIDTH - minCenterWidth
    );
    const maxByRatio = Math.max(
      RIGHT_PANE_MIN_WIDTH,
      Math.floor(rect.width * RIGHT_PANE_MAX_WIDTH_RATIO) - RIGHT_PANE_RESIZER_WIDTH
    );
    const maxWidth =
      activeView === "sceneGeneration"
        ? Math.max(RIGHT_PANE_MAX_WIDTH, maxByCenter)
        : Math.min(maxByCenter, maxByRatio);
    return Math.min(maxWidth, Math.max(RIGHT_PANE_MIN_WIDTH, widthFromRight));
  }, [activeView]);

  const onRightPaneResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsResizingRightPane(true);
      const applyWidth =
        activeView === "sceneGeneration" ? setSceneGenPaneWidth : setRightPaneWidth;
      applyWidth(getClampedPaneWidth(event.clientX));

      const onPointerMove = (moveEvent: PointerEvent) => {
        applyWidth(getClampedPaneWidth(moveEvent.clientX));
      };

      const onPointerUp = () => {
        setIsResizingRightPane(false);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp, { once: true });
    },
    [activeView, getClampedPaneWidth]
  );

  const getClampedBottomHeight = useCallback((clientY: number) => {
    const rect = simulationCenterRef.current?.getBoundingClientRect();
    if (!rect) {
      return 200;
    }
    const heightFromBottom = rect.bottom - clientY;
    const maxByContainer = Math.max(
      BOTTOM_PANEL_MIN_HEIGHT,
      rect.height - BOTTOM_PANEL_RESIZER_HEIGHT - 140
    );
    const maxByRatio = Math.max(
      BOTTOM_PANEL_MIN_HEIGHT,
      Math.floor(rect.height * BOTTOM_PANEL_MAX_HEIGHT_RATIO) - BOTTOM_PANEL_RESIZER_HEIGHT
    );
    const maxHeight = Math.min(maxByContainer, maxByRatio);
    return Math.min(maxHeight, Math.max(BOTTOM_PANEL_MIN_HEIGHT, heightFromBottom));
  }, []);

  // The simulation view gives the encounter canvas and its timeline three fifths by default.
  const defaultTopFraction = activeView === "simulation" ? 3 : 1;
  const defaultBottomFraction = activeView === "simulation" ? 2 : 1;
  const simulationBottomPanelGridRows =
    bottomPanelHeight !== null
      ? `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px ${bottomPanelHeight}px`
      : `minmax(0, ${defaultTopFraction}fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px minmax(0, ${defaultBottomFraction}fr)`;

  const onBottomPaneResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsResizingBottomPanel(true);
      setBottomPanelHeight(getClampedBottomHeight(event.clientY));

      const onPointerMove = (moveEvent: PointerEvent) => {
        setBottomPanelHeight(getClampedBottomHeight(moveEvent.clientY));
      };

      const onPointerUp = () => {
        setIsResizingBottomPanel(false);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp, { once: true });
    },
    [getClampedBottomHeight]
  );

  const readTextFile = useCallback(async (file: File): Promise<string> => file.text(), []);

  const canGenerateScene =
    functionalSpecText.trim().length > 0 &&
    colregsConstraintsText.trim().length > 0 &&
    vesselTypesText.trim().length > 0 &&
    obstacleTypesText.trim().length > 0;

  const domainReadyForGeneration =
    colregsConstraintsText.trim().length > 0 &&
    vesselTypesText.trim().length > 0 &&
    obstacleTypesText.trim().length > 0;
  const domainProblem = clusterDomain.isError
    ? `The cluster's domain configuration could not be read: ${clusterDomain.error instanceof Error ? clusterDomain.error.message : String(clusterDomain.error)}`
    : clusterDomain.isPending
      ? "Reading the cluster's domain configuration..."
      : "The cluster's domain configuration is incomplete: complete it on the Domain Configuration page of the cluster.";

  const globalErrorMessage = resolveGlobalErrorMessage(sceneGenerationError, errorMessage);
  const sceneGenerationResources = streamControls.clusterResources(SCENE_GENERATION_JOB);

  const showRightPane =
    activeView === "sceneGeneration" ||
    activeView === "trajectoryGeneration" ||
    (activeView === "simulation" && rightPaneVisible);

  const simulationRightPaneGridColumns =
    rightPaneWidth !== null
      ? `minmax(0, 1fr) ${RIGHT_PANE_RESIZER_WIDTH}px ${rightPaneWidth}px`
      : `minmax(0, ${RIGHT_PANE_DEFAULT_CENTER_FRACTION}fr) ${RIGHT_PANE_RESIZER_WIDTH}px minmax(0, ${RIGHT_PANE_DEFAULT_RIGHT_FRACTION}fr)`;

  const mainLayoutGridColumns = showRightPane
    ? activeView === "sceneGeneration"
      ? `minmax(0, 1fr) ${RIGHT_PANE_RESIZER_WIDTH}px ${sceneGenPaneWidth}px`
      : simulationRightPaneGridColumns
    : "minmax(0, 1fr)";

  const loadForTrajectoryGeneration = useCallback(() => {
    const handoff = sceneOfScenePage(scenarioSourceName ?? null);
    if (handoff === null) {
      return;
    }
    setTrajectoryInput(handoff.input, handoff.scene);
    setActiveView("trajectoryGeneration");
  }, [scenarioSourceName, setActiveView]);

  const runSceneGeneration = useCallback(
    async (specText: string) => {
      if (!domainReadyForGeneration) {
        return { ok: false, message: domainProblem };
      }
      clearVisualizedScenario();
      setLoadedScenarioFileContent(null);
      const requestId = crypto.randomUUID();
      const outcome = await streamControls.generateScene(requestId, {
        label: functionalSpecLabel ?? "functional scenario",
        functionalScenarioContent: specText,
        colregsConstraintsContent: colregsConstraintsText,
        vesselTypesContent: vesselTypesText,
        obstacleTypesContent: obstacleTypesText,
        timeoutSeconds: sceneGenerationTimeoutSeconds,
        enforceLowTcpa,
      });
      if (!outcome.ok) {
        return { ok: false, message: outcome.message, superseded: outcome.stopped };
      }
      if (!outcome.valid) {
        return { ok: false, message: "The generation found no valid scene within its timeout. The best attempt is shown." };
      }
      return { ok: true, evaluationData: outcome.evaluationData, scene: outcome.scene };
    },
    [
      clearVisualizedScenario,
      colregsConstraintsText,
      domainProblem,
      domainReadyForGeneration,
      enforceLowTcpa,
      functionalSpecLabel,
      obstacleTypesText,
      sceneGenerationTimeoutSeconds,
      streamControls,
      vesselTypesText,
    ]
  );

  const generateBatch = useCallback(
    async (rows: { requestId: string; label: string; specText: string }[]) => {
      if (!domainReadyForGeneration) return;
      await streamControls.generateBatch(
        rows.map((row) => ({ requestId: row.requestId, label: row.label, functionalScenarioContent: row.specText })),
        {
          colregsConstraintsContent: colregsConstraintsText,
          vesselTypesContent: vesselTypesText,
          obstacleTypesContent: obstacleTypesText,
          timeoutSeconds: sceneGenerationTimeoutSeconds,
          enforceLowTcpa,
        }
      );
    },
    [
      colregsConstraintsText,
      domainReadyForGeneration,
      enforceLowTcpa,
      obstacleTypesText,
      sceneGenerationTimeoutSeconds,
      streamControls,
      vesselTypesText,
    ]
  );

  const loadScenarioOnBackend = useCallback(
    async (
      evaluationData: EvaluationData,
      scene: SimulationFrame,
      fileName = "generated_scene.json",
      fileContent?: string
    ) => {
      const content =
        fileContent ?? formatScenarioJsonForExport(evaluationData, scene);
      await streamControls.setSimulationInput(inputOfFile(fileName), content, { colregsConstraintsContent: colregsConstraintsText });
      setControlPanelMode("animation");
      setActiveView("simulation");
      requestAutoFit();
    },
    [colregsConstraintsText, streamControls, requestAutoFit, setActiveView, setControlPanelMode]
  );

  const handleScenarioFileSelected = useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        const { evaluationData, scene, hasFullTrajectories } = parseScenarioFile(text);
        setVisualizedScenario({ scene, evaluationData, valid: true });
        // A scene from a file is no entry: the page shows it until a run or a loaded entry replaces it.
        useScenePageStore.getState().setLocalOutput({ label: file.name, ref: null, source: { file: file.name } });
        setLoadedScenarioFileContent(hasFullTrajectories ? text : null);
        setScenarioSourceName(file.name);
        setSceneGenerationError(null);
        // The cluster's post-hoc monitor judges the first scene; its verdicts merge into the shown scene.
        void streamControls.monitorScene(crypto.randomUUID(), JSON.parse(text) as Record<string, unknown>, colregsConstraintsText);
      } catch (error) {
        setScenarioSourceName(null);
        setLoadedScenarioFileContent(null);
        clearVisualizedScenario();
        setSceneGenerationError(
          error instanceof Error ? error.message : "Failed to parse scenario file."
        );
      }
    },
    [
      clearVisualizedScenario,
      colregsConstraintsText,
      setVisualizedScenario,
      setScenarioSourceName,
      streamControls,
    ]
  );

  const initializeVisualizedScenario = useCallback(async () => {
    const visualized = useScenePlaybackStore.getState().latestGeneratedScene;
    if (!visualized?.valid || !visualized.evaluationData) {
      return;
    }
    try {
      await loadScenarioOnBackend(
        visualized.evaluationData,
        visualized.scene,
        scenarioSourceName ?? "generated_scene.json",
        loadedScenarioFileContent ?? undefined
      );
      setSceneGenerationError(null);
    } catch (error) {
      setSceneGenerationError(
        error instanceof Error ? error.message : "Failed to load scenario on backend."
      );
    }
  }, [loadScenarioOnBackend, loadedScenarioFileContent, scenarioSourceName]);

  const exportTextFile = useCallback((content: string, fileName: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  // The canvas, the playback bar and the monitor panels read the shown page's frames.
  const shownPlayback =
    activeView === "sceneGeneration" ? useScenePlaybackStore : activeView === "trajectoryGeneration" ? useTrajectoryPlaybackStore : usePlaybackStore;

  return (
    <PlaybackStoreContext.Provider value={shownPlayback}>
      <main
        ref={mainLayoutRef}
        className={`main-layout${isResizingRightPane ? " is-resizing" : ""}`}
        style={{ gridTemplateColumns: mainLayoutGridColumns }}
        hidden={!active}
      >
        <section className="center-pane">
          {activeView === "connections" ? (
            <div className="load-scenario-layout mqtt-broker-view">
              <MqttBrokerPanel sendMessage={(message: ClientToServerMessage) => streamControls.sendMessage(message)} />
            </div>
          ) : activeView === "sceneGeneration" ? (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{
                gridTemplateRows:
                  bottomPanelHeight !== null
                    ? `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px ${bottomPanelHeight}px`
                    : `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px 380px`,
              }}
            >
              <div className="simulation-center-stage">
                {activeSceneGenerationRequestId && (
                  <LoadingSpinner label="Generating scene…" />
                )}
                {latestGeneratedScene && !sceneValidityBadgeDismissed && (
                  <p
                    className={`scene-validity-badge${latestGeneratedScene.valid ? " scene-validity-badge--valid" : " scene-validity-badge--invalid"}`}
                    role="button"
                    tabIndex={0}
                    title="Click to dismiss"
                    onClick={() => setSceneValidityBadgeDismissed(true)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSceneValidityBadgeDismissed(true);
                      }
                    }}
                  >
                    {latestGeneratedScene.valid
                      ? "Displayed scene: valid (complies with specification)"
                      : "Displayed scene: invalid (generation in progress)"}
                  </p>
                )}
                <div className="scene-host">
                  <SceneCanvas generatedScene={latestGeneratedScene?.scene ?? null} />
                </div>
              </div>
              <div
                className="bottom-pane-resizer"
                onPointerDown={onBottomPaneResizeStart}
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize bottom scene generation panel"
              />
              <footer className="bottom-toolbar bottom-toolbar-compact bottom-toolbar-single">
                <div className="bottom-slot bottom-slot-controls">
                  <div className="control-panel-heading">
                    <div>
                      <p className="control-panel-eyebrow">Step 1 of 3</p>
                      <h3>Scene Generation</h3>
                    </div>
                    <div className="control-panel-status">
                      <span className="meta" role="status">
                        Scene:{" "}
                        {latestGeneratedScene
                          ? scenarioSourceName
                            ? `from file (${scenarioSourceName})`
                            : "generated"
                          : "none yet"}
                      </span>
                      <span className="meta" title="Scene generation runs as jobs on the active cluster">
                        Cluster: {describeResources(sceneGenerationResources)}
                      </span>
                    </div>
                  </div>
                  {sceneGenerationResources.blocker !== null && (
                    <p className="meta resource-blocker" role="status">
                      {sceneGenerationResources.blocker}
                    </p>
                  )}
                  <PageEntryStatus store={useScenePageStore} />
                  <p className="meta">
                    Scenario: {functionalSpecLabel ?? (functionalSpecText.trim().length > 0 ? "written in the editor" : "none yet")}. Every
                    generation is saved as an entry of Campaign History.
                  </p>
                  <div className="toolbar-row scene-generation-toolbar">
                    {(() => {
                      const isBatch = sceneGenerationTab === "batch";
                      const sceneCount = isBatch ? selectedBatchClassIds.length : 1;
                      const disabled =
                        sceneGenerationResources.blocker !== null ||
                        (isBatch
                          ? !domainReadyForGeneration ||
                            isSceneGenerationBusy ||
                            selectedBatchClassIds.length === 0
                          : !canGenerateScene || isSceneGenerationBusy);
                      return (
                        <button
                          className="primary-btn accent"
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            setSceneGenerationError(null);
                            if (isBatch) {
                              void runBatchGeneration({
                                selectedClassIds: selectedBatchClassIds,
                                loadScenarioText,
                                generateBatch,
                                sceneGenerationTimeoutSeconds,
                                isAborted: () =>
                                  !useBatchGenerationStore.getState().running,
                              });
                              return;
                            }
                            void (async () => {
                              const outcome = await runSceneGeneration(functionalSpecText);
                              if (!outcome.ok && !outcome.superseded) {
                                setSceneGenerationError(
                                  outcome.message ?? "Scene generation failed."
                                );
                              } else if (outcome.ok) {
                                setScenarioSourceName(null);
                              }
                            })();
                          }}
                        >
                          {sceneCount === 1 ? "Generate scene" : `Generate ${sceneCount} scenes`}
                        </button>
                      );
                    })()}
                    <button
                      type="button"
                      disabled={!isSceneGenerationBusy}
                      onClick={() => {
                        streamControls.stopSceneGeneration();
                        setSceneGenerationError("Scene generation stopped.");
                      }}
                    >
                      Stop
                    </button>
                    <button
                      type="button"
                      className={
                        latestGeneratedScene?.valid && latestGeneratedScene.evaluationData
                          ? "primary-btn accent"
                          : undefined
                      }
                      disabled={
                        isSceneGenerationBusy ||
                        !latestGeneratedScene?.valid ||
                        !latestGeneratedScene.evaluationData
                      }
                      onClick={loadForTrajectoryGeneration}
                    >
                      Next: Trajectory Generation
                    </button>
                  </div>
                  {!domainReadyForGeneration ? (
                    <p className="meta">{domainProblem}</p>
                  ) : (
                    !canGenerateScene &&
                    sceneGenerationTab === "single" && <p className="meta">Choose or write a scenario specification on the right to enable generating.</p>
                  )}
                  <Disclosure
                    id="scene-gen:options"
                    variant="plain"
                    headingLevel={4}
                    title="Generation options"
                    hint={`${sceneGenerationTimeoutSeconds} s timeout${enforceLowTcpa ? ", low TCPA" : ""}${sceneGenerationLivePreview ? "" : ", no live preview"}`}
                  >
                    <div className="scene-generation-trigger-group">
                      <label className="check scene-generation-preview-toggle">
                        <input
                          type="checkbox"
                          checked={sceneGenerationLivePreview}
                          onChange={(e) => setSceneGenerationLivePreview(e.target.checked)}
                          aria-label="Live preview visualization during scene generation"
                        />
                        <span>Live preview</span>
                      </label>
                      <label className="check scene-generation-preview-toggle">
                        <input
                          type="checkbox"
                          checked={enforceLowTcpa}
                          onChange={(e) => setEnforceLowTcpa(e.target.checked)}
                          aria-label="Enforce low TCPA when generating a COLREGS situation"
                        />
                        <span>Enforce low TCPA</span>
                      </label>
                      <label className="toolbar-timeout">
                        <span className="toolbar-timeout-label">Timeout (s)</span>
                        <input
                          className="toolbar-timeout-input"
                          type="number"
                          min={1}
                          max={86400}
                          step={1}
                          value={sceneGenerationTimeoutSeconds}
                          onChange={(e) => {
                            const v = Number.parseInt(e.target.value, 10);
                            if (Number.isFinite(v)) {
                              setSceneGenerationTimeoutSeconds(Math.min(86400, Math.max(1, v)));
                            }
                          }}
                          aria-label="Scene generation timeout in seconds"
                        />
                      </label>
                    </div>
                  </Disclosure>
                  <Disclosure
                    id="scene-gen:more-actions"
                    variant="plain"
                    headingLevel={4}
                    title="More scene actions"
                    hint="Load or export a scenario file, skip to simulation"
                    keepMounted
                  >
                    <div className="scene-scenario-actions">
                      <input
                        ref={scenarioFileInputRef}
                        type="file"
                        accept="application/json,.json"
                        hidden
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) {
                            void handleScenarioFileSelected(file);
                          }
                          e.target.value = "";
                        }}
                      />
                      <button
                        type="button"
                        disabled={isSceneGenerationBusy}
                        onClick={() => scenarioFileInputRef.current?.click()}
                      >
                        Load Scenario File...
                      </button>
                      <button
                        type="button"
                        disabled={
                          simulationInitializing ||
                          streamStatus !== "connected" ||
                          !latestGeneratedScene?.valid ||
                          !latestGeneratedScene.evaluationData
                        }
                        onClick={() => {
                          void initializeVisualizedScenario();
                        }}
                      >
                        Load for Simulation
                      </button>
                      <button
                        type="button"
                        disabled={
                          isSceneGenerationBusy ||
                          !latestGeneratedScene?.valid ||
                          !latestGeneratedScene.evaluationData
                        }
                        onClick={() => {
                          if (
                            !latestGeneratedScene?.valid ||
                            !latestGeneratedScene.evaluationData
                          ) {
                            return;
                          }
                          exportTextFile(
                            loadedScenarioFileContent ??
                              formatScenarioJsonForExport(
                                latestGeneratedScene.evaluationData,
                                latestGeneratedScene.scene
                              ),
                            scenarioSourceName ?? "generated_scene.json",
                            "application/json"
                          );
                        }}
                      >
                        Export Scenario
                      </button>
                    </div>
                  </Disclosure>
                </div>
              </footer>
            </div>
          ) : activeView === "trajectoryGeneration" ? (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{ gridTemplateRows: simulationBottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                <div className="scene-host">
                  <SceneCanvas />
                </div>
              </div>
              <div
                className="bottom-pane-resizer"
                onPointerDown={onBottomPaneResizeStart}
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize bottom trajectory generation panel"
              />
              <footer className="bottom-toolbar bottom-toolbar-compact bottom-toolbar-single">
                <div className="bottom-slot bottom-slot-controls">
                  <TrajectoryGenerationControls
                    streamControls={streamControls}
                    colregsConstraintsContent={colregsConstraintsText}
                    onNavigateToSimulation={() => {
                      requestAutoFit();
                      setControlPanelMode("animation");
                      setActiveView("simulation");
                    }}
                  />
                </div>
              </footer>
            </div>
          ) : (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{ gridTemplateRows: simulationBottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                <div className="scene-host">
                  <SceneCanvas />
                </div>
                <WorkbenchEncounterStrip streamControls={streamControls} />
              </div>
              <div
                className="bottom-pane-resizer"
                onPointerDown={onBottomPaneResizeStart}
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize bottom control panel"
              />
              <footer className="bottom-toolbar bottom-toolbar-compact bottom-toolbar-single">
                <div className="bottom-slot bottom-slot-controls">
                  <SimulationRunPanel streamControls={streamControls} colregsConstraintsContent={colregsConstraintsText} />
                </div>
              </footer>
            </div>
          )}
        </section>

        {activeView === "simulation" && !rightPaneVisible && (
          <button
            type="button"
            className="right-pane-show-btn"
            onClick={() => setRightPaneVisible(true)}
            aria-label="Show monitoring panel"
            title="Show monitoring panel"
          >
            <span className="right-pane-show-icon" aria-hidden>
              ◀
            </span>
            <span className="right-pane-show-label">Monitor</span>
          </button>
        )}

        {showRightPane && (
          <>
            <div
              className="right-pane-resizer"
              onPointerDown={onRightPaneResizeStart}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize right panel"
            />
            {activeView === "simulation" || activeView === "trajectoryGeneration" ? (
              <TrajectoryMonitorSidebar previewOnly={activeView === "trajectoryGeneration"} />
            ) : sceneGenerationPaneView === "monitor" ? (
              <SceneMonitorPreview />
            ) : (
              <SceneGenerationSidebar
                functionalSpecText={functionalSpecText}
                onFunctionalSpecTextChange={(text) => {
                  setFunctionalSpecText(text);
                  setFunctionalSpecLabel((label) => (label === null || label.endsWith(" (edited)") ? label : `${label} (edited)`));
                }}
                onLoadFunctionalSpecFromPreset={(classId) => {
                  void (async () => {
                    try {
                      const text = await loadScenarioText(classId);
                      setFunctionalSpecText(text);
                      setFunctionalSpecLabel(classId);
                      setSceneGenerationError(null);
                    } catch (error) {
                      setSceneGenerationError(
                        error instanceof Error ? `The functional scenario could not be loaded: ${error.message}` : "The functional scenario could not be loaded."
                      );
                    }
                  })();
                }}
                loadScenarioText={loadScenarioText}
                onLoadFunctionalSpecFromFile={(file) => {
                  void (async () => {
                    const text = await readTextFile(file);
                    setFunctionalSpecText(text);
                    setFunctionalSpecLabel(file.name);
                    setSceneGenerationError(null);
                  })();
                }}
                onExportFunctionalSpec={() =>
                  exportTextFile(functionalSpecText, "functional_scenario.problem", "text/plain")
                }
                isSceneGenerationBusy={isSceneGenerationBusy}
                onVisualizeFromEvaluation={(evaluationData, scene) => {
                  // A batch row's scene is a case of the batch entry: the page loads it from there, with its monitor frame.
                  const target = useBatchGenerationStore.getState().results.find((row) => row.scene === scene)?.target;
                  if (target) {
                    setLoadedScenarioFileContent(null);
                    setScenarioSourceName(null);
                    setSceneGenerationError(null);
                    openTarget(target);
                    return;
                  }
                  setVisualizedScenario({ scene, evaluationData, valid: true });
                  useScenePageStore.getState().setLocalOutput(null);
                  setLoadedScenarioFileContent(null);
                  setScenarioSourceName(null);
                  setSceneGenerationError(null);
                }}
                activeScene={latestGeneratedScene?.scene ?? null}
              />
            )}
          </>
        )}
      </main>
      {globalErrorMessage &&
        errorSlot &&
        createPortal(
          <footer
            className="global-error-bar"
            role="alert"
            aria-live="assertive"
            title="Click to dismiss"
            onClick={() => {
              setSceneGenerationError(null);
              setError(null);
            }}
          >
            {globalErrorMessage}
          </footer>,
          errorSlot
        )}
    </PlaybackStoreContext.Provider>
  );
}
