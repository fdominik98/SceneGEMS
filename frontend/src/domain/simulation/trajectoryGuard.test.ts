import { describe, expect, it } from "vitest";
import { missingTrajectoriesReason, NO_TRAJECTORIES_MESSAGE } from "./trajectoryGuard";

describe("missingTrajectoriesReason", () => {
  it("refuses a scenario that holds its initial scene only", () => {
    expect(missingTrajectoriesReason(0)).toBe(NO_TRAJECTORIES_MESSAGE);
  });

  it("lets a scenario with trajectories through", () => {
    expect(missingTrajectoriesReason(3600)).toBeNull();
    expect(missingTrajectoriesReason(1)).toBeNull();
  });

  it("leaves a scenario the backend has not reported yet to the backend", () => {
    expect(missingTrajectoriesReason(null)).toBeNull();
  });

  it("tells the user to run a generator", () => {
    expect(NO_TRAJECTORIES_MESSAGE).toContain("generate trajectories first");
    expect(NO_TRAJECTORIES_MESSAGE).toContain("monitor-guided planner or straight");
  });
});
