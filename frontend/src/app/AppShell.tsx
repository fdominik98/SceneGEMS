import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { LeftPane, type AppView } from "./LeftPane";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { usePlaybackTicker } from "../domain/playback/usePlaybackTicker";
import { usePlaybackStore } from "../domain/playback/playbackStore";
import { useUiStore } from "./uiStore";
import { usePersistedState } from "./usePersistedState";
import {
  connectionFormIsValid,
  useConnectionStore,
} from "../features/connection/connectionStore";
import { useSimulationWorkflow } from "../domain/simulation/useSimulationWorkflow";
import type { ClientToServerMessage } from "../domain/simulation/wireTypes";
import { PlaybackControls } from "../features/controls/PlaybackControls";
import { DomainConfigurationPanel } from "../features/controls/DomainConfigurationPanel";
import {
  DEFAULT_COLREGS_PRESET,
  DEFAULT_OBSTACLE_TYPES_PRESET,
  DEFAULT_VESSEL_TYPES_PRESET,
} from "../features/controls/domainConfigPresets";
import { SceneGenerationSidebar } from "../features/controls/SceneGenerationSidebar";
import { runBatchGeneration } from "../features/controls/runBatchGeneration";
import { TrajectoryGenerationControls } from "../features/controls/TrajectoryGenerationControls";
import { TrajectoryMonitorSidebar } from "../features/controls/TrajectoryMonitorSidebar";
import { useTrajectoryGenerationStore } from "../domain/trajectoryGeneration/trajectoryGenerationStore";
import { WarapsConnectionPanel } from "../features/connection/WarapsConnectionPanel";
import { SceneCanvas } from "../features/scene/SceneCanvas";
import { waitForSceneGeneration } from "../domain/playback/waitForSceneGeneration";
import { useBatchGenerationStore } from "../domain/sceneGeneration/batchGenerationStore";
import {
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "../domain/sceneGeneration/parseEvaluationDataFile";
import type { EvaluationData, SimulationFrame } from "../domain/simulation/types";
import { resolveGlobalErrorMessage } from "./globalErrorMessage";

const APP_TITLE = "SceneGEMS";

export function AppShell() {
  useEffect(() => {
    document.title = APP_TITLE;
  }, []);

  const RIGHT_PANE_MIN_WIDTH = 300;
  const RIGHT_PANE_MAX_WIDTH = 900;
  const RIGHT_PANE_MAX_WIDTH_RATIO = 0.85;
  const RIGHT_PANE_RESIZER_WIDTH = 8;
  const RIGHT_PANE_DEFAULT_CENTER_FRACTION = 3;
  const RIGHT_PANE_DEFAULT_RIGHT_FRACTION = 2;
  const BOTTOM_PANEL_MIN_HEIGHT = 140;
  const BOTTOM_PANEL_MAX_HEIGHT_RATIO = 0.85;
  const BOTTOM_PANEL_RESIZER_HEIGHT = 8;

  const streamControls = useSimulationWorkflow();
  const streamControlsRef = useRef(streamControls);
  streamControlsRef.current = streamControls;
  const autoConnectAttemptedRef = useRef(false);
  usePlaybackTicker();
  const rightPaneVisible = useUiStore((s) => s.rightPaneVisible);
  const setRightPaneVisible = useUiStore((s) => s.setRightPaneVisible);
  const errorMessage = usePlaybackStore((s) => s.errorMessage);
  const setError = usePlaybackStore((s) => s.setError);
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const simulationInitializing = usePlaybackStore((s) => s.simulationInitializing);
  const activeSceneGenerationRequestId = usePlaybackStore((s) => s.activeSceneGenerationRequestId);
  const batchGenerationRunning = useBatchGenerationStore((s) => s.running);
  const selectedBatchPaths = useBatchGenerationStore((s) => s.selectedPaths);
  const setTrajectoryHandoffScene = useTrajectoryGenerationStore((s) => s.setHandoffScene);
  const sceneGenerationTab = useUiStore((s) => s.sceneGenerationTab);
  const sceneGenerationLivePreview = useUiStore((s) => s.sceneGenerationLivePreview);
  const setSceneGenerationLivePreview = useUiStore((s) => s.setSceneGenerationLivePreview);
  const isSceneGenerationBusy =
    activeSceneGenerationRequestId !== null || batchGenerationRunning;
  const latestGeneratedScene = usePlaybackStore((s) => s.latestGeneratedScene);

  useEffect(() => {
    setSceneValidityBadgeDismissed(false);
  }, [latestGeneratedScene]);
  const clearVisualizedScenario = usePlaybackStore((s) => s.clearVisualizedScenario);
  const setVisualizedScenario = usePlaybackStore((s) => s.setVisualizedScenario);
  const requestAutoFit = usePlaybackStore((s) => s.requestAutoFit);
  const [scenarioSourceName, setScenarioSourceName] = usePersistedState<string | null>(
    "scenario-source-name",
    null
  );
  const [loadedScenarioFileContent, setLoadedScenarioFileContent] = useState<string | null>(null);
  const [rightPaneWidth, setRightPaneWidth] = useState<number | null>(null);
  const [sceneGenPaneWidth, setSceneGenPaneWidth] = useState(() =>
    typeof window !== "undefined"
      ? Math.max(RIGHT_PANE_MIN_WIDTH, Math.round(window.innerWidth / 2))
      : 600
  );
  const [isResizingRightPane, setIsResizingRightPane] = useState(false);
  const [bottomPanelHeight, setBottomPanelHeight] = useState<number | null>(null);
  const [isResizingBottomPanel, setIsResizingBottomPanel] = useState(false);
  const [isLeftMenuCollapsed, setIsLeftMenuCollapsed] = useState(true);
  const [activeView, setActiveView] = usePersistedState<AppView>("active-view", "simulation");
  const [colregsConstraintsText, setColregsConstraintsText] = usePersistedState("colregs-text", "");
  const [vesselTypesText, setVesselTypesText] = usePersistedState("vessel-types-text", "");
  const [obstacleTypesText, setObstacleTypesText] = usePersistedState("obstacle-types-text", "");
  const [functionalSpecText, setFunctionalSpecText] = usePersistedState("functional-spec-text", "");
  const [sceneGenerationTimeoutSeconds, setSceneGenerationTimeoutSeconds] = usePersistedState(
    "scene-gen-timeout",
    240
  );
  const [sceneGenerationError, setSceneGenerationError] = useState<string | null>(null);
  const [sceneValidityBadgeDismissed, setSceneValidityBadgeDismissed] = useState(false);
  const [domainConfigLoading, setDomainConfigLoading] = useState(true);
  const mainLayoutRef = useRef<HTMLElement | null>(null);
  const simulationCenterRef = useRef<HTMLDivElement | null>(null);
  const previousViewRef = useRef<AppView>("simulation");
  const scenarioFileInputRef = useRef<HTMLInputElement | null>(null);

  const loadTextFromPreset = useCallback(async (path: string): Promise<string> => {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`Failed to load preset ${path}: ${response.status}`);
    }
    return response.text();
  }, []);

  useEffect(() => {
    // Only fetch default presets for fields the user has not already edited
    // (persisted edits are restored before this runs).
    const needColregs = colregsConstraintsText.trim().length === 0;
    const needVessels = vesselTypesText.trim().length === 0;
    const needObstacles = obstacleTypesText.trim().length === 0;
    if (!needColregs && !needVessels && !needObstacles) {
      setDomainConfigLoading(false);
      return;
    }
    void (async () => {
      setDomainConfigLoading(true);
      try {
        const [colregs, vessels, obstacles] = await Promise.all([
          needColregs ? loadTextFromPreset(DEFAULT_COLREGS_PRESET) : Promise.resolve(null),
          needVessels ? loadTextFromPreset(DEFAULT_VESSEL_TYPES_PRESET) : Promise.resolve(null),
          needObstacles ? loadTextFromPreset(DEFAULT_OBSTACLE_TYPES_PRESET) : Promise.resolve(null),
        ]);
        if (colregs !== null) setColregsConstraintsText(colregs);
        if (vessels !== null) setVesselTypesText(vessels);
        if (obstacles !== null) setObstacleTypesText(obstacles);
      } catch (error) {
        setSceneGenerationError(
          error instanceof Error ? error.message : "Failed to load default domain configuration presets."
        );
      } finally {
        setDomainConfigLoading(false);
      }
    })();
    // Runs once on mount; reads initial (restored) values intentionally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadTextFromPreset]);

  useEffect(() => {
    let wasInitialized = usePlaybackStore.getState().simulationInitialized;
    const unsubscribe = usePlaybackStore.subscribe((state) => {
      if (!wasInitialized && state.simulationInitialized) {
        setActiveView("simulation");
      }
      wasInitialized = state.simulationInitialized;
    });
    return unsubscribe;
  }, [setActiveView]);

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

  // Auto-connect to the configured (default) WARA-PS profile once the backend
  // socket connects, so a reconnect/refresh re-establishes the session hands-free.
  useEffect(() => {
    const attemptAutoConnect = () => {
      const conn = useConnectionStore.getState();
      if (usePlaybackStore.getState().warapsStatus === "connected") {
        return;
      }
      // Honour an explicit user Disconnect: do not silently reconnect on a
      // transient backend-socket blip.
      if (conn.userDisconnectedWaraps) {
        return;
      }
      if (!connectionFormIsValid(conn)) {
        return;
      }
      streamControlsRef.current.sendMessage({
        type: "connect_to_waraps",
        user: conn.user.trim(),
        password: conn.password,
        agent_broker: conn.agentBroker.trim(),
        client_broker: conn.clientBroker.trim(),
        port: conn.port,
        tls_connection: conn.tlsConnection,
        allow_certificates: conn.allowCertificates,
        geofence: conn.geofence,
      });
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

  const simulationBottomPanelGridRows =
    bottomPanelHeight !== null
      ? `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px ${bottomPanelHeight}px`
      : `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px minmax(0, 1fr)`;

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

  const globalErrorMessage = resolveGlobalErrorMessage(sceneGenerationError, errorMessage);

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
    const visualized = usePlaybackStore.getState().latestGeneratedScene;
    if (!visualized?.valid || !visualized.evaluationData) {
      return;
    }
    setTrajectoryHandoffScene(
      { scene: visualized.scene, evaluationData: visualized.evaluationData, valid: true },
      scenarioSourceName ?? null
    );
    setActiveView("trajectoryGeneration");
  }, [scenarioSourceName, setActiveView, setTrajectoryHandoffScene]);

  const runSceneGeneration = useCallback(
    async (specText: string) => {
      if (!domainReadyForGeneration) {
        return { ok: false, message: "Domain configuration is incomplete." };
      }
      clearVisualizedScenario();
      setLoadedScenarioFileContent(null);
      const requestId = crypto.randomUUID();
      streamControls.generateScene(
        requestId,
        specText,
        colregsConstraintsText,
        vesselTypesText,
        obstacleTypesText,
        sceneGenerationTimeoutSeconds
      );
      const outcome = await waitForSceneGeneration(requestId, sceneGenerationTimeoutSeconds);
      if (!outcome.ok) {
        return {
          ok: false,
          message: outcome.message ?? "No valid scene received.",
          superseded: outcome.superseded,
        };
      }
      if (!outcome.scene?.evaluationData) {
        return { ok: false, message: "No valid scene received." };
      }
      return {
        ok: true,
        evaluationData: outcome.scene.evaluationData,
        scene: outcome.scene.scene,
      };
    },
    [
      clearVisualizedScenario,
      colregsConstraintsText,
      domainReadyForGeneration,
      obstacleTypesText,
      sceneGenerationTimeoutSeconds,
      streamControls,
      vesselTypesText,
    ]
  );

  const enqueueSceneGeneration = useCallback(
    (requestId: string, specText: string) => {
      if (!domainReadyForGeneration) return;
      streamControls.enqueueSceneGeneration(
        requestId,
        specText,
        colregsConstraintsText,
        vesselTypesText,
        obstacleTypesText,
        sceneGenerationTimeoutSeconds
      );
    },
    [
      colregsConstraintsText,
      domainReadyForGeneration,
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
      const evaluationFile = new File([content], fileName, { type: "application/json" });
      await streamControls.loadScenarioFromFile(evaluationFile);
      setActiveView("simulation");
      requestAutoFit();
    },
    [streamControls, requestAutoFit, setActiveView]
  );

  const handleScenarioFileSelected = useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        const { evaluationData, scene, hasFullTrajectories } = parseScenarioFile(text);
        setVisualizedScenario({ scene, evaluationData, valid: true });
        setLoadedScenarioFileContent(hasFullTrajectories ? text : null);
        setScenarioSourceName(file.name);
        setSceneGenerationError(null);
      } catch (error) {
        setScenarioSourceName(null);
        setLoadedScenarioFileContent(null);
        clearVisualizedScenario();
        setSceneGenerationError(
          error instanceof Error ? error.message : "Failed to parse scenario file."
        );
      }
    },
    [clearVisualizedScenario, setVisualizedScenario, setScenarioSourceName]
  );

  const initializeVisualizedScenario = useCallback(async () => {
    const visualized = usePlaybackStore.getState().latestGeneratedScene;
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

  return (
    <div className="app-shell">
      <div
        className="app-body"
        style={{ gridTemplateColumns: `${isLeftMenuCollapsed ? 56 : 240}px minmax(0, 1fr)` }}
      >
        <LeftPane
          isCollapsed={isLeftMenuCollapsed}
          onToggleCollapse={() => setIsLeftMenuCollapsed((v) => !v)}
          activeMenu={activeView}
          onAppViewSelect={(view) => {
            if (view === "simulation") {
              requestAutoFit();
            }
            setActiveView(view);
          }}
        />

        <main
          ref={mainLayoutRef}
          className={`main-layout${isResizingRightPane ? " is-resizing" : ""}`}
          style={{ gridTemplateColumns: mainLayoutGridColumns }}
        >
          <section className="center-pane">
            {activeView === "waraps" ? (
              <div className="load-scenario-layout waraps-view">
                <WarapsConnectionPanel
                  sendMessage={(message: ClientToServerMessage) => streamControls.sendMessage(message)}
                />
              </div>
            ) : activeView === "domainConfig" ? (
              <div className="load-scenario-layout">
                {domainConfigLoading && <LoadingSpinner label="Loading domain presets…" />}
                <DomainConfigurationPanel
                  colregsText={colregsConstraintsText}
                  onColregsTextChange={setColregsConstraintsText}
                  onLoadColregsFromPreset={(path) => {
                    void (async () => {
                      try {
                        const text = await loadTextFromPreset(path);
                        setColregsConstraintsText(text);
                        setSceneGenerationError(null);
                      } catch (error) {
                        setSceneGenerationError(
                          error instanceof Error ? error.message : "Failed to load COLREGS preset."
                        );
                      }
                    })();
                  }}
                  onLoadColregsFromFile={(file) => {
                    void (async () => {
                      const text = await readTextFile(file);
                      setColregsConstraintsText(text);
                      setSceneGenerationError(null);
                    })();
                  }}
                  onExportColregs={() =>
                    exportTextFile(colregsConstraintsText, "colregs_constants.yaml", "text/yaml")
                  }
                  vesselTypesText={vesselTypesText}
                  onVesselTypesTextChange={setVesselTypesText}
                  onLoadVesselTypesFromPreset={(path) => {
                    void (async () => {
                      try {
                        const text = await loadTextFromPreset(path);
                        setVesselTypesText(text);
                        setSceneGenerationError(null);
                      } catch (error) {
                        setSceneGenerationError(
                          error instanceof Error ? error.message : "Failed to load vessel types preset."
                        );
                      }
                    })();
                  }}
                  onLoadVesselTypesFromFile={(file) => {
                    void (async () => {
                      const text = await readTextFile(file);
                      setVesselTypesText(text);
                      setSceneGenerationError(null);
                    })();
                  }}
                  onExportVesselTypes={() =>
                    exportTextFile(vesselTypesText, "vessel_types.yaml", "text/yaml")
                  }
                  obstacleTypesText={obstacleTypesText}
                  onObstacleTypesTextChange={setObstacleTypesText}
                  onLoadObstacleTypesFromPreset={(path) => {
                    void (async () => {
                      try {
                        const text = await loadTextFromPreset(path);
                        setObstacleTypesText(text);
                        setSceneGenerationError(null);
                      } catch (error) {
                        setSceneGenerationError(
                          error instanceof Error ? error.message : "Failed to load obstacle types preset."
                        );
                      }
                    })();
                  }}
                  onLoadObstacleTypesFromFile={(file) => {
                    void (async () => {
                      const text = await readTextFile(file);
                      setObstacleTypesText(text);
                      setSceneGenerationError(null);
                    })();
                  }}
                  onExportObstacleTypes={() =>
                    exportTextFile(obstacleTypesText, "static_obstacle_types.yaml", "text/yaml")
                  }
                />
              </div>
            ) : activeView === "sceneGeneration" ? (
              <div
                ref={simulationCenterRef}
                className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
                style={{
                  gridTemplateRows:
                    bottomPanelHeight !== null
                      ? `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px ${bottomPanelHeight}px`
                      : `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px 280px`,
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
                    <div className="toolbar-row scene-generation-toolbar">
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
                        {(() => {
                          const isBatch = sceneGenerationTab === "batch";
                          const sceneCount = isBatch ? selectedBatchPaths.length : 1;
                          const disabled = isBatch
                            ? !domainReadyForGeneration ||
                              isSceneGenerationBusy ||
                              selectedBatchPaths.length === 0
                            : !canGenerateScene || isSceneGenerationBusy;
                          return (
                            <button
                              className="primary-btn accent"
                              type="button"
                              disabled={disabled}
                              onClick={() => {
                                setSceneGenerationError(null);
                                if (isBatch) {
                                  void runBatchGeneration({
                                    selectedPaths: selectedBatchPaths,
                                    loadPresetText: loadTextFromPreset,
                                    enqueueSceneGeneration,
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
                              Generate Initial Scenes ({sceneCount})
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
                      </div>
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
                            isSceneGenerationBusy ||
                            !latestGeneratedScene?.valid ||
                            !latestGeneratedScene.evaluationData
                          }
                          onClick={loadForTrajectoryGeneration}
                        >
                          Load for Trajectory Generation
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
                    </div>
                    <p className="meta">
                      Visualized scenario:{" "}
                      {latestGeneratedScene
                        ? scenarioSourceName
                          ? `from file (${scenarioSourceName})`
                          : "generated scene"
                        : "none"}
                    </p>
                    <p className="meta">
                      Backend socket: <span className={`status-text ${streamStatus}`}>{streamStatus}</span>
                    </p>
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
                    <PlaybackControls
                      streamControls={streamControls}
                      colregsConstraintsContent={colregsConstraintsText}
                    />
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
                <TrajectoryMonitorSidebar />
              ) : (
                <SceneGenerationSidebar
                  functionalSpecText={functionalSpecText}
                  onFunctionalSpecTextChange={setFunctionalSpecText}
                  onLoadFunctionalSpecFromPreset={(path) => {
                    void (async () => {
                      try {
                        const text = await loadTextFromPreset(path);
                        setFunctionalSpecText(text);
                        setSceneGenerationError(null);
                      } catch (error) {
                        setSceneGenerationError(
                          error instanceof Error ? error.message : "Failed to load functional spec preset."
                        );
                      }
                    })();
                  }}
                  onLoadFunctionalSpecFromFile={(file) => {
                    void (async () => {
                      const text = await readTextFile(file);
                      setFunctionalSpecText(text);
                      setSceneGenerationError(null);
                    })();
                  }}
                  onExportFunctionalSpec={() =>
                    exportTextFile(functionalSpecText, "functional_scenario.problem", "text/plain")
                  }
                  isSceneGenerationBusy={isSceneGenerationBusy}
                  onVisualizeFromEvaluation={(evaluationData, scene) => {
                    setVisualizedScenario({ scene, evaluationData, valid: true });
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
      </div>
      {globalErrorMessage && (
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
        </footer>
      )}
    </div>
  );
}
