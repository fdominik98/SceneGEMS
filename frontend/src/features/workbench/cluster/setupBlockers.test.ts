import { describe, expect, it } from "vitest";
import type { StackOptionsPayload, StackOptionWire } from "../../../domain/simulation/wireTypes";
import { setupBlockers } from "./setupBlockers";
import { planSimulationRun, type ClusterRunPlan, type SimulationSetup, type SimulationVesselSetup } from "./simulationJobs";

function vessel(vesselId: string, overrides: Partial<SimulationVesselSetup> = {}): SimulationVesselSetup {
  return { vesselId, context: "simulation", asvSystem: "replay", controlLayer: "ardupilot", isOwnShip: vesselId === "0", ...overrides };
}

function setup(vessels: SimulationVesselSetup[], overrides: Partial<SimulationSetup> = {}): SimulationSetup {
  return { simulatorType: "Gazebo", vessels, windVector: [0, 0, 0], waveAmplitude: 0, waveSpeed: 0, speedup: 1, body: {}, ...overrides };
}

function option(simulatorType: string, asvSystem: StackOptionWire["asvSystem"], controlLayer: StackOptionWire["controlLayer"], overrides: Partial<StackOptionWire> = {}): StackOptionWire {
  return {
    simulatorType,
    asvSystem,
    controlLayer,
    available: true,
    status: "available",
    reason: "",
    interactiveOnly: false,
    repeatabilityTier: "bounded",
    maxSpeedup: null,
    speedupUnlimited: false,
    wind: "supported",
    waves: "supported",
    ...overrides,
  };
}

/** The combinations the backend's resolver sends, as far as these rules read them (gateway/stack_options.py). */
const OPTIONS: StackOptionsPayload = {
  simulatorTypes: ["Gazebo", "ArduPilot Sim", "Kinematic"],
  asvSystem: ["replay", "usv_navigation", "mission_planner", "on_board"],
  controlLayers: ["ardupilot", "custom", "none", "real_vessel"],
  combinations: [
    option("Gazebo", "replay", "ardupilot"),
    option("Gazebo", "replay", "custom"),
    option("Gazebo", "usv_navigation", "ardupilot"),
    option("Gazebo", "usv_navigation", "custom"),
    option("Gazebo", "mission_planner", "ardupilot", { interactiveOnly: true }),
    option("Gazebo", "mission_planner", "custom", { available: false, status: "unavailable", reason: "the custom controller has no MAVLink" }),
    option("ArduPilot Sim", "replay", "ardupilot", { maxSpeedup: 50, wind: "unsupported" }),
    option("ArduPilot Sim", "usv_navigation", "ardupilot", { maxSpeedup: 20, wind: "unsupported" }),
    option("ArduPilot Sim", "mission_planner", "ardupilot", { maxSpeedup: 100, wind: "unsupported", interactiveOnly: true }),
    option("Kinematic", "replay", "none", { speedupUnlimited: true, wind: "unsupported", waves: "unsupported" }),
    option("Kinematic", "usv_navigation", "none", { speedupUnlimited: true, wind: "unsupported", waves: "unsupported" }),
    option("Kinematic", "mission_planner", "none", { available: false, status: "unavailable", reason: "control layer none has no MAVLink endpoint" }),
  ],
};

function blockersOf(checked: SimulationSetup, options: StackOptionsPayload | null = OPTIONS): string[] {
  return setupBlockers(checked, planSimulationRun(checked) as ClusterRunPlan, options);
}

describe("why no job runs a setup", () => {
  it("lets the setups a job runs through", () => {
    expect(blockersOf(setup([vessel("0", { asvSystem: "usv_navigation" }), vessel("1"), vessel("2")]))).toEqual([]);
    expect(blockersOf(setup([vessel("0", { asvSystem: "usv_navigation", controlLayer: "custom" }), vessel("1", { controlLayer: "custom" })]))).toEqual([]);
    expect(blockersOf(setup([vessel("0", { asvSystem: "mission_planner" }), vessel("1")]))).toEqual([]);
    expect(blockersOf(setup([vessel("0"), vessel("1", { asvSystem: "usv_navigation" })], { simulatorType: "ArduPilot Sim" }))).toEqual([]);
    expect(blockersOf(setup([vessel("0", { controlLayer: "none" }), vessel("1", { controlLayer: "none" })], { simulatorType: "Kinematic" }))).toEqual([]);
  });

  it("refuses a Gazebo world on both ArduPilot and the custom controller, and names the vessels on each", () => {
    const mixed = setup([vessel("0", { asvSystem: "usv_navigation" }), vessel("1", { controlLayer: "custom" }), vessel("2", { controlLayer: "custom" })]);
    expect(planSimulationRun(mixed)).toMatchObject({ runner: "attended" });
    const blockers = blockersOf(mixed);
    expect(blockers).toHaveLength(1);
    expect(blockers[0]).toContain("either with ArduPilot or with the custom controller");
    expect(blockers[0]).toContain("now os on ArduPilot, ts1 and ts2 on Custom");
    // The rule is the simulation layer's own, so it holds before the stack options have arrived
    expect(blockersOf(mixed, null)).toEqual(blockers);
    // A real vessel is on its own layers and is not part of the world
    expect(blockersOf(setup([vessel("0"), vessel("1", { context: "real", controlLayer: "real_vessel" })]))).toEqual([]);
  });

  it("refuses a vessel whose stack does not run on the simulator", () => {
    const blockers = blockersOf(setup([vessel("0", { asvSystem: "mission_planner", controlLayer: "none" }), vessel("1", { controlLayer: "none" })], { simulatorType: "Kinematic" }));
    expect(blockers).toEqual(["os cannot run Mission Planner with the control layer None (kinematic) on Kinematic: pick another ASV system, control layer or simulator."]);
    // Every combination counts as running until the backend has said which do
    expect(blockersOf(setup([vessel("0", { asvSystem: "mission_planner", controlLayer: "none" })], { simulatorType: "Kinematic" }), null)).toEqual([]);
  });

  it("refuses wind and waves an attended job would apply where the simulator has none", () => {
    const kinematic = [vessel("0", { controlLayer: "none" }), vessel("1", { controlLayer: "none" })];
    expect(blockersOf(setup(kinematic, { simulatorType: "Kinematic", windVector: [1, 0, 0] }))).toEqual(["Kinematic has no wind: set the wind to zero, or pick a simulator that has it."]);
    expect(blockersOf(setup([vessel("0")], { simulatorType: "ArduPilot Sim", windVector: [0, 2, 0] }))).toEqual(["ArduPilot Sim has no wind: set the wind to zero, or pick a simulator that has it."]);
    expect(blockersOf(setup([vessel("0")], { simulatorType: "ArduPilot Sim", waveAmplitude: 0.5, waveSpeed: 3 }))).toEqual([]);
    expect(blockersOf(setup([vessel("0"), vessel("1")], { windVector: [0, 2, 0], waveAmplitude: 0.5, waveSpeed: 3 }))).toEqual([]);
    const wavy = setup(kinematic, { simulatorType: "Kinematic", waveAmplitude: 0.5, waveSpeed: 3 });
    expect(planSimulationRun(wavy)).toMatchObject({ runner: "attended" });
    expect(blockersOf(wavy)).toEqual(["Kinematic has no waves: set where the waves are going to zero, or pick a simulator that has them."]);
    // The kinematic job applies no weather, so waves that only have a direction do not reach it
    const calmJob = setup(kinematic, { simulatorType: "Kinematic", waveSpeed: 3 });
    expect(planSimulationRun(calmJob)).toMatchObject({ runner: "kinematic" });
    expect(blockersOf(calmJob)).toEqual([]);
  });

  it("refuses a pace above what the slowest stack was measured to keep up with", () => {
    const navigating = [vessel("0", { asvSystem: "usv_navigation" }), vessel("1")];
    expect(planSimulationRun(setup(navigating, { simulatorType: "ArduPilot Sim", speedup: 50 }))).toMatchObject({ runner: "ardupilot" });
    expect(blockersOf(setup(navigating, { simulatorType: "ArduPilot Sim", speedup: 50 }))).toEqual(["USV Navigation on ArduPilot Sim is measured to keep up to 20x real time (os): set the pace to 20 or less."]);
    expect(blockersOf(setup(navigating, { simulatorType: "ArduPilot Sim", speedup: 20 }))).toEqual([]);
    expect(blockersOf(setup([vessel("0"), vessel("1")], { simulatorType: "ArduPilot Sim", speedup: 50 }))).toEqual([]);
    // Unmeasured on Gazebo: the worker node only warns
    expect(blockersOf(setup(navigating, { speedup: 50 }))).toEqual([]);
    // A kinematic job and the custom controller's follow the watch speed, not the pace
    expect(blockersOf(setup([vessel("0", { controlLayer: "none" })], { simulatorType: "Kinematic", speedup: 50 }))).toEqual([]);
  });

  describe("with a real vessel", () => {
    const real = vessel("1", { context: "real", controlLayer: "real_vessel" });

    it("lets replay and Mission Planner on ArduPilot run beside it, in real time", () => {
      expect(blockersOf(setup([vessel("0"), real], { simulatorType: "ArduPilot Sim" }))).toEqual([]);
      expect(blockersOf(setup([vessel("0", { asvSystem: "mission_planner" }), { ...real, asvSystem: "on_board" }]))).toEqual([]);
      expect(blockersOf(setup([{ ...real, vesselId: "0", isOwnShip: true }, real], { simulatorType: "Kinematic" }))).toEqual([]);
    });

    it("refuses a simulated vessel no ArduAgent drives", () => {
      const message = (names: string) => `Beside a real vessel every simulated vessel runs through an ArduAgent, which takes replay or Mission Planner on ArduPilot (on Gazebo or ArduPilot Sim): change ${names}.`;
      expect(blockersOf(setup([vessel("0", { asvSystem: "usv_navigation" }), real], { simulatorType: "ArduPilot Sim" }))).toEqual([message("os")]);
      expect(blockersOf(setup([vessel("0", { controlLayer: "custom" }), real, vessel("2", { controlLayer: "custom" })]))).toEqual([message("os and ts2")]);
      expect(blockersOf(setup([vessel("0", { controlLayer: "none" }), real], { simulatorType: "Kinematic" }))).toEqual([message("os")]);
    });

    it("refuses a pace above real time", () => {
      expect(blockersOf(setup([vessel("0"), real], { simulatorType: "ArduPilot Sim", speedup: 5 }))).toEqual(["A real vessel runs in real time: set the pace to 1."]);
    });
  });
});
