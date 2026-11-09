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

  it("orders one rule of two vessels by vessel, whatever order the frame lists them in", () => {
    const target = evaluation({ subjectActorId: "1", subjectActorName: "ts1" });
    const own = evaluation({});
    expect(sortEvaluations([target, own])).toEqual([own, target]);
    expect(sortEvaluations([own, target])).toEqual([own, target]);
  });
});
