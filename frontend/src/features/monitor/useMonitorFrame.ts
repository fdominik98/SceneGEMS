import type { TrajectoryStream } from "../../app/uiStore";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
  usePlaybackStore,
} from "../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../domain/simulation/types";

/** Frame for a specific trajectory stream (animation vs simulation playback buffer). */
export function useMonitorFrameForKind(panelKind: TrajectoryStream): {
  frame: SimulationFrame | null;
  panelKind: TrajectoryStream;
} {
  const playback = usePlaybackStore();
  if (panelKind === "animation") {
    return { frame: getCurrentFrame(playback), panelKind: "animation" };
  }
  return { frame: getCurrentSimulationFrame(playback), panelKind: "simulation" };
}
