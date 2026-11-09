import type { TrajectoryStream } from "../../../app/uiStore";
import { useStore } from "zustand";
import { useShownPlaybackStore } from "../../../domain/playback/playbackContext";
import { getCurrentFrame, getCurrentSimulationFrame } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";

/** Frame for a specific trajectory stream (animation vs simulation playback buffer) of the shown page. */
export function useMonitorFrameForKind(panelKind: TrajectoryStream): {
  frame: SimulationFrame | null;
  panelKind: TrajectoryStream;
} {
  // Only the frame: the store changes every playback tick, the frame only when the play head reaches another one.
  const frame = useStore(useShownPlaybackStore(), (s) => (panelKind === "animation" ? getCurrentFrame(s) : getCurrentSimulationFrame(s)));
  return { frame, panelKind };
}
