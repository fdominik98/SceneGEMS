import { describe, expect, it } from "vitest";
import type { LoadedRun } from "../../features/workbench/pages/entryLoader";
import { setupRequestOf } from "./useSimulationWorkflow";

function run(setup: Partial<LoadedRun["setup"]>): LoadedRun {
  return {
    step: "simulation",
    runRecord: {} as LoadedRun["runRecord"],
    scenario: null,
    frames: [],
    setup: { simulationLayer: "kinematic", controlLayer: null, mode: "replay", speedup: null, windVector: [0, 0, 0], waves: null, ...setup },
    input: null,
  };
}

describe("the setup a loaded run fills", () => {
  it("is the kinematic simulator with no control layer for a kinematic run", () => {
    expect(setupRequestOf(run({ mode: "usv_navigation" }))).toMatchObject({ simulatorType: "Kinematic", controlLayer: "none", speedup: null, mode: "usv_navigation" });
  });

  it("is ArduPilot Sim with replay on ArduPilot and SITL's pace for a SITL run", () => {
    expect(setupRequestOf(run({ simulationLayer: "ardupilot_sim", mode: "replay", speedup: 4 }))).toMatchObject({
      simulatorType: "ArduPilot Sim",
      controlLayer: "ardupilot",
      speedup: 4,
      mode: "replay",
      wave: null,
    });
  });

  it("is Gazebo for a run on a Gazebo world, and keeps the current pace when the record names none", () => {
    expect(setupRequestOf(run({ simulationLayer: "gazebo", mode: "replay", speedup: null }))).toMatchObject({ simulatorType: "Gazebo", controlLayer: "ardupilot", speedup: null });
  });

  it("is Gazebo with the custom controller and the run's wind for a custom controller run", () => {
    expect(setupRequestOf(run({ simulationLayer: "gazebo", controlLayer: "custom", mode: "usv_navigation", windVector: [0, 3, 0] }))).toMatchObject({
      simulatorType: "Gazebo",
      controlLayer: "custom",
      speedup: null,
      mode: "usv_navigation",
      windVector: [0, 3, 0],
    });
  });
});
