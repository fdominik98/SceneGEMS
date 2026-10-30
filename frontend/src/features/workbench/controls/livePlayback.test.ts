import { describe, expect, it, vi } from "vitest";
import { activateLiveMode, getLatestSimulationTimestamp, watchClusterRun } from "./livePlayback";

describe("handleLivePlayback", () => {

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

  it("follows a paced cluster run live, and plays a free-running one from its start, waiting at its latest frame", () => {
    const paced = { followSimulationLive: vi.fn(), setPlaying: vi.fn(), setHoldAtLiveEdge: vi.fn() };
    watchClusterRun(true, paced);
    expect([paced.followSimulationLive.mock.calls.length, paced.setPlaying.mock.calls, paced.setHoldAtLiveEdge.mock.calls]).toEqual([1, [], [[false]]]);
    const free = { followSimulationLive: vi.fn(), setPlaying: vi.fn(), setHoldAtLiveEdge: vi.fn() };
    watchClusterRun(false, free);
    expect([free.followSimulationLive.mock.calls.length, free.setPlaying.mock.calls, free.setHoldAtLiveEdge.mock.calls]).toEqual([0, [[true]], [[true]]]);
  });
});
