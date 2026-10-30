import { describe, expect, it } from "vitest";
import { activeStages, firstStep, inputKindOf, itemKindsFor, lastStep, normalizeSteps, sourceStepsFor, stepRange, uploadKindFor, visibleWizardSteps } from "./stepPlan";

describe("stepRange and normalizeSteps", () => {
  it("takes the steps from the first to the last, in chain order", () => {
    expect(stepRange("scene_generation", "simulation")).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(stepRange("trajectory_generation", "trajectory_generation")).toEqual(["trajectory_generation"]);
    expect(stepRange("simulation", "scene_generation")).toEqual(["simulation"]);
  });

  it("reads anything unusable as the whole chain and closes gaps", () => {
    expect(normalizeSteps(undefined)).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeSteps([])).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeSteps(["x", 3])).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(normalizeSteps(["simulation", "trajectory_generation"])).toEqual(["trajectory_generation", "simulation"]);
    expect(normalizeSteps(["scene_generation", "simulation"])).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
  });

  it("names the first and the last step", () => {
    expect(firstStep(["trajectory_generation", "simulation"])).toBe("trajectory_generation");
    expect(lastStep(["trajectory_generation", "simulation"])).toBe("simulation");
  });
});

describe("visibleWizardSteps", () => {
  it("shows the page of each step the campaign runs and hides the others", () => {
    expect(visibleWizardSteps(["scene_generation"])).toEqual(["steps", "input", "domain", "scenes", "resources", "policy", "review"]);
    expect(visibleWizardSteps(["scene_generation", "trajectory_generation"])).toEqual(["steps", "input", "domain", "scenes", "trajectories", "resources", "policy", "review"]);
    expect(visibleWizardSteps(["trajectory_generation"])).toEqual(["steps", "input", "domain", "trajectories", "resources", "policy", "review"]);
    expect(visibleWizardSteps(["simulation"])).toEqual(["steps", "input", "domain", "runs", "resources", "policy", "review"]);
    expect(visibleWizardSteps(["scene_generation", "trajectory_generation", "simulation"])).toEqual(["steps", "input", "domain", "scenes", "trajectories", "runs", "resources", "policy", "review"]);
  });
});

describe("input of the first step", () => {
  it("is catalog classes or scenario files for scene generation, scenes for trajectory generation, trajectories for simulation", () => {
    expect(inputKindOf(["scene_generation", "trajectory_generation"])).toBe("catalog_or_scenarios");
    expect(inputKindOf(["trajectory_generation"])).toBe("scenes");
    expect(inputKindOf(["simulation"])).toBe("trajectories");
  });

  it("allows the item kinds, history steps and upload kind that fit", () => {
    expect(itemKindsFor(["trajectory_generation", "simulation"])).toEqual(["scene"]);
    expect(itemKindsFor(["simulation"])).toEqual(["trajectory_data", "trajectories"]);
    expect(itemKindsFor(["scene_generation"])).toEqual([]);
    expect(sourceStepsFor(["trajectory_generation"])).toEqual(["scene_generation"]);
    expect(sourceStepsFor(["simulation"])).toEqual(["trajectory_generation", "simulation"]);
    expect(sourceStepsFor(["scene_generation"])).toEqual([]);
    expect(uploadKindFor(["trajectory_generation"])).toBe("scene");
    expect(uploadKindFor(["simulation"])).toBe("trajectories");
    expect(uploadKindFor(["scene_generation"])).toBeNull();
  });
});

describe("activeStages", () => {
  const none = { scene: false, trajectories: false, simulation: false };

  it("lists the generation stages of the steps and the monitor stage when anything is post hoc monitored", () => {
    expect(activeStages(["scene_generation"], none)).toEqual(["generate_scene"]);
    expect(activeStages(["scene_generation"], { ...none, scene: true })).toEqual(["generate_scene", "monitor"]);
    expect(activeStages(["trajectory_generation", "simulation"], { ...none, simulation: true })).toEqual(["generate_trajectories", "simulate", "monitor"]);
  });

  it("ignores the monitor of a step it does not run", () => {
    expect(activeStages(["trajectory_generation"], { scene: true, trajectories: false, simulation: true })).toEqual(["generate_trajectories"]);
  });
});
