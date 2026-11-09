import { describe, expect, it } from "vitest";
import { frameAt, threeVesselFrames, twoVesselFrames } from "../../encounter/fixtures/recordedFrames";
import type { SimulationFrame } from "../../../domain/simulation/types";
import {
  buildPairModels,
  encounterAbbreviation,
  encounterTagsByVessel,
  roleOf,
} from "./encounterPairs";
import { buildRuleTimeline } from "./ruleTimelineModel";
import { parseFrame } from "../../../domain/simulation/protocol";
import { RULE_16_ID, monitoredFrames } from "../../../test/fixtures/monitoredFrames";

describe("buildPairModels on the recorded two-vessel crossing", () => {
  const frames = twoVesselFrames();
  const timeline = buildRuleTimeline(frames);

  it("describes the crossing at 100 s from the monitor's data", () => {
    const [pair] = buildPairModels(frameAt(frames, 100), timeline);
    expect(pair!.relationId).toBe("0->1");
    expect(pair!.a.name).toBe("os");
    expect(pair!.b.name).toBe("ts1");
    expect(pair!.encounterLabel).toBe("Crossing from Port");
    expect(pair!.encounterActive).toBe(true);
    expect(pair!.a.role).toBe("give-way");
    expect(pair!.b.role).toBe("stand-on");
    expect(pair!.cpaSource).toBe("monitor");
    expect(pair!.dcpa).toBeCloseTo(0, 0);
    expect(pair!.tcpa).toBeCloseTo(350, 0);
    expect(pair!.since).toBe(0);
  });

  it("computes bearings from the states: ts1 on the starboard bow of os", () => {
    const [pair] = buildPairModels(frameAt(frames, 100), timeline);
    // Northbound: the course is 000 (the recorded heading is rounded to 1.571 rad).
    expect(Math.min(pair!.a.courseDeg!, 360 - pair!.a.courseDeg!)).toBeLessThan(0.1);
    expect(pair!.a.relativeBearingToOther!).toBeGreaterThan(22.5);
    expect(pair!.a.relativeBearingToOther!).toBeLessThan(67.5);
    expect(pair!.a.sectorOfOther).toBe("starboard bow");
    expect(pair!.b.sectorOfOther).toBe("port bow");
  });

  it("shows Rule 16 failed with its first failure time once it failed", () => {
    const before = buildPairModels(frameAt(frames, 60), timeline)[0]!;
    const r16Before = before.rules.find((r) => r.tag === "R16")!;
    expect(r16Before.result).toBe("UNKNOWN");
    expect(r16Before.firstFailure).toBeNull();
    expect(before.severity).not.toBe("fail");

    const after = buildPairModels(frameAt(frames, 200), timeline)[0]!;
    const r16 = after.rules.find((r) => r.tag === "R16")!;
    expect(r16.result).toBe("FAILED");
    expect(r16.firstFailure).toBe(70);
    expect(after.failedRuleCount).toBe(1);
    expect(after.severity).toBe("fail");
  });

  it("keeps the previous encounter for a pair whose encounter has ended", () => {
    const pair = buildPairModels(frameAt(frames, 500), timeline)[0]!;
    expect(pair.encounterActive).toBe(false);
    expect(pair.previousEncounterLabel).toBe("Crossing from Port");
    expect(pair.a.role).toBeNull();
    expect(pair.tcpa!).toBeLessThan(0);
  });

  it("falls back to the first failure in the frame without a timeline", () => {
    const pair = buildPairModels(frameAt(frames, 200), null)[0]!;
    expect(pair.rules.find((r) => r.tag === "R16")!.firstFailure).toBe(200);
  });

  it("computes range and CPA from the states when the frame has no metrics", () => {
    const frame: SimulationFrame = { ...frameAt(frames, 100), metrics: undefined };
    const pair = buildPairModels(frame, timeline)[0]!;
    expect(pair.cpaSource).toBe("computed");
    expect(pair.tcpa!).toBeCloseTo(350, 0);
    expect(pair.dcpa!).toBeLessThan(5);
    expect(pair.range!).toBeGreaterThan(3900);
  });

  it("returns nothing without a frame", () => {
    expect(buildPairModels(null, null)).toEqual([]);
  });
});

describe("buildPairModels on the recorded three-vessel run", () => {
  const frames = threeVesselFrames();
  const timeline = buildRuleTimeline(frames);

  it("gives one card per pair, own ship pairs first", () => {
    const pairs = buildPairModels(frameAt(frames, 100), timeline);
    expect(pairs.map((p) => `${p.a.name}-${p.b.name} ${p.situationType}`)).toEqual([
      "os-ts1 CROSSING_FROM_PORT",
      "os-ts2 HEAD_ON",
      "ts1-ts2 OTHER",
    ]);
  });

  it("makes both vessels of a head-on give way", () => {
    const headOn = buildPairModels(frameAt(frames, 100), timeline)[1]!;
    expect([headOn.a.role, headOn.b.role]).toEqual(["give-way", "give-way"]);
    expect(headOn.a.sectorOfOther).toBe("ahead");
    expect(headOn.rules.filter((r) => r.result === "FAILED").map((r) => r.subjectActorName)).toEqual([
      "os",
      "ts2",
    ]);
  });

  it("marks a pair in no encounter as such", () => {
    const other = buildPairModels(frameAt(frames, 100), timeline)[2]!;
    expect(other.encounterActive).toBe(false);
    expect(other.severity).toBe("none");
    expect([other.a.role, other.b.role]).toEqual([null, null]);
  });

  it("tags each vessel with its encounters for the canvas", () => {
    const tags = encounterTagsByVessel(frameAt(frames, 100));
    expect(tags["0"]!.map((t) => `${t.abbreviation} ${t.role} ${t.otherName}`).sort()).toEqual([
      "CR give-way ts1",
      "HO give-way ts2",
    ]);
    expect(tags["1"]!.map((t) => `${t.abbreviation} ${t.role}`)).toEqual(["CR stand-on"]);
  });
});

describe("encounter helpers", () => {
  it("abbreviates encounter types", () => {
    expect(encounterAbbreviation("HEAD_ON")).toBe("HO");
    expect(encounterAbbreviation("CROSSING_FROM_PORT")).toBe("CR");
    expect(encounterAbbreviation("OVERTAKING_TO_STARBOARD")).toBe("OT");
    expect(encounterAbbreviation("TWO_WAY_CROSSING_FROM_PORT")).toBe("TW");
    expect(encounterAbbreviation("OTHER")).toBe("");
  });

  it("has no role outside an encounter", () => {
    const frame = frameAt(threeVesselFrames(), 500);
    expect(roleOf(frame.situationContexts[0], "0")).toBeNull();
    expect(roleOf(undefined, "0")).toBeNull();
  });
});

describe("buildPairModels with the monitor's rule ids and first failures", () => {
  const frames = monitoredFrames(40, 12, true).map(parseFrame);

  it("keys the rules by rule id and takes the first failure from the frame", () => {
    // no timeline: only the frame at 30 s was received
    const [pair] = buildPairModels(frames[30]!, null);
    const r16 = pair!.rules.find((rule) => rule.key === RULE_16_ID)!;
    expect([r16.result, r16.firstFailure]).toEqual(["FAILED", 12]);
    expect(pair!.rules.find((rule) => rule.ruleNumber === "8")!.firstFailure).toBeNull();
  });

  it("trusts a rule that never failed over the timeline", () => {
    const timeline = buildRuleTimeline(frames);
    const [pair] = buildPairModels(frames[5]!, timeline);
    expect(pair!.rules.find((rule) => rule.key === RULE_16_ID)!.firstFailure).toBeNull();
  });

  it("falls back to the frame's time on an older frame without a timeline", () => {
    const [pair] = buildPairModels(parseFrame(monitoredFrames(40, 12)[30]!), null);
    expect(pair!.rules.find((rule) => rule.ruleNumber === "16")!.firstFailure).toBe(30);
  });
});
