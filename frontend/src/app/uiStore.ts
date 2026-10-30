import { create } from "zustand";
import { persist } from "zustand/middleware";
import { defaultReferenceGeofence, type ReferenceGeofence } from "../features/workbench/connection/referenceGeofence";

export interface OverlayVisibility {
  dot: boolean;
  velocity: boolean;
  safetyRadius: boolean;
  trajectory: boolean;
  /** Per-encounter COLREGS safety domains reported by the monitor. */
  safetyDomain: boolean;
  /** Potential collision domains frozen at the start of each encounter. */
  staticAvoidanceDomain: boolean;
  /** Planner maneuvering corridor (give-way A-B-C-D). */
  maneuveringDomain: boolean;
}

/** Bottom control panel tab (preview animation playback or simulation playback). */
export type ControlPanelMode = "animation" | "simulation";

/** Which trajectory stream the right-hand monitor columns refer to (preview vs simulation). */
export type TrajectoryStream = "animation" | "simulation";

/** Right-hand monitoring panel view mode. */
export type MonitorPanelView = "runtime_data" | "overall_analysis";
export type SceneViewMode = "cartesian" | "nautical";
/** Scene generation panel mode: single editor-driven generation or batch over presets. */
export type SceneGenerationTab = "single" | "batch";
/** Scene generation right pane: the specification editor or the monitor preview of the displayed scene. */
export type SceneGenerationPaneView = "specification" | "monitor";
/** Top-level sections of the left pane. */
export type AppSection = "workbench" | "cluster" | "domain" | "capabilities" | "campaigns" | "history" | "results";
/** Views inside the workbench section (its sub-navigation). */
export type WorkbenchView =
  | "simulation"
  | "connections"
  | "sceneGeneration"
  | "trajectoryGeneration";

export const APP_SECTIONS: readonly AppSection[] = ["workbench", "cluster", "domain", "capabilities", "campaigns", "history", "results"];
export const WORKBENCH_VIEWS: readonly WorkbenchView[] = [
  "sceneGeneration",
  "trajectoryGeneration",
  "simulation",
  "connections",
];

/** The Connections view's id before v5, when the page was named after WARA-PS. */
export const LEGACY_CONNECTIONS_VIEW = "waraps";

/** The History section's id before v6, when the page was named Observe. */
export const LEGACY_OBSERVE_SECTION = "observe";

/** The workbench view of the domain configuration before v7, when it was the workbench's and not the cluster's. */
export const LEGACY_DOMAIN_CONFIG_VIEW = "domainConfig";

/** Where the workbench kept its view before v4 (`usePersistedState("active-view")`). */
export const LEGACY_ACTIVE_VIEW_KEY = "scenegems:active-view";

function isWorkbenchView(value: unknown): value is WorkbenchView {
  return typeof value === "string" && (WORKBENCH_VIEWS as readonly string[]).includes(value);
}

/**
 * Whether a workbench view shows its right pane: the scene page always (its specification),
 * the trajectory and simulation pages while the monitoring panel is not hidden, Connections never.
 */
export function rightPaneShown(view: WorkbenchView, rightPaneVisible: boolean): boolean {
  if (view === "sceneGeneration") {
    return true;
  }
  return (view === "trajectoryGeneration" || view === "simulation") && rightPaneVisible;
}

/** The view the workbench persisted under its old key, or null when there is none. */
export function readLegacyWorkbenchView(): WorkbenchView | null {
  try {
    const raw = globalThis.localStorage?.getItem(LEGACY_ACTIVE_VIEW_KEY);
    if (raw == null) {
      return null;
    }
    const value: unknown = JSON.parse(raw);
    return isWorkbenchView(value) ? value : value === LEGACY_CONNECTIONS_VIEW ? "connections" : null;
  } catch {
    return null;
  }
}

const defaultOverlays: OverlayVisibility = {
  dot: true,
  velocity: true,
  safetyRadius: true,
  trajectory: true,
  safetyDomain: true,
  staticAvoidanceDomain: true,
  maneuveringDomain: true,
};

interface UiState {
  /** Left pane section shown in the main area. */
  section: AppSection;
  setSection: (section: AppSection) => void;
  /** Workbench view; selecting one also shows the workbench section. */
  workbenchView: WorkbenchView;
  setWorkbenchView: (view: WorkbenchView) => void;
  controlPanelMode: ControlPanelMode;
  setControlPanelMode: (mode: ControlPanelMode) => void;
  /** Whether the entire right-hand monitoring panel is shown (vs fully hidden, occupying no space). */
  rightPaneVisible: boolean;
  setRightPaneVisible: (value: boolean) => void;
  /** Right sidebar: preview trajectory column visibility. */
  rightTrajectoryPreviewVisible: boolean;
  setRightTrajectoryPreviewVisible: (value: boolean) => void;
  /** Right sidebar: simulation trajectory column visibility. */
  rightTrajectorySimulationVisible: boolean;
  setRightTrajectorySimulationVisible: (value: boolean) => void;
  /** Share of the right sidebar width for the preview column when both columns are visible (0-100). */
  rightTrajectorySplitPercent: number;
  setRightTrajectorySplitPercent: (value: number) => void;
  /** Granular toggles for right-panel stream overlays (preview vs simulation). */
  previewOverlays: OverlayVisibility;
  simulationOverlays: OverlayVisibility;
  setPreviewOverlay: (key: keyof OverlayVisibility, value: boolean) => void;
  setSimulationOverlay: (key: keyof OverlayVisibility, value: boolean) => void;
  /** When true, all canvas layers for that stream are hidden regardless of overlay toggles. */
  hidePreviewStream: boolean;
  hideSimulationStream: boolean;
  setHidePreviewStream: (value: boolean) => void;
  setHideSimulationStream: (value: boolean) => void;
  /**
   * Open/closed state for monitor `details` sections. Missing keys are closed
   * (the default). Keys are stable ids such as `monitor:animation:frame-data`.
   */
  monitorSectionOpen: Record<string, boolean>;
  setMonitorSectionOpen: (key: string, open: boolean) => void;
  /** Right sidebar monitoring view: live frame data or metrics analysis. */
  monitorPanelView: MonitorPanelView;
  setMonitorPanelView: (view: MonitorPanelView) => void;
  /** Selected COLREGS relation for metrics charts. */
  selectedMetricsRelationId: string | null;
  setSelectedMetricsRelationId: (id: string | null) => void;
  /** Main scene view mode: legacy cartesian canvas or nautical GPS map. */
  sceneViewMode: SceneViewMode;
  setSceneViewMode: (mode: SceneViewMode) => void;
  /** Scene generation panel tab (single vs batch). */
  sceneGenerationTab: SceneGenerationTab;
  setSceneGenerationTab: (tab: SceneGenerationTab) => void;
  sceneGenerationPaneView: SceneGenerationPaneView;
  setSceneGenerationPaneView: (view: SceneGenerationPaneView) => void;
  /** When true, every incoming generated scene is shown; when false, only final valid (single) or user-selected (batch) scenes. */
  sceneGenerationLivePreview: boolean;
  setSceneGenerationLivePreview: (value: boolean) => void;
  /** Shared geofence center and radius selected on the Connections page. */
  referenceGeofence: ReferenceGeofence;
  setReferenceGeofence: (geofence: ReferenceGeofence) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
  section: "workbench",
  setSection: (section) => set({ section }),
  workbenchView: readLegacyWorkbenchView() ?? "simulation",
  setWorkbenchView: (workbenchView) => set({ workbenchView }),
  controlPanelMode: "animation",
  setControlPanelMode: (mode) => set({ controlPanelMode: mode }),
  rightPaneVisible: true,
  setRightPaneVisible: (value) => set({ rightPaneVisible: value }),
  rightTrajectoryPreviewVisible: true,
  setRightTrajectoryPreviewVisible: (value) => set({ rightTrajectoryPreviewVisible: value }),
  rightTrajectorySimulationVisible: true,
  setRightTrajectorySimulationVisible: (value) => set({ rightTrajectorySimulationVisible: value }),
  rightTrajectorySplitPercent: 50,
  setRightTrajectorySplitPercent: (value) =>
    set({ rightTrajectorySplitPercent: Math.min(85, Math.max(15, value)) }),
  previewOverlays: { ...defaultOverlays },
  simulationOverlays: { ...defaultOverlays },
  setPreviewOverlay: (key, value) =>
    set((state) => ({
      previewOverlays: { ...state.previewOverlays, [key]: value },
    })),
  setSimulationOverlay: (key, value) =>
    set((state) => ({
      simulationOverlays: { ...state.simulationOverlays, [key]: value },
    })),
  hidePreviewStream: false,
  hideSimulationStream: false,
  setHidePreviewStream: (value) => set({ hidePreviewStream: value }),
  setHideSimulationStream: (value) => set({ hideSimulationStream: value }),
  monitorSectionOpen: {},
  setMonitorSectionOpen: (key, open) =>
    set((state) => {
      if (state.monitorSectionOpen[key] === open) {
        return state;
      }
      return { monitorSectionOpen: { ...state.monitorSectionOpen, [key]: open } };
    }),
  monitorPanelView: "runtime_data",
  setMonitorPanelView: (view) => set({ monitorPanelView: view }),
  selectedMetricsRelationId: null,
  setSelectedMetricsRelationId: (id) => set({ selectedMetricsRelationId: id }),
  sceneViewMode: "cartesian",
  setSceneViewMode: (mode) => set({ sceneViewMode: mode }),
  sceneGenerationTab: "single",
  setSceneGenerationTab: (tab) => set({ sceneGenerationTab: tab }),
  sceneGenerationPaneView: "specification",
  setSceneGenerationPaneView: (view) => set({ sceneGenerationPaneView: view }),
  sceneGenerationLivePreview: true,
  setSceneGenerationLivePreview: (value) => set({ sceneGenerationLivePreview: value }),
  referenceGeofence: defaultReferenceGeofence,
  setReferenceGeofence: (referenceGeofence) => set({ referenceGeofence }),
    }),
    {
      name: "scenegems:ui",
      version: 7,
      // v2: the monitor tab moved to the Connections page.
      // v3: persist monitor section collapse and preview/simulation column visibility.
      // v4: sections; the workbench view moved here from its own "active-view" key.
      // v5: the Connections view's id is "connections" (was "waraps").
      // v6: the section "observe" is "history" (Campaign History).
      // v7: the domain configuration is the cluster's section "domain", no longer the workbench view "domainConfig".
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as {
          controlPanelMode?: string;
          section?: AppSection | typeof LEGACY_OBSERVE_SECTION;
          workbenchView?: WorkbenchView | typeof LEGACY_CONNECTIONS_VIEW | typeof LEGACY_DOMAIN_CONFIG_VIEW;
        };
        if (version < 2 && state.controlPanelMode === "monitor") {
          state.controlPanelMode = "animation";
        }
        if (version < 4) {
          state.section = "workbench";
          state.workbenchView = readLegacyWorkbenchView() ?? "simulation";
        }
        if (version < 5 && state.workbenchView === LEGACY_CONNECTIONS_VIEW) {
          state.workbenchView = "connections";
        }
        if (version < 6 && state.section === LEGACY_OBSERVE_SECTION) {
          state.section = "history";
        }
        if (version < 7 && state.workbenchView === LEGACY_DOMAIN_CONFIG_VIEW) {
          state.workbenchView = "sceneGeneration";
          if (state.section === "workbench") {
            state.section = "domain";
          }
        }
        return state as UiState;
      },
      partialize: (state) => ({
        section: state.section,
        workbenchView: state.workbenchView,
        controlPanelMode: state.controlPanelMode,
        sceneViewMode: state.sceneViewMode,
        sceneGenerationTab: state.sceneGenerationTab,
        sceneGenerationPaneView: state.sceneGenerationPaneView,
        sceneGenerationLivePreview: state.sceneGenerationLivePreview,
        rightTrajectoryPreviewVisible: state.rightTrajectoryPreviewVisible,
        rightTrajectorySimulationVisible: state.rightTrajectorySimulationVisible,
        hidePreviewStream: state.hidePreviewStream,
        hideSimulationStream: state.hideSimulationStream,
        monitorSectionOpen: state.monitorSectionOpen,
      }),
    }
  )
);
