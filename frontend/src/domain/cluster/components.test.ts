import { describe, expect, it } from "vitest";
import { sampleWorkerNode } from "../../test/fixtures/clusterViews";
import {
  COMPONENTS,
  componentLabel,
  describeComponents,
  isWhollyOutOfDate,
  jobComponents,
  listsJob,
  offersJob,
  orderedComponents,
  runStackComponents,
  simulationPayloadComponents,
  staleComponents,
} from "./components";
import { workerNodeViewSchema } from "./schemas";

const GAZEBO = ["asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo"];
const CUSTOM = ["asv_software/replay", "control_layer/custom", "simulation_layer/gazebo"];

function workerNodeWith(components: [string, "usable" | "out_of_date"][], slots: Record<string, number> = { simulation: 2 }) {
  return workerNodeViewSchema.parse(
    sampleWorkerNode({
      slots: Object.fromEntries(Object.entries(slots).map(([jobType, count]) => [jobType, { slots: count, slots_in_use: 0 }])),
      components: components.map(([component, state]) => ({ component, images: [], state })),
    })
  );
}

describe("the component catalog", () => {
  it("lists the campaign layers and the subsystems in the backend's order", () => {
    expect(COMPONENTS).toHaveLength(13);
    expect(orderedComponents(["monitoring", "simulation_layer/gazebo", "asv_software/replay", "monitoring", "gpu"])).toEqual(["asv_software/replay", "simulation_layer/gazebo", "monitoring", "gpu"]);
    expect(componentLabel("simulation_layer/ardupilot_sim")).toBe("ArduPilot SITL");
    expect(componentLabel("gpu")).toBe("gpu");
    expect(describeComponents(GAZEBO)).toBe("Replay, ArduPilot and Gazebo");
  });

  it("derives a run's components from its stack section as the stage graph does", () => {
    expect(runStackComponents(undefined)).toEqual(["asv_software/replay", "control_layer/none", "simulation_layer/kinematic"]);
    expect(runStackComponents({ simulation_layer: "kinematic", mode: "usv_navigation" })).toEqual([
      "asv_software/replay",
      "asv_software/usv_navigation",
      "control_layer/none",
      "simulation_layer/kinematic",
    ]);
    expect(runStackComponents({ simulation_layer: "gazebo", speedup: 2 })).toEqual(GAZEBO);
    expect(runStackComponents({ simulation_layer: "gazebo", control_layer: "ardupilot" })).toEqual(GAZEBO);
    expect(runStackComponents({ simulation_layer: "ardupilot_sim", mode: "usv_navigation" })).toEqual([
      "asv_software/replay",
      "asv_software/usv_navigation",
      "control_layer/ardupilot",
      "simulation_layer/ardupilot_sim",
    ]);
    expect(runStackComponents({ simulation_layer: "gazebo", control_layer: "custom" })).toEqual(CUSTOM);
    expect(runStackComponents({ simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" })).toEqual([
      "asv_software/replay",
      "asv_software/usv_navigation",
      "control_layer/custom",
      "simulation_layer/gazebo",
    ]);
  });

  it("derives a job's components from its payload as the control node does", () => {
    expect(simulationPayloadComponents({ runner: "ardupilot", simulation_layer: "gazebo" })).toEqual(GAZEBO);
    expect(simulationPayloadComponents({ runner: "kinematic", mode: "replay" })).toEqual(runStackComponents({}));
    expect(simulationPayloadComponents({ runner: "gazebo_custom" })).toEqual(CUSTOM);
    expect(simulationPayloadComponents({ runner: "gazebo_custom", mode: "usv_navigation" })).toEqual(runStackComponents({ simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" }));
    expect(simulationPayloadComponents({ runner: "ardupilot", simulation_layer: "gazebo", mode: "usv_navigation" })).toEqual(runStackComponents({ simulation_layer: "gazebo", mode: "usv_navigation" }));
    expect(jobComponents("simulation", { runner: "ardupilot", simulation_layer: "ardupilot_sim" })).toEqual(["asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"]);
    expect(jobComponents("monitoring.post_hoc")).toEqual(["monitoring"]);
    expect(jobComponents("calibration.deviation")).toEqual(["calibration"]);
    expect(jobComponents("future.kind")).toEqual([]);
  });
});

describe("a worker node's components", () => {
  it("runs a job with slots for its type and every component usable", () => {
    const workerNode = workerNodeWith([
      ["asv_software/replay", "usable"],
      ["control_layer/ardupilot", "usable"],
      ["simulation_layer/gazebo", "out_of_date"],
      ["simulation_layer/ardupilot_sim", "usable"],
    ]);
    expect(staleComponents(workerNode)).toEqual(["simulation_layer/gazebo"]);
    expect(isWhollyOutOfDate(workerNode)).toBe(false);
    expect(listsJob(workerNode, "simulation", GAZEBO)).toBe(true);
    expect(offersJob(workerNode, "simulation", GAZEBO)).toBe(false);
    expect(offersJob(workerNode, "simulation", ["asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"])).toBe(true);
    expect(offersJob(workerNode, "monitoring.post_hoc", [])).toBe(false);
  });

  it("is wholly out of date once every component is", () => {
    expect(isWhollyOutOfDate(workerNodeWith([["monitoring", "out_of_date"]]))).toBe(true);
    expect(isWhollyOutOfDate(workerNodeWith([]))).toBe(false);
  });
});
