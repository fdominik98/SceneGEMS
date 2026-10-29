import { describe, expect, it } from "vitest";
import { thumbGeometry } from "./overlayScrollbars";

describe("thumbGeometry", () => {
  it("has no thumb when nothing overflows", () => {
    expect(thumbGeometry(200, 200, 0, 196)).toBeNull();
    expect(thumbGeometry(200, 200.5, 0, 196)).toBeNull();
  });

  it("has no thumb when there is no room for a track", () => {
    expect(thumbGeometry(200, 800, 0, 0)).toBeNull();
  });

  it("sizes the thumb to the share of the content in view", () => {
    expect(thumbGeometry(200, 800, 0, 196)).toEqual({ offset: 0, length: 49 });
  });

  it("keeps a long list's thumb at the minimum length", () => {
    expect(thumbGeometry(200, 100000, 0, 196, 28)?.length).toBe(28);
  });

  it("moves the thumb with the scroll position, from the start to the end of the track", () => {
    expect(thumbGeometry(200, 800, 300, 196)?.offset).toBeCloseTo(73.5);
    expect(thumbGeometry(200, 800, 600, 196)?.offset).toBeCloseTo(147);
  });

  it("keeps the thumb on the track while the content overscrolls", () => {
    expect(thumbGeometry(200, 800, 650, 196)?.offset).toBeCloseTo(147);
    expect(thumbGeometry(200, 800, -40, 196)?.offset).toBe(0);
  });
});
