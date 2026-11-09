import { describe, expect, it } from "vitest";
import { threeVesselFrames, twoVesselFrames } from "../../encounter/fixtures/recordedFrames";
import type { SimulationFrame } from "../../../domain/simulation/types";
import {
  buildRuleTimeline,
  firstFailureAtOrBefore,
  niceTimeStep,
  pairSummarySegments,
  ruleTag,
  valueAt,
} from "./ruleTimelineModel";
import { parseFrame } from "../../../domain/simulation/protocol";
import { RULE_16_ID, monitoredFrames } from "../../../test/fixtures/monitoredFrames";

const R16 = "Rule 16: Give-Way Vessel Takes Early and Substantial Action";

describe("buildRuleTimeline on the recorded two-vessel crossing", () => {
  const timeline = buildRuleTimeline(twoVesselFrames());
  const pair = timeline.pairs[0]!;

  it("spans the run plus one time step", () => {
    expect(timeline.start).toBe(0);
    expect(timeline.end).toBe(730);
    expect(timeline.pairs.map((p) => p.relationId)).toEqual(["0->1"]);
  });

  it("joins the encounter type into segments", () => {
    expect(pair.encounter.map((s) => [s.start, s.end, s.value.type])).toEqual([
      [0, 390, "CROSSING_FROM_PORT"],
      [390, 730, "OTHER"],
    ]);
  });

  it("keeps one track per rule and subject, rules before suggestions, encounter-wide rules first", () => {
    expect(pair.rules.map((r) => `${ruleTag(r)} ${r.subjectActorName}`)).toEqual([
      "R8 ",
      "R8 os",
      "R16 os",
      "Tip os",
    ]);
  });

  it("records the results over time and the first failure", () => {
    const r16 = pair.rules.find((r) => r.ruleName === R16)!;
    expect(r16.segments.map((s) => [s.start, s.end, s.value])).toEqual([
      [10, 70, "UNKNOWN"],
      [70, 730, "FAILED"],
    ]);
    expect(r16.firstFailure).toBe(70);
    expect(valueAt(r16.segments, 5)).toBeNull();
    expect(valueAt(r16.segments, 69)).toBe("UNKNOWN");
    expect(valueAt(r16.segments, 70)).toBe("FAILED");
    expect(firstFailureAtOrBefore(r16, 60)).toBeNull();
    expect(firstFailureAtOrBefore(r16, 400)).toBe(70);
  });

  it("summarises a pair by its worst rule result", () => {
    expect(pairSummarySegments(pair).map((s) => [s.start, s.end, s.value])).toEqual([
      [10, 70, "UNKNOWN"],
      [70, 730, "FAILED"],
    ]);
  });
});

describe("buildRuleTimeline on the recorded three-vessel run", () => {
  const timeline = buildRuleTimeline(threeVesselFrames());

  it("orders own ship pairs first", () => {
    expect(timeline.pairs.map((p) => p.relationId)).toEqual(["0->1", "0->2", "1->2"]);
  });

  it("tracks a rule for each vessel of the head-on", () => {
    const headOn = timeline.pairs.find((p) => p.relationId === "0->2")!;
    expect(headOn.encounter[0]!.value.type).toBe("HEAD_ON");
    const r16 = headOn.rules.filter((r) => r.ruleName === R16);
    expect(r16.map((r) => [r.subjectActorName, r.firstFailure])).toEqual([
      ["os", 70],
      ["ts2", 70],
    ]);
  });

  it("keeps a pair in no encounter with its single rule", () => {
    const other = timeline.pairs.find((p) => p.relationId === "1->2")!;
    expect(other.encounter.map((s) => s.value.type)).toEqual(["OTHER"]);
    expect(other.rules.every((r) => r.firstFailure === null)).toBe(true);
  });
});

describe("buildRuleTimeline edge cases", () => {
  it("is empty without frames", () => {
    expect(buildRuleTimeline([])).toEqual({ start: 0, end: 0, pairs: [] });
  });

  it("uses the given time step for the last frame and leaves gaps for missing rules", () => {
    const frames = twoVesselFrames();
    const first = frames[2]!;
    const gap: SimulationFrame = { ...frames[3]!, ruleResults: [] };
    const last = frames[4]!;
    const timeline = buildRuleTimeline([first, gap, last], 2);
    expect(timeline.end).toBe(last.timestamp + 2);
    const track = timeline.pairs[0]!.rules[0]!;
    expect(track.segments.map((s) => [s.start, s.end])).toEqual([
      [first.timestamp, gap.timestamp],
      [last.timestamp, last.timestamp + 2],
    ]);
  });
});

describe("niceTimeStep", () => {
  it("keeps at most eight ticks on round steps", () => {
    expect(niceTimeStep(720)).toBe(120);
    expect(niceTimeStep(60)).toBe(10);
    expect(niceTimeStep(3600)).toBe(600);
    expect(niceTimeStep(10 ** 7)).toBe(14400);
  });
});

describe("buildRuleTimeline with the monitor's rule ids and first failures", () => {
  const frames = monitoredFrames(40, 12, true).map(parseFrame);

  it("keys the tracks by rule id, so a renamed rule stays one track", () => {
    const renamed = frames.map((frame, index) =>
      index < 20
        ? frame
        : {
            ...frame,
            ruleResults: frame.ruleResults.map((result) => ({
              ...result,
              evaluations: result.evaluations.map((rule) => ({ ...rule, ruleName: `${rule.ruleName} (renamed)` })),
            })),
          }
    );
    const pair = buildRuleTimeline(renamed).pairs[0]!;
    expect(pair.rules.map((rule) => rule.key).sort()).toEqual([RULE_16_ID, "rule:8:passing-at-a-safe-distance:0-1:-"].sort());
  });

  it("takes the first failure from the monitor when frames were thinned", () => {
    const thinned = frames.filter((frame) => frame.timestamp % 10 === 0);
    const r16 = buildRuleTimeline(thinned).pairs[0]!.rules.find((rule) => rule.key === RULE_16_ID)!;
    expect(r16.segments.find((segment) => segment.value === "FAILED")!.start).toBe(20);
    expect(r16.firstFailure).toBe(12);
  });

  it("falls back to the first FAILED frame on older frames", () => {
    const older = monitoredFrames(40, 12).map(parseFrame).filter((frame) => frame.timestamp % 10 === 0);
    const r16 = buildRuleTimeline(older).pairs[0]!.rules.find((rule) => rule.ruleNumber === "16")!;
    expect(r16.key).toBe("Rule 16: Give-Way Vessel Takes Early and Substantial Action#0");
    expect(r16.firstFailure).toBe(20);
  });
});
