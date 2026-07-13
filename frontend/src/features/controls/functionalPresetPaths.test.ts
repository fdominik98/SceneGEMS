import { describe, expect, it } from "vitest";
import { formatFunctionalPresetLabel } from "./functionalPresetPaths";

describe("formatFunctionalPresetLabel", () => {
  it("shows only the path after the all folder", () => {
    expect(
      formatFunctionalPresetLabel(
        "/generated_functional_models/all/3vessel_0obstacle_scenarios/functional_model10.problem"
      )
    ).toBe("3vessel_0obstacle_scenarios/functional_model10.problem");
  });
});
