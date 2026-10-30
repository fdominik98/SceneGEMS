import { beforeEach, describe, expect, it } from "vitest";
import { takeEntrySeed, useEntrySeedStore } from "./entrySeedStore";

describe("takeEntrySeed", () => {
  beforeEach(() => useEntrySeedStore.setState({ fixed: null, last: null }));

  it("draws a fresh seed per entry while none is fixed, and remembers the last one", () => {
    expect(takeEntrySeed(() => 0.5)).toBe(2 ** 30);
    expect(takeEntrySeed(() => 0)).toBe(0);
    expect(useEntrySeedStore.getState().last).toBe(0);
  });

  it("gives every entry the fixed seed", () => {
    useEntrySeedStore.getState().setFixed(42);
    expect([takeEntrySeed(() => 0.5), takeEntrySeed(() => 0.9)]).toEqual([42, 42]);
    expect(useEntrySeedStore.getState().last).toBe(42);
  });
});
