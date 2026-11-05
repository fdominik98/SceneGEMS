import { describe, expect, it } from "vitest";
import { formatDuration, percent, plural, runDuration, splitClassId } from "./campaignFormat";

describe("campaign formatting", () => {
  it("formats durations coarsely", () => {
    expect(formatDuration(0)).toBe("0 s");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(60)).toBe("1 min");
    expect(formatDuration(725)).toBe("12 min 5 s");
    expect(formatDuration(3600)).toBe("1 h");
    expect(formatDuration(3 * 3600 + 20 * 60 + 40)).toBe("3 h 20 min");
    expect(formatDuration(2 * 86400 + 4 * 3600)).toBe("2 d 4 h");
    expect(formatDuration(-1)).toBe("none");
    expect(formatDuration(Number.NaN)).toBe("none");
  });

  it("measures a run from its start to its end, or to now while it goes on", () => {
    const now = Date.parse("2026-10-26T10:00:00+00:00");
    expect(runDuration(null, null, now)).toBe("not started");
    expect(runDuration("2026-10-26T09:00:00+00:00", null, now)).toBe("1 h");
    expect(runDuration("2026-10-26T09:00:00+00:00", "2026-10-26T09:10:30+00:00", now)).toBe("10 min 30 s");
    expect(runDuration("garbage", null, now)).toBe("none");
  });

  it("splits a class id into folder and name", () => {
    expect(splitClassId("3vessel_0obstacle_scenarios/fec5")).toEqual({ folder: "3vessel_0obstacle_scenarios", name: "fec5" });
    expect(splitClassId("plain")).toEqual({ folder: "", name: "plain" });
  });

  it("formats percent and plurals", () => {
    expect(percent(0.456)).toBe("46%");
    expect(plural(1, "class", "classes")).toBe("1 class");
    expect(plural(3, "class", "classes")).toBe("3 classes");
    expect(plural(2, "case")).toBe("2 cases");
  });
});
