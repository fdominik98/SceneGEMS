import { describe, expect, it, vi } from "vitest";
import { handleResetPlayback } from "./resetPlayback";

describe("handleResetPlayback", () => {
  it("stops playback, then seeks to zero", () => {
    const setPlaying = vi.fn();
    const seek = vi.fn();

    handleResetPlayback(setPlaying, seek);

    expect(setPlaying).toHaveBeenCalledWith(false);
    expect(seek).toHaveBeenCalledWith(0);
    expect(setPlaying.mock.invocationCallOrder[0]).toBeLessThan(seek.mock.invocationCallOrder[0]);
  });
});
