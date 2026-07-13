import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { timestampAtOrBefore, framesAtOrBeforeCursor } from "./playbackFrameResolve";

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

describe("framesAtOrBeforeCursor", () => {
  const frames = [0, 2, 10].map((timestamp) => ({ ...sampleFrames[0], timestamp }));

  it("returns frames up to the latest at or before the cursor", () => {
    expect(framesAtOrBeforeCursor(frames, 0).map((f) => f.timestamp)).toEqual([0]);
    expect(framesAtOrBeforeCursor(frames, 1).map((f) => f.timestamp)).toEqual([0]);
    expect(framesAtOrBeforeCursor(frames, 2).map((f) => f.timestamp)).toEqual([0, 2]);
    expect(framesAtOrBeforeCursor(frames, 9).map((f) => f.timestamp)).toEqual([0, 2]);
    expect(framesAtOrBeforeCursor(frames, 10).map((f) => f.timestamp)).toEqual([0, 2, 10]);
  });
});
