import { create } from "zustand";
import { persist } from "zustand/middleware";
import { defaultReferenceGeofence, type ReferenceGeofence } from "../features/connection/referenceGeofence";

export interface OverlayVisibility {
  dot: boolean;
  velocity: boolean;
  safetyRadius: boolean;
  trajectory: boolean;
  /** Per-encounter COLREGS safety domains reported by the monitor. */
  safetyDomain: boolean;
  /** Potential collision domains frozen at the start of each encounter. */
  staticAvoidanceDomain: boolean;
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

const defaultOverlays: OverlayVisibility = {
  dot: true,
  velocity: true,
  safetyRadius: true,
  trajectory: true,
  safetyDomain: true,
  staticAvoidanceDomain: true,
};

interface UiState {
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
  /** Shared geofence center/radius selected in WARA-PS panel. */
  referenceGeofence: ReferenceGeofence;
  setReferenceGeofence: (geofence: ReferenceGeofence) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
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
      version: 2,
      // v2: the monitor tab moved to the Connections page.
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as { controlPanelMode?: string };
        if (version < 2 && state.controlPanelMode === "monitor") {
          state.controlPanelMode = "animation";
        }
        return state as UiState;
      },
      // Only persist where the user has navigated (page tabs / scene view), not transient UI state.
      partialize: (state) => ({
        controlPanelMode: state.controlPanelMode,
        sceneViewMode: state.sceneViewMode,
        sceneGenerationTab: state.sceneGenerationTab,
        sceneGenerationPaneView: state.sceneGenerationPaneView,
        sceneGenerationLivePreview: state.sceneGenerationLivePreview,
      }),
    }
  )
);
