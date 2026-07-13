import { describe, expect, it, vi } from "vitest";
import {
  activateLiveMode,
  getLatestSimulationTimestamp,
  handleLivePlayback,
} from "./livePlayback";

describe("handleLivePlayback", () => {
  it("follows simulation live without starting playback", () => {
    const followSimulationLive = vi.fn();

    handleLivePlayback({
      liveTimestamp: 42,
      followSimulationLive,
    });

    expect(followSimulationLive).toHaveBeenCalledTimes(1);
  });

  it("does nothing when no simulation frame timestamp is available", () => {
    const followSimulationLive = vi.fn();

    handleLivePlayback({
      liveTimestamp: null,
      followSimulationLive,
    });

    expect(followSimulationLive).not.toHaveBeenCalled();
  });

  it("activates live follow via store action", () => {
    const followSimulationLive = vi.fn();

    activateLiveMode({ followSimulationLive });

    expect(followSimulationLive).toHaveBeenCalledTimes(1);
  });

  it("returns the latest buffered simulation timestamp", () => {
    expect(
      getLatestSimulationTimestamp([
        { timestamp: 5 },
        { timestamp: 8 },
        { timestamp: 13 },
      ])
    ).toBe(13);
  });

  it("returns null for an empty simulation frame list", () => {
    expect(getLatestSimulationTimestamp([])).toBeNull();
  });
});
