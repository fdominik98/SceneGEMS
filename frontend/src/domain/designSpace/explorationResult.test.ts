import { describe, expect, it } from "vitest";
import { describeExploration, exploredFecId, exploredFecsOfResult, isExplorationFec, isExploredFec, parseExplorationResult } from "./explorationResult";

const RESULT = {
  stop_reason: "cap_reached",
  complete: false,
  models_found: 2,
  max_models: 2,
  random_seed: 7,
  elapsed_s: 4.2,
  message: null,
  fecs: [
    { index: 0, vessel_count: 2, obstacle_count: 0 },
    { index: 1, vessel_count: 3, obstacle_count: 1 },
  ],
  functional_scenarios: [{ sha256: "a".repeat(64), size_bytes: 10, kind: "functional_scenario", media_type: "text/plain; charset=utf-8", pointer: null }, null],
};

describe("the exploration's result", () => {
  it("names the classes of the exploration and of its models", () => {
    expect(exploredFecId(3)).toBe("explored/00003");
    expect(isExploredFec("explored/00003")).toBe(true);
    expect(isExploredFec("exploration")).toBe(false);
    expect(isExplorationFec("exploration")).toBe(true);
  });

  it("reads the job's result, or nothing from another job", () => {
    expect(parseExplorationResult(RESULT)?.models_found).toBe(2);
    expect(parseExplorationResult({ scene: {} })).toBeNull();
    expect(parseExplorationResult(null)).toBeNull();
  });

  it("lists the FECs a result names with their artifacts", () => {
    const fecs = exploredFecsOfResult(parseExplorationResult(RESULT)!);
    expect(fecs.map((fec) => [fec.fecId, fec.vesselCount, fec.obstacleCount, fec.artifact?.sha256 ?? null])).toEqual([
      ["explored/00000", 2, 0, "a".repeat(64)],
      ["explored/00001", 3, 1, null],
    ]);
  });

  it("says how many were found and what that means", () => {
    expect(describeExploration({ stop_reason: "exhausted", models_found: 5 })).toBe("5 FECs: all FECs of the design space.");
    expect(describeExploration({ stop_reason: "exhausted", models_found: 1 })).toBe("1 FEC: all FECs of the design space.");
    expect(describeExploration({ stop_reason: "unsatisfiable", models_found: 0 })).toBe("No FEC: the specification has no model within the scope.");
    expect(describeExploration({ stop_reason: "cap_reached", models_found: 100, max_models: 100 })).toBe("The first 100 FECs: the cap of 100 was reached, there may be more.");
    expect(describeExploration({ stop_reason: "timeout", models_found: 17 })).toBe("The first 17 FECs: the time limit ended the search, there may be more.");
    expect(describeExploration({ stop_reason: "timeout", models_found: 0 })).toBe("No FEC: the time limit ended the search before it found one.");
    expect(describeExploration({ stop_reason: "stopped", models_found: 3 })).toBe("The first 3 FECs: the search was stopped, there may be more.");
    expect(describeExploration({ stop_reason: "something_new", models_found: 2 })).toBe("2 FECs (the search ended: something_new).");
  });
});
