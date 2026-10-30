interface ActivateLiveModeParams {
  followSimulationLive: () => void;
}

export function getLatestSimulationTimestamp(
  frames: Array<{ timestamp: number }>
): number | null {
  if (frames.length === 0) {
    return null;
  }
  return frames[frames.length - 1]!.timestamp;
}

/** Enables live follow on simulation trajectory chunks without starting playback. */
export function activateLiveMode({ followSimulationLive }: ActivateLiveModeParams): void {
  followSimulationLive();
}

interface WatchClusterRunParams extends ActivateLiveModeParams {
  setPlaying: (value: boolean) => void;
  setHoldAtLiveEdge: (value: boolean) => void;
}

/**
 * How the workbench shows a cluster run it starts. A run the watch speed paces arrives at that
 * speed, so the view follows its latest frame. A run that is not paced (SITL runs free) is played
 * from its start at the playback speed, waiting at the latest frame while more arrive.
 */
export function watchClusterRun(pacedByWatchSpeed: boolean, { followSimulationLive, setPlaying, setHoldAtLiveEdge }: WatchClusterRunParams): void {
  setHoldAtLiveEdge(!pacedByWatchSpeed);
  if (pacedByWatchSpeed) {
    activateLiveMode({ followSimulationLive });
  } else {
    setPlaying(true);
  }
}
