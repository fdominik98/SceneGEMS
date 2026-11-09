import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { timestampAtOrBefore } from "./playbackFrameResolve";

describe("timestampAtOrBefore", () => {
  const frames = [0, 2, 10].map((timestamp) => ({ ...sampleFrames[0], timestamp }));

  it("returns the latest frame at or before t", () => {
    expect(timestampAtOrBefore(frames, 0)).toBe(0);
    expect(timestampAtOrBefore(frames, 1)).toBe(0);
    expect(timestampAtOrBefore(frames, 2)).toBe(2);
    expect(timestampAtOrBefore(frames, 9)).toBe(2);
    expect(timestampAtOrBefore(frames, 10)).toBe(10);
  });
});
