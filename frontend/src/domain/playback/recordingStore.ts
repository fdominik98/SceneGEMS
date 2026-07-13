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
  previewRecording: [],
  simulationRecording: [],
  startRecording: () =>
    set({ isRecording: true, previewRecording: [], simulationRecording: [] }),
  stopRecording: () => set({ isRecording: false }),
  clearRecording: () =>
    set({ previewRecording: [], simulationRecording: [], isRecording: false }),
  appendPreviewFrame: (frame) => {
    if (!get().isRecording) return;
    set((s) => ({ previewRecording: mergeFrame(s.previewRecording, frame) }));
  },
  appendSimulationFrame: (frame) => {
    if (!get().isRecording) return;
    set((s) => ({ simulationRecording: mergeFrame(s.simulationRecording, frame) }));
  },
  exportRecording: () => {
    const { previewRecording, simulationRecording } = get();
    const payload = {
      exportedAt: new Date().toISOString(),
      streams: [
        { stream: "preview", frames: previewRecording },
        { stream: "simulation", frames: simulationRecording },
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
