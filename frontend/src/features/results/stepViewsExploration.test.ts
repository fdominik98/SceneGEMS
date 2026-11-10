import { describe, expect, it } from "vitest";
import { chooseStep, describeOrigin, executedSteps, resultSteps } from "./stepViews";

/** The Results section offers no view of the design space exploration: it has no monitor and no findings. */
describe("results of an entry that explored the design space", () => {
  it("leaves the exploration out of the steps it offers", () => {
    const entry = { steps: ["design_space_exploration", "scene_generation", "trajectory_generation"] as const };
    expect(executedSteps({ steps: [...entry.steps] })).toEqual(["design_space_exploration", "scene_generation", "trajectory_generation"]);
    expect(resultSteps({ steps: [...entry.steps] })).toEqual(["scene_generation", "trajectory_generation"]);
    expect(chooseStep({ steps: [...entry.steps] }, "design_space_exploration")).toBe("trajectory_generation");
  });

  it("has no step to show for an entry that only explored", () => {
    expect(resultSteps({ steps: ["design_space_exploration"] })).toEqual([]);
    expect(chooseStep({ steps: ["design_space_exploration"] }, null)).toBeNull();
    expect(describeOrigin("design_space_exploration")).toBe("run on the design space exploration page");
  });
});
