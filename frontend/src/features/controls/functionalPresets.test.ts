import { describe, expect, it } from "vitest";
import { filterPresets, type FunctionalPresetEntry } from "./functionalPresets";

const sample: FunctionalPresetEntry[] = [
  {
    path: "/generated_functional_models/all/2vessel_0obstacle_scenarios/functional_model0.problem",
    label: "2vessel_0obstacle_scenarios/functional_model0.problem",
    fileName: "functional_model0.problem",
    folder: "2vessel_0obstacle_scenarios",
    vesselCount: 2,
    obstacleCount: 0,
  },
  {
    path: "/generated_functional_models/all/3vessel_1obstacle_scenarios/functional_model1.problem",
    label: "3vessel_1obstacle_scenarios/functional_model1.problem",
    fileName: "functional_model1.problem",
    folder: "3vessel_1obstacle_scenarios",
    vesselCount: 3,
    obstacleCount: 1,
  },
];

describe("filterPresets", () => {
  it("filters by vessel and obstacle count", () => {
    const result = filterPresets(sample, "", "2", "0");
    expect(result).toHaveLength(1);
    expect(result[0]?.vesselCount).toBe(2);
  });

  it("filters by search query", () => {
    const result = filterPresets(sample, "model1", "any", "any");
    expect(result).toHaveLength(1);
    expect(result[0]?.fileName).toBe("functional_model1.problem");
  });
});
