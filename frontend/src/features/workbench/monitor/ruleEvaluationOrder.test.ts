import { describe, expect, it } from "vitest";
import type { RuleEvaluation } from "../../../domain/simulation/types";
import { sortEvaluations } from "./ruleEvaluationOrder";

function evaluation(overrides: Partial<RuleEvaluation>): RuleEvaluation {
  return {
    ruleName: "Rule 16: Give-Way Vessel Takes Early and Substantial Action",
    title: "Give-Way Vessel Takes Early and Substantial Action",
    ruleNumber: "16",
    kind: "rule",
    description: "",
    subjectActorId: "0",
    subjectActorName: "os",
    result: "UNKNOWN",
    ...overrides,
  };
}

describe("sortEvaluations", () => {
  it("lists failures first, then rules by number before suggestions", () => {
    const sorted = sortEvaluations([
      evaluation({ kind: "suggestion", ruleNumber: "", title: "Pass Around" }),
      evaluation({ ruleNumber: "17", title: "Stand-On" }),
      evaluation({ ruleNumber: "8", title: "Safe Distance", result: "FAILED" }),
      evaluation({ ruleNumber: "8", title: "Readily Apparent" }),
    ]);
    expect(sorted.map((item) => item.title)).toEqual(["Safe Distance", "Readily Apparent", "Stand-On", "Pass Around"]);
  });

  it("orders the paragraphs of one rule, and a rule with a paragraph by its number", () => {
    const sorted = sortEvaluations([
      evaluation({ ruleNumber: "17(a)(i)", title: "Stand-On" }),
      evaluation({ ruleNumber: "16", title: "Early Action" }),
      evaluation({ ruleNumber: "8(d)", title: "Safe Distance" }),
      evaluation({ ruleNumber: "8(b)", title: "Readily Apparent" }),
      evaluation({ ruleNumber: "8(c)", title: "No New Situation" }),
    ]);
    expect(sorted.map((item) => item.ruleNumber)).toEqual(["8(b)", "8(c)", "8(d)", "16", "17(a)(i)"]);
  });

  it("orders one rule of two vessels by vessel, whatever order the frame lists them in", () => {
    const target = evaluation({ subjectActorId: "1", subjectActorName: "ts1" });
    const own = evaluation({});
    expect(sortEvaluations([target, own])).toEqual([own, target]);
    expect(sortEvaluations([own, target])).toEqual([own, target]);
  });
});
