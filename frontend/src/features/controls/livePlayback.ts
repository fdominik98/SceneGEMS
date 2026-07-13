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

export function handleLivePlayback({
  liveTimestamp,
  followSimulationLive,
}: {
  liveTimestamp: number | null;
  followSimulationLive: () => void;
}): void {
  if (liveTimestamp === null) {
    return;
  }
  activateLiveMode({ followSimulationLive });
}
