import { create } from "zustand";
import type { SimulationFrame } from "../simulation/types";
import { usePlaybackStore } from "./playbackStore";

export interface RecordedStream {
  stream: "preview" | "simulation";
  scenarioId: string | null;
  recordedAt: string;
  frames: SimulationFrame[];
}

interface RecordingState {
  isRecording: boolean;
  /** Scenario id captured when recording started; used to detect scenario switches. */
  recordingScenarioId: string | null;
  previewRecording: SimulationFrame[];
  simulationRecording: SimulationFrame[];
  startRecording: () => void;
  stopRecording: () => void;
  appendPreviewFrame: (frame: SimulationFrame) => void;
  appendSimulationFrame: (frame: SimulationFrame) => void;
  clearRecording: () => void;
  exportRecording: () => void;
  importRecordingForReplay: (json: string) => boolean;
}

function mergeFrame(existing: SimulationFrame[], frame: SimulationFrame): SimulationFrame[] {
  const idx = existing.findIndex((f) => f.timestamp === frame.timestamp);
  if (idx >= 0) {
    const next = [...existing];
    next[idx] = frame;
    return next;
  }
  return [...existing, frame].sort((a, b) => a.timestamp - b.timestamp);
}

export const useRecordingStore = create<RecordingState>((set, get) => ({
  isRecording: false,
  recordingScenarioId: null,
  previewRecording: [],
  simulationRecording: [],
  startRecording: () =>
    set({
      isRecording: true,
      recordingScenarioId: usePlaybackStore.getState().activeScenarioId,
      previewRecording: [],
      simulationRecording: [],
    }),
  stopRecording: () => set({ isRecording: false }),
  clearRecording: () =>
    set({
      previewRecording: [],
      simulationRecording: [],
      isRecording: false,
      recordingScenarioId: null,
    }),
  appendPreviewFrame: (frame) => {
    if (!get().isRecording) return;
    set((s) => ({ previewRecording: mergeFrame(s.previewRecording, frame) }));
  },
  appendSimulationFrame: (frame) => {
    if (!get().isRecording) return;
    set((s) => ({ simulationRecording: mergeFrame(s.simulationRecording, frame) }));
  },
  exportRecording: () => {
    const { previewRecording, simulationRecording, recordingScenarioId } = get();
    const payload = {
      exportedAt: new Date().toISOString(),
      scenarioId: recordingScenarioId,
      streams: [
        { stream: "preview", scenarioId: recordingScenarioId, frames: previewRecording },
        { stream: "simulation", scenarioId: recordingScenarioId, frames: simulationRecording },
      ],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `scenario_recording_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  importRecordingForReplay: (json) => {
    try {
      const data = JSON.parse(json) as {
        streams?: { stream: string; frames: SimulationFrame[] }[];
      };
      const preview = data.streams?.find((s) => s.stream === "preview")?.frames ?? [];
      const simulation = data.streams?.find((s) => s.stream === "simulation")?.frames ?? [];
      const playback = usePlaybackStore.getState();
      if (preview.length > 0) {
        playback.ingestFrames(preview);
      }
      if (simulation.length > 0) {
        playback.ingestSimulationFrames(simulation);
      }
      return preview.length > 0 || simulation.length > 0;
    } catch {
      return false;
    }
  },
}));

// Stop an active recording when the loaded scenario changes, so a single
// recording can never silently mix frames from two different scenarios.
usePlaybackStore.subscribe((state, prev) => {
  if (state.activeScenarioId === prev.activeScenarioId) {
    return;
  }
  const recording = useRecordingStore.getState();
  if (recording.isRecording && recording.recordingScenarioId !== state.activeScenarioId) {
    useRecordingStore.setState({ isRecording: false });
  }
});
