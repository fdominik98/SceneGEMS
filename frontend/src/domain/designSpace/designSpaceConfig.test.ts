import { describe, expect, it } from "vitest";
import { designSpaceSectionOf } from "./designSpaceConfig";

describe("the config's design space exploration section", () => {
  it("reads the section with the fields it states, none without one", () => {
    expect(designSpaceSectionOf({ design_space_exploration: { specification: "class A.", scope: "A = 1", max_fecs: null, timeout_s: 60, quota: 2, failure_budget: "unlimited" } })).toEqual({
      specification: "class A.",
      scope: "A = 1",
      max_fecs: null,
      timeout_s: 60,
      quota: 2,
      failure_budget: "unlimited",
    });
    // A preset may leave the specification to the master
    expect(designSpaceSectionOf({ design_space_exploration: { scope: "TS = 2" } })).toEqual({ specification: "", scope: "TS = 2" });
    expect(designSpaceSectionOf({ steps: ["scene_generation"] })).toBeNull();
  });
});
