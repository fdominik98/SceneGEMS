import { describe, expect, it } from "vitest";
import { connectionHints, liveSessionsOffNote } from "./connectionHints";

describe("connection hints", () => {
  it("points at the control node's broker service for the control node broker", () => {
    const hints = connectionHints(true, "", 1883, false);
    expect(hints.some((hint) => hint.includes("cluster-broker"))).toBe(true);
  });

  it("explains how the server reaches a broker on localhost", () => {
    const hints = connectionHints(false, "localhost", 1882, false);
    expect(hints[0]).toContain("port 1882 of the control node's machine");
    expect(hints.at(-1)).toContain("TLS is off");
  });

  it("names the TLS port of the public broker when TLS is on", () => {
    expect(connectionHints(false, "broker.waraps.org", 8883, true).at(-1)).toContain("8883");
  });

  it("says live sessions are off only when the control node reports them off", () => {
    expect(liveSessionsOffNote(true)).toBeNull();
    expect(liveSessionsOffNote(undefined)).toBeNull();
    expect(liveSessionsOffNote(false)).toContain("Live sessions are off on this control node");
  });
});
