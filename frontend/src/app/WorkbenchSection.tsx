import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { saveBlob } from "../components/saveBlob";
import { usePlaybackTicker } from "../domain/playback/usePlaybackTicker";
import { usePlaybackStore, useScenePlaybackStore, useTrajectoryPlaybackStore } from "../domain/playback/playbackStore";
import { PlaybackStoreContext } from "../domain/playback/playbackContext";
import { useWorkerNodesStore } from "../domain/cluster/workerNodesStore";
import { getClassContent } from "../domain/cluster/presetsApi";
import { useCatalogClasses, useOperatorClient } from "../features/campaigns/useCampaignData";
import { useClusterDomain } from "../features/domain/useClusterDomain";
import { sceneInputSpecification } from "../features/workbench/pages/inputSpecification";
import { useEditorLoads, type EditorLoad } from "../features/workbench/controls/useEditorLoads";
import { sceneOfScenePage, setTrajectoryInput } from "../features/workbench/pages/pageHandoff";
import { useScenePageStore } from "../features/workbench/pages/pageStore";
import { useLoadedRefresh, useTargetConsumer } from "../features/workbench/pages/useWorkbenchTargets";
import type { WorkbenchPage, WorkbenchTarget } from "../features/workbench/pages/workbenchTarget";
import { rightPaneShown, useUiStore, type WorkbenchView } from "./uiStore";
import { usePersistedState } from "./usePersistedState";
import {
  buildConnectMessage,
  connectionFormIsValid,
  useConnectionStore,
} from "../features/workbench/connection/connectionStore";
import { useSimulationWorkflow } from "../domain/simulation/useSimulationWorkflow";
import type { ClientToServerMessage } from "../domain/simulation/wireTypes";
import { SimulationRunPanel } from "../features/workbench/controls/SimulationRunPanel";
import { SceneGenerationControls } from "../features/workbench/controls/SceneGenerationControls";
import { SceneGenerationSidebar } from "../features/workbench/controls/SceneGenerationSidebar";
import { SceneMonitorPreview } from "../features/workbench/controls/SceneMonitorPreview";
import { runBatchGeneration } from "../features/workbench/controls/runBatchGeneration";
import { catalogText } from "../features/workbench/controls/catalogTexts";
import { placeOfInput } from "../features/workbench/controls/sceneSelection";
import { TrajectoryGenerationControls } from "../features/workbench/controls/TrajectoryGenerationControls";
import { TrajectoryMonitorSidebar } from "../features/workbench/controls/TrajectoryMonitorSidebar";
import { MqttBrokerPanel } from "../features/workbench/connection/MqttBrokerPanel";
import { buildInitializeMonitorMessage, canInitializeMonitor } from "../features/workbench/controls/monitorConfig";
import { DESIGN_SPACE_EXPLORATION_JOB, SCENE_GENERATION_JOB } from "../features/workbench/cluster/workbenchJobs";
import { DesignSpaceExplorationControls } from "../features/workbench/designSpace/DesignSpaceExplorationControls";
import { DesignSpaceSidebar } from "../features/workbench/designSpace/DesignSpaceSidebar";
import { focusDesignSpaceEditor } from "../features/workbench/designSpace/explorationModel";
import { ExploredFecList } from "../features/workbench/designSpace/ExploredFecList";
import { downloadExplorationZip } from "../features/workbench/designSpace/explorationExport";
import { explorationInputOfEntry } from "../features/workbench/designSpace/explorationInputOfEntry";
import { useExplorationInputStore } from "../features/workbench/designSpace/explorationInputStore";
import { handoffFec, useExplorationStore } from "../features/workbench/designSpace/explorationStore";
import { allFecTexts, fecText } from "../features/workbench/designSpace/fecTexts";
import { sendToScenePage, useSceneSpecificationHandoff } from "../features/workbench/pages/sceneSpecificationHandoff";
import { useExplorationPageStore } from "../features/workbench/pages/pageStore";
import { SceneCanvas } from "../features/workbench/scene/SceneCanvas";
import { WorkbenchEncounterStrip } from "../features/workbench/monitor/WorkbenchEncounterPanels";
import { sceneSelectionMode, useBatchGenerationStore } from "../domain/sceneGeneration/batchGenerationStore";
import {
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "../domain/sceneGeneration/parseEvaluationDataFile";
import { resolveGlobalErrorMessage } from "./globalErrorMessage";

interface WorkbenchSectionProps {
  /** Whether the workbench is the shown section. It stays mounted while hidden, so its socket and state survive. */
  active: boolean;
  /** Where the workbench's error bar is rendered (below the app body), or null before it exists. */
  errorSlot: HTMLElement | null;
}

/**
 * The workbench section: scene and trajectory generation, simulation and connections over the
 * workbench gateway socket of the active cluster's control-node-api. Its view is the `workbenchView` of `uiStore`. The
 * domain configuration is the active cluster's (the Domain Configuration section edits it), and
 * the functional scenarios to start from are the control node's catalog.
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
  const errorMessage = usePlaybackStore((s) => s.errorMessage);
  const setError = usePlaybackStore((s) => s.setError);
  const activeSceneGenerationRequestId = useScenePlaybackStore((s) => s.activeSceneGenerationRequestId);
  const batchGenerationRunning = useBatchGenerationStore((s) => s.running);
  // The catalog FECs selected on the scene page: none runs the editor's text, one a single scene of it, several a batch.
  const selectedBatchClassIds = useBatchGenerationStore((s) => s.selectedClassIds);
  const sceneSelection = sceneSelectionMode(selectedBatchClassIds.length);
  // The one selected FEC's text while it is read for its run.
  const [singleFecLoading, setSingleFecLoading] = useState<string | null>(null);
  const sceneGenerationLivePreview = useUiStore((s) => s.sceneGenerationLivePreview);
  const setSceneGenerationLivePreview = useUiStore((s) => s.setSceneGenerationLivePreview);
  const sceneGenerationPaneView = useUiStore((s) => s.sceneGenerationPaneView);
  const setSceneGenerationPaneView = useUiStore((s) => s.setSceneGenerationPaneView);
  const isSceneGenerationBusy =
    activeSceneGenerationRequestId !== null || batchGenerationRunning || singleFecLoading !== null;
  const latestGeneratedScene = useScenePlaybackStore((s) => s.latestGeneratedScene);
  const explorationStatus = useExplorationPageStore((s) => s.status);
  const explorationRunning = useExplorationStore((s) => s.running !== null);
  const isExplorationBusy = explorationRunning || explorationStatus === "running" || explorationStatus === "following";
  const exploredFecCount = useExplorationStore((s) => s.fecs.length);
  const exploredHandoffId = useExplorationStore((s) => handoffFec(s)?.fecId ?? null);
  const [explorationExporting, setExplorationExporting] = useState(false);

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
  // The cluster's domain configuration, global for the cluster and kept on the control node.
  const clusterDomain = useClusterDomain();
  const colregsConstraintsText = clusterDomain.data?.colregs_constants ?? "";
  const vesselTypesText = clusterDomain.data?.vessel_types ?? "";
  const obstacleTypesText = clusterDomain.data?.obstacle_types ?? "";
  const operatorClient = useOperatorClient();
  // Which labels are catalog FECs, so an opened scene of one selects it rather than filling the editor.
  const catalogClasses = useCatalogClasses();
  const catalogIdsRef = useRef<ReadonlySet<string> | null>(null);
  useEffect(() => {
    catalogIdsRef.current = catalogClasses.data === undefined ? null : new Set(catalogClasses.data.items.map((entry) => entry.fec_id));
  }, [catalogClasses.data]);
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
  const mainLayoutRef = useRef<HTMLElement | null>(null);
  const simulationCenterRef = useRef<HTMLDivElement | null>(null);
  const previousViewRef = useRef<WorkbenchView>("simulation");

  /** A functional scenario of the control node's catalog, by class id. */
  const loadScenarioText = useCallback(
    async (classId: string): Promise<string> => {
      if (operatorClient === null) {
        throw new Error("Select a cluster first: the functional scenarios come from its control node.");
      }
      return getClassContent(operatorClient, classId);
    },
    [operatorClient]
  );

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

  // Auto-connect to the configured MQTT broker (the control node's by default) once the server
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

  // After a reload the simulation page has its input's name but not its trajectories: they load
  // again once the gateway is connected (the live session needs it) and the domain configuration
  // and the machines are known (the cluster's monitor judges the preview). Once per page load.
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const workerNodesKnown = useWorkerNodesStore((s) => s.loaded || s.unreachable);
  const domainKnown = clusterDomain.data !== undefined || clusterDomain.isError;
  const inputRestoreTriedRef = useRef(false);
  useEffect(() => {
    if (inputRestoreTriedRef.current || streamStatus !== "connected" || !workerNodesKnown || !domainKnown) {
      return;
    }
    inputRestoreTriedRef.current = true;
    void streamControlsRef.current.restoreSimulationInput(colregsTextRef.current);
  }, [domainKnown, workerNodesKnown, streamStatus]);

  // Only the latest load into the editor counts; while it runs the scenario list shows the pick and generating
  // waits, so a generation never pairs the old text with the new name (useEditorLoads.ts).
  // A text put into the editor from outside (a file, a hand-off, a loaded scene's scenario) shows the editor: the selection is cleared.
  const applyEditorLoad = useCallback(
    (loaded: EditorLoad) => {
      setFunctionalSpecText(loaded.text);
      setFunctionalSpecLabel(loaded.label);
      setSceneGenerationError(null);
      useBatchGenerationStore.getState().clearSelectedClassIds();
    },
    [setFunctionalSpecLabel, setFunctionalSpecText]
  );
  const { pending: pendingLoad, load: loadIntoEditor, cancel: cancelEditorLoads } = useEditorLoads(applyEditorLoad, setSceneGenerationError);

  // A scene loaded on the scene page brings its functional scenario along, so it can be generated again or changed: a catalog
  // FEC is selected in the list, any other scenario goes into the editor (sceneSelection.placeOfInput).
  const loadInputSpecification = useCallback(
    (target: WorkbenchTarget) => {
      if (target.page !== "sceneGeneration" || operatorClient === null) {
        return;
      }
      loadIntoEditor(
        null,
        async () => {
          const spec = await sceneInputSpecification(operatorClient, target);
          if (spec === null) {
            return null;
          }
          const place = placeOfInput(spec, catalogIdsRef.current);
          if (place.kind === "select") {
            useBatchGenerationStore.getState().setSelectedClassIds([place.classId]);
            return null;
          }
          return spec;
        },
        "The scene's functional scenario could not be loaded"
      );
    },
    [loadIntoEditor, operatorClient]
  );

  // A FEC sent to the scene page (from the exploration page or Campaign History) loads into its editor.
  const pendingSceneSpecification = useSceneSpecificationHandoff((s) => s.pending);
  useEffect(() => {
    if (pendingSceneSpecification === null) {
      return;
    }
    const load = useSceneSpecificationHandoff.getState().take();
    if (load !== null) {
      loadIntoEditor(load.label, async () => ({ label: load.label, text: await load.text() }), "The FEC could not be loaded");
    }
  }, [loadIntoEditor, pendingSceneSpecification]);

  /** The FEC the exploration page has selected (or its first), into the scene page's editor. */
  const sendExploredFecToScenePage = useCallback(() => {
    const fec = handoffFec(useExplorationStore.getState());
    if (fec === null || operatorClient === null) {
      return;
    }
    sendToScenePage({ label: fec.fecId, text: () => fecText(operatorClient, fec) });
  }, [operatorClient]);

  // An exploration opened from Campaign History brings its specification and scope, so it can run again or change.
  const loadExplorationInput = useCallback(
    (target: WorkbenchTarget) => {
      if (target.page !== "designSpaceExploration" || operatorClient === null) {
        return;
      }
      void explorationInputOfEntry(operatorClient, target.campaignId)
        .then((section) => {
          if (section === null || section.specification.trim().length === 0) {
            return;
          }
          const input = useExplorationInputStore.getState();
          input.loadSpecification(section.specification, `the specification of entry ${target.campaignId.split("-")[0]}`);
          input.setScope(section.scope);
          if (section.max_fecs !== undefined) {
            input.setMaxFecs(section.max_fecs);
          }
          if (section.timeout_s !== undefined) {
            input.setTimeoutSeconds(section.timeout_s);
          }
        })
        .catch(() => undefined);
    },
    [operatorClient]
  );

  // Outputs other sections open here (`openInWorkbench`), and the pages' loaded entries after a reload.
  const openTarget = useCallback(
    (target: WorkbenchTarget, options: { keepInput?: boolean } = {}) => {
      if (target.page === "simulation") {
        usePlaybackStore.getState().requestAutoFit();
      }
      loadExplorationInput(target);
      // A live entry's scenario is known before its scene is: it loads too. A batch row's scene keeps the selection of the batch.
      if (!options.keepInput) {
        loadInputSpecification(target);
      }
      void streamControlsRef.current.openTarget(target, colregsTextRef.current);
    },
    [loadExplorationInput, loadInputSpecification]
  );
  const refreshLoaded = useCallback((target: WorkbenchTarget) => {
    void streamControlsRef.current.refreshLoaded(target, colregsTextRef.current);
  }, []);
  const activePage: WorkbenchPage | null =
    activeView === "designSpaceExploration" || activeView === "sceneGeneration" || activeView === "trajectoryGeneration" || activeView === "simulation" ? activeView : null;
  // The pages with a wide specification pane of their own width.
  const specificationPage = activeView === "sceneGeneration" || activeView === "designSpaceExploration";
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
      activeView === "sceneGeneration" || activeView === "designSpaceExploration"
        ? Math.max(RIGHT_PANE_MAX_WIDTH, maxByCenter)
        : Math.min(maxByCenter, maxByRatio);
    return Math.min(maxWidth, Math.max(RIGHT_PANE_MIN_WIDTH, widthFromRight));
  }, [activeView]);

  const onRightPaneResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsResizingRightPane(true);
      const applyWidth =
        activeView === "sceneGeneration" || activeView === "designSpaceExploration" ? setSceneGenPaneWidth : setRightPaneWidth;
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

  // Every page's panel takes the height it needs, at most half the page, and the canvas the rest, until the
  // resizer sets a height.
  const bottomPanelGridRows =
    bottomPanelHeight !== null
      ? `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px ${bottomPanelHeight}px`
      : `minmax(0, 1fr) ${BOTTOM_PANEL_RESIZER_HEIGHT}px fit-content(50%)`;

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
  const explorationResources = streamControls.clusterResources(DESIGN_SPACE_EXPLORATION_JOB);

  const showRightPane = rightPaneShown(activeView, rightPaneVisible);

  const simulationRightPaneGridColumns =
    rightPaneWidth !== null
      ? `minmax(0, 1fr) ${RIGHT_PANE_RESIZER_WIDTH}px ${rightPaneWidth}px`
      : `minmax(0, ${RIGHT_PANE_DEFAULT_CENTER_FRACTION}fr) ${RIGHT_PANE_RESIZER_WIDTH}px minmax(0, ${RIGHT_PANE_DEFAULT_RIGHT_FRACTION}fr)`;

  const mainLayoutGridColumns = showRightPane
    ? specificationPage
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
    async (specText: string, label: string) => {
      if (!domainReadyForGeneration) {
        return { ok: false, message: domainProblem };
      }
      clearVisualizedScenario();
      setLoadedScenarioFileContent(null);
      const requestId = crypto.randomUUID();
      const outcome = await streamControls.generateScene(requestId, {
        label,
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

  const exportTextFile = useCallback((content: string, fileName: string, mimeType: string) => {
    saveBlob(new Blob([content], { type: mimeType }), fileName);
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
          ) : activeView === "designSpaceExploration" ? (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{ gridTemplateRows: bottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                <ExploredFecList client={operatorClient} />
              </div>
              <div
                className="bottom-pane-resizer"
                onPointerDown={onBottomPaneResizeStart}
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize bottom design space exploration panel"
              />
              <footer className="bottom-toolbar bottom-toolbar-compact bottom-toolbar-single">
                <div className="bottom-slot bottom-slot-controls">
                  <DesignSpaceExplorationControls
                    resources={explorationResources}
                    busy={isExplorationBusy}
                    onExplore={() => {
                      const input = useExplorationInputStore.getState();
                      streamControls.exploreDesignSpace({
                        specification: input.specification,
                        label: input.specificationLabel ?? "written specification",
                        scope: input.scope,
                        maxFecs: input.maxFecs,
                        timeoutSeconds: input.timeoutSeconds,
                      });
                    }}
                    onStop={() => streamControls.stopDesignSpaceExploration()}
                    onShowSpecification={focusDesignSpaceEditor}
                    exporting={explorationExporting}
                    onExport={() => {
                      const campaignId = useExplorationStore.getState().campaignId;
                      if (operatorClient === null || campaignId === null) {
                        return;
                      }
                      setExplorationExporting(true);
                      void allFecTexts(operatorClient)
                        .then((entries) => downloadExplorationZip(entries, campaignId))
                        .catch((error: unknown) => setSceneGenerationError(`The FECs could not be exported: ${error instanceof Error ? error.message : String(error)}`))
                        .finally(() => setExplorationExporting(false));
                    }}
                    onNext={sendExploredFecToScenePage}
                  />
                </div>
              </footer>
            </div>
          ) : activeView === "sceneGeneration" ? (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{ gridTemplateRows: bottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                {activeSceneGenerationRequestId && (
                  <LoadingSpinner label="Generating scene…" />
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
                  <SceneGenerationControls
                    resources={sceneGenerationResources}
                    busy={isSceneGenerationBusy}
                    selectedFecs={selectedBatchClassIds}
                    scenarioLabel={functionalSpecLabel}
                    hasScenario={functionalSpecText.trim().length > 0}
                    loadingLabel={singleFecLoading ?? (pendingLoad !== null ? (pendingLoad.label ?? "the scene's scenario") : null)}
                    domainProblem={domainReadyForGeneration ? null : domainProblem}
                    specificationHidden={sceneGenerationPaneView === "monitor"}
                    onShowSpecification={() => setSceneGenerationPaneView("specification")}
                    onGenerate={() => {
                      setSceneGenerationError(null);
                      if (sceneSelection === "batch") {
                        void runBatchGeneration({
                          selectedClassIds: selectedBatchClassIds,
                          loadScenarioText,
                          generateBatch,
                          sceneGenerationTimeoutSeconds,
                          isAborted: () => !useBatchGenerationStore.getState().running,
                        });
                        return;
                      }
                      void (async () => {
                        // One selected FEC runs as a single scene under its id; none runs the editor's text.
                        let specText = functionalSpecText;
                        let label = functionalSpecLabel ?? "functional scenario";
                        if (sceneSelection === "single") {
                          const classId = selectedBatchClassIds[0];
                          setSingleFecLoading(classId);
                          try {
                            specText = await catalogText(loadScenarioText, classId);
                            label = classId;
                          } catch (error) {
                            setSceneGenerationError(`The FEC ${classId} could not be read: ${error instanceof Error ? error.message : String(error)}`);
                            return;
                          } finally {
                            setSingleFecLoading(null);
                          }
                        }
                        const outcome = await runSceneGeneration(specText, label);
                        if (!outcome.ok && !outcome.superseded) {
                          setSceneGenerationError(outcome.message ?? "Scene generation failed.");
                        } else if (outcome.ok) {
                          setScenarioSourceName(null);
                        }
                      })();
                    }}
                    onStop={() => {
                      streamControls.stopSceneGeneration();
                      setSceneGenerationError("Scene generation stopped.");
                    }}
                    timeoutSeconds={sceneGenerationTimeoutSeconds}
                    onTimeoutSecondsChange={setSceneGenerationTimeoutSeconds}
                    enforceLowTcpa={enforceLowTcpa}
                    onEnforceLowTcpaChange={setEnforceLowTcpa}
                    livePreview={sceneGenerationLivePreview}
                    onLivePreviewChange={setSceneGenerationLivePreview}
                    scene={latestGeneratedScene}
                    sceneFileName={scenarioSourceName}
                    onOpenFile={(file) => void handleScenarioFileSelected(file)}
                    onExport={() => {
                      if (!latestGeneratedScene?.valid || !latestGeneratedScene.evaluationData) {
                        return;
                      }
                      exportTextFile(
                        loadedScenarioFileContent ?? formatScenarioJsonForExport(latestGeneratedScene.evaluationData, latestGeneratedScene.scene),
                        scenarioSourceName ?? "generated_scene.json",
                        "application/json"
                      );
                    }}
                    onNext={loadForTrajectoryGeneration}
                    explorationFec={exploredFecCount > 0 ? exploredHandoffId : null}
                    onTakeExploration={sendExploredFecToScenePage}
                  />
                </div>
              </footer>
            </div>
          ) : activeView === "trajectoryGeneration" ? (
            <div
              ref={simulationCenterRef}
              className={`simulation-center-layout${isResizingBottomPanel ? " is-resizing-bottom" : ""}`}
              style={{ gridTemplateRows: bottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                <div className="scene-host">
                  <SceneCanvas emptyMessage="Take an input scene below to see it here." />
                </div>
                <WorkbenchEncounterStrip />
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
              style={{ gridTemplateRows: bottomPanelGridRows }}
            >
              <div className="simulation-center-stage">
                <div className="scene-host">
                  <SceneCanvas emptyMessage="Take input trajectories below to see the encounter." />
                </div>
                <WorkbenchEncounterStrip />
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

        {showRightPane && (
          <>
            <div
              className="right-pane-resizer"
              onPointerDown={onRightPaneResizeStart}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize right panel"
            />
            {activeView === "designSpaceExploration" ? (
              <DesignSpaceSidebar disabled={isExplorationBusy} />
            ) : activeView === "simulation" || activeView === "trajectoryGeneration" ? (
              // One panel per page: its stream choice starts from that page's frames.
              <TrajectoryMonitorSidebar key={activeView} previewOnly={activeView === "trajectoryGeneration"} />
            ) : sceneGenerationPaneView === "monitor" ? (
              <SceneMonitorPreview />
            ) : (
              <SceneGenerationSidebar
                functionalSpecText={functionalSpecText}
                functionalSpecLabel={pendingLoad?.label ?? functionalSpecLabel}
                onFunctionalSpecTextChange={(text) => {
                  // Typing wins over a load still running
                  cancelEditorLoads();
                  setFunctionalSpecText(text);
                  setFunctionalSpecLabel((label) => (label === null || label.endsWith(" (edited)") ? label : `${label} (edited)`));
                }}
                onEditCopy={(label, text) => {
                  cancelEditorLoads();
                  setFunctionalSpecText(text);
                  setFunctionalSpecLabel(label);
                  setSceneGenerationError(null);
                  useBatchGenerationStore.getState().clearSelectedClassIds();
                }}
                loadScenarioText={loadScenarioText}
                onLoadFunctionalSpecFromFile={(file) =>
                  loadIntoEditor(file.name, async () => ({ label: file.name, text: await readTextFile(file) }), "The file could not be read")
                }
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
                    openTarget(target, { keepInput: true });
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
