import { describe, expect, it } from "vitest";
import type { RuleEvaluation, RuleResultData } from "../../../domain/simulation/types";
import { failedCount, isVesselScopedRule, splitRuleResults } from "./ruleScopes";

const ACTOR_NAMES: Record<string, string> = { "0": "os", "1": "ts1", "2": "ts2" };

function rule(
  number: string,
  title: string,
  subjectActorId: string | null,
  overrides: Partial<RuleEvaluation> = {},
): RuleEvaluation {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  const own = subjectActorId ?? "-";
  return {
    ruleId: `rule:${number}:${slug}:${subjectActorId === null ? "0-1" : `${own}-${own}`}:${own}`,
    ruleName: `Rule ${number}: ${title}`,
    title,
    ruleNumber: number,
    kind: "rule",
    description: "",
    subjectActorId,
    subjectActorName: subjectActorId === null ? "" : ACTOR_NAMES[subjectActorId]!,
    result: "UNKNOWN",
    ...overrides,
  };
}

const apparent = (actorId: string, overrides: Partial<RuleEvaluation> = {}) =>
  rule("8", "Readily Apparent Course Change", actorId, overrides);
const standOn = (actorId: string, overrides: Partial<RuleEvaluation> = {}) =>
  rule("17", "Stand-On Vessel Keeps Course and Speed", actorId, overrides);
const earlyAction = (actorId: string, overrides: Partial<RuleEvaluation> = {}) =>
  rule("16", "Give-Way Vessel Takes Early and Substantial Action", actorId, overrides);
const safeDistance = (overrides: Partial<RuleEvaluation> = {}) =>
  rule("8", "Passing at a Safe Distance", null, overrides);

function group(relationId: string, evaluations: RuleEvaluation[]): RuleResultData {
  const failed = evaluations.filter((evaluation) => evaluation.result === "FAILED");
  return {
    relationId,
    evaluations,
    failedRules: failed.map((evaluation) => evaluation.ruleName),
    overallStatus: failed.length > 0 ? "FAILED" : "NOT_FAILED",
  };
}

describe("isVesselScopedRule", () => {
  it("takes the rules on a vessel's own maneuvering", () => {
    for (const title of [
      "Readily Apparent Course Change",
      "Readily Apparent Speed Change",
      "Course Change Persistence",
      "Course Held After the Manoeuvre",
      "No New Situation While Manoeuvring",
      "Stand-On Vessel Keeps Course and Speed",
    ]) {
      expect(isVesselScopedRule(rule("8", title, "0")), title).toBe(true);
    }
  });

  it("leaves an encounter's rules with the encounter, also when they name one vessel", () => {
    expect(isVesselScopedRule(safeDistance())).toBe(false);
    expect(isVesselScopedRule(earlyAction("0"))).toBe(false);
    expect(isVesselScopedRule(rule("8", "Give-Way Steering After First Evasive", "0"))).toBe(false);
    expect(
      isVesselScopedRule(rule("", "Pass Around the Collision Domain", "0", { kind: "suggestion" })),
    ).toBe(false);
  });

  it("needs a subject vessel", () => {
    expect(isVesselScopedRule(rule("8", "Readily Apparent Course Change", null))).toBe(false);
  });
});

describe("splitRuleResults", () => {
  it("lists a vessel's rule once, however many encounters repeat it", () => {
    const split = splitRuleResults([
      group("0->1", [safeDistance(), apparent("0"), apparent("1"), standOn("1")]),
      group("0->2", [safeDistance(), earlyAction("0"), apparent("0"), apparent("2")]),
      group("1->2", [safeDistance(), apparent("1"), standOn("1"), apparent("2")]),
    ]);

    expect(split.vessels.map((vessel) => [vessel.actorName, vessel.evaluations.map((item) => item.ruleNumber)])).toEqual([
      ["os", ["8"]],
      ["ts1", ["8", "17"]],
      ["ts2", ["8"]],
    ]);
    expect(split.encounters.map((encounter) => [encounter.relationId, encounter.evaluations.map((item) => item.title)])).toEqual([
      ["0->1", ["Passing at a Safe Distance"]],
      ["0->2", ["Passing at a Safe Distance", "Give-Way Vessel Takes Early and Substantial Action"]],
      ["1->2", ["Passing at a Safe Distance"]],
    ]);
  });

  it("keeps an encounter rule of one vessel under each of its encounters", () => {
    const split = splitRuleResults([
      group("0->1", [earlyAction("0", { result: "FAILED" })]),
      group("0->2", [earlyAction("0", { result: "PASSED" })]),
    ]);

    expect(split.vessels).toEqual([]);
    expect(split.encounters.map((encounter) => encounter.evaluations.map((item) => item.result))).toEqual([["FAILED"], ["PASSED"]]);
  });

  it("orders the vessels by name, whatever order the frame lists them in", () => {
    const split = splitRuleResults([group("1->2", [apparent("2"), apparent("1")]), group("0->2", [apparent("0")])]);

    expect(split.vessels.map((vessel) => vessel.actorName)).toEqual(["os", "ts1", "ts2"]);
  });

  it("keeps the worst result and the earliest failure when the copies of a rule differ", () => {
    const split = splitRuleResults([
      group("0->1", [apparent("0", { result: "PASSED", firstFailedAt: null })]),
      group("0->2", [apparent("0", { result: "FAILED", firstFailedAt: 40 })]),
      group("0->3", [apparent("0", { result: "UNKNOWN", firstFailedAt: 25 })]),
    ]);

    expect(split.vessels).toHaveLength(1);
    expect(split.vessels[0]!.evaluations).toHaveLength(1);
    expect(split.vessels[0]!.evaluations[0]).toMatchObject({ result: "FAILED", firstFailedAt: 25 });
  });

  it("tells a vessel's rules apart by name on frames without rule ids", () => {
    const legacy = (evaluation: RuleEvaluation): RuleEvaluation => ({ ...evaluation, ruleId: undefined });
    const split = splitRuleResults([
      group("0->1", [legacy(apparent("0")), legacy(standOn("0"))]),
      group("0->2", [legacy(apparent("0")), legacy(standOn("0"))]),
    ]);

    expect(split.vessels[0]!.evaluations.map((item) => item.ruleNumber)).toEqual(["8", "17"]);
  });

  it("returns no vessels for a frame without vessel rules", () => {
    const split = splitRuleResults([group("0->1", [safeDistance()])]);

    expect(split.vessels).toEqual([]);
    expect(split.encounters).toEqual([{ relationId: "0->1", evaluations: [safeDistance()] }]);
  });
});

describe("failedCount", () => {
  it("counts the failed evaluations", () => {
    expect(failedCount([apparent("0", { result: "FAILED" }), standOn("0"), safeDistance({ result: "FAILED" })])).toBe(2);
    expect(failedCount([])).toBe(0);
  });
});
