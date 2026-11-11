import { describe, expect, it } from "vitest";
import { NO_TRAJECTORIES_MESSAGE } from "./trajectoryGuard";

describe("the message of a simulation without trajectories", () => {
  it("tells the user to run a generator", () => {
    expect(NO_TRAJECTORIES_MESSAGE).toContain("generate trajectories first");
    expect(NO_TRAJECTORIES_MESSAGE).toContain("monitor-guided planner or straight");
  });
});
