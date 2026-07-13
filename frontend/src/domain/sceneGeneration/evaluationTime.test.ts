import { describe, expect, it } from "vitest";
import {
  evaluationTimeBaseline,
  hasExceededEvaluationTimeout,
  parseEvaluationTimeSeconds,
  parseEvaluationTimeoutSeconds,
} from "./evaluationTime";

describe("evaluationTime", () => {
  it("reads evaluation_time from evaluation data", () => {
    expect(parseEvaluationTimeSeconds({ evaluation_time: 15.48 })).toBe(15.48);
  });

  it("reads evaluationTime camelCase fallback", () => {
    expect(parseEvaluationTimeSeconds({ evaluationTime: 2.5 })).toBe(2.5);
  });

  it("returns null for missing or invalid values", () => {
    expect(parseEvaluationTimeSeconds(undefined)).toBeNull();
    expect(parseEvaluationTimeSeconds({})).toBeNull();
    expect(parseEvaluationTimeSeconds({ evaluation_time: -1 })).toBeNull();
    expect(parseEvaluationTimeSeconds({ evaluation_time: "bad" })).toBeNull();
  });

  it("prefers timeout from evaluation data over UI fallback", () => {
    expect(parseEvaluationTimeoutSeconds({ timeout: 240 }, 60)).toBe(240);
    expect(parseEvaluationTimeoutSeconds({}, 60)).toBe(60);
  });

  it("detects timeout from evaluation time", () => {
    expect(hasExceededEvaluationTimeout({ evaluation_time: 59.9, timeout: 60 }, 60)).toBe(false);
    expect(hasExceededEvaluationTimeout({ evaluation_time: 60, timeout: 60 }, 60)).toBe(true);
    expect(hasExceededEvaluationTimeout({ evaluation_time: 61 }, 60)).toBe(true);
    expect(hasExceededEvaluationTimeout({}, 60)).toBe(false);
  });

  it("uses per-request baseline for elapsed evaluation time", () => {
    expect(
      hasExceededEvaluationTimeout({ evaluation_time: 165, timeout: 60 }, 60, 100)
    ).toBe(true);
    expect(
      hasExceededEvaluationTimeout({ evaluation_time: 150, timeout: 60 }, 60, 100)
    ).toBe(false);
  });

  it("derives baseline from first evaluation time", () => {
    expect(evaluationTimeBaseline({ evaluation_time: 100.5 })).toBe(100.5);
    expect(evaluationTimeBaseline({})).toBe(0);
  });
});
