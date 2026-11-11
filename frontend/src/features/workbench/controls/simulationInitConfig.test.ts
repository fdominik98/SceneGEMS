import { describe, expect, it } from "vitest";
import type { StackOptionsPayload, StackOptionWire } from "../../../domain/simulation/wireTypes";
import { asvSystemChoice, buildInitializeSimulationConnectionsByAgentIdMap, buildInitialVesselConnectionDrafts, controlLayerChoice, groundControlEndpointLabels, mergePersistedVesselSettings, normalizeDraftStack, realVesselSoftwareChoice, toPersistedVesselDrafts, toTopicSegment, type PersistedVesselConnectionDraft, type VesselDescriptor, type VesselInitConnectionDraft } from "./simulationInitConfig";

const vessels: VesselDescriptor[] = [
  { id: "os", isOwnShip: true },
  { id: "ts-1", isOwnShip: false },
  { id: "ts-2", isOwnShip: false },
];

describe("simulationInitConfig", () => {
  it("creates deterministic default vessel names and topics", () => {
    const drafts = buildInitialVesselConnectionDrafts(vessels);
    expect(drafts[0]?.agentName).toBe("os_sim");
    expect(drafts[0]?.topic).toBe("waraps/unit/surface/simulation/os_sim");
    expect(drafts[0]?.asvSystem).toBe("replay");
    expect(drafts[0]?.controlLayer).toBe("ardupilot");
    expect(drafts[0]?.context).toBe("simulation");
    expect(drafts[0]?.port).toBe(14570);
    expect(drafts[1]?.agentName).toBe("ts1_sim");
    expect(drafts[1]?.asvSystem).toBe("replay");
    expect(drafts[1]?.context).toBe("simulation");
    expect(drafts[1]?.port).toBe(14571);
    expect(drafts[2]?.agentName).toBe("ts2_sim");
    expect(drafts[2]?.asvSystem).toBe("replay");
    expect(drafts[2]?.context).toBe("simulation");
    expect(drafts[2]?.port).toBe(14572);
  });

  it("computes default ports from numeric vessel id", () => {
    const drafts = buildInitialVesselConnectionDrafts([
      { id: "0", isOwnShip: true },
      { id: "3", isOwnShip: false },
    ]);
    expect(drafts[0]?.port).toBe(14570);
    expect(drafts[0]?.asvSystem).toBe("mission_planner");
    expect(drafts[1]?.port).toBe(14573);
    expect(drafts[1]?.asvSystem).toBe("replay");
  });

  it("normalizes context labels used in topics", () => {
    expect(toTopicSegment("simulation")).toBe("simulation");
    expect(toTopicSegment("real")).toBe("real");
  });

  it("builds backend map by agent id (simulation includes port and the stack)", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "simulation",
      asvSystem: "replay",
      controlLayer: "ardupilot",
      agentName: "os_sim",
      topic: "waraps/unit/surface/simulation/os_sim",
      port: 14572,
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect(map).toEqual({
      os: {
        context: "simulation",
        asvSystem: "replay",
        controlLayer: "ardupilot",
        controlMode: "autonomous",
        agentName: "os_sim",
        topic: "waraps/unit/surface/simulation/os_sim",
        port: 14572,
      },
    });
  });

  it("sends a real vessel on its own autopilot, without a port", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "real",
      asvSystem: "mission_planner",
      controlLayer: "ardupilot",
      agentName: "os_real",
      topic: "waraps/unit/surface/real/os_real",
      port: 14572,
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect(map).toEqual({
      os: {
        context: "real",
        asvSystem: "mission_planner",
        controlLayer: "real_vessel",
        controlMode: "external",
        agentName: "os_real",
        topic: "waraps/unit/surface/real/os_real",
      },
    });
    expect("port" in map.os!).toBe(false);
  });

  it("includes gazeboVesselModel in backend map when present", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "simulation",
      asvSystem: "replay",
      controlLayer: "ardupilot",
      agentName: "os_sim",
      topic: "waraps/unit/surface/simulation/os_sim",
      port: 14570,
      gazeboVesselModel: "<sdf></sdf>",
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect(map.os).toMatchObject({ gazeboVesselModel: "<sdf></sdf>" });
  });

  it("omits gazeboVesselModel from backend map when empty/cleared", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "simulation",
      asvSystem: "replay",
      controlLayer: "ardupilot",
      agentName: "os_sim",
      topic: "waraps/unit/surface/simulation/os_sim",
      port: 14570,
      gazeboVesselModel: "",
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect("gazeboVesselModel" in map.os!).toBe(false);
  });

  it("persists vessel settings without SDF model content", () => {
    const generated = buildInitialVesselConnectionDrafts(vessels);
    const withModel: VesselInitConnectionDraft = {
      ...generated[0]!,
      agentName: "custom_agent",
      gazeboVesselModel: "<sdf>large</sdf>",
    };
    const persisted = toPersistedVesselDrafts([withModel]);
    expect(persisted[0]).not.toHaveProperty("gazeboVesselModel");
    expect(persisted[0]?.agentName).toBe("custom_agent");

    const restored = mergePersistedVesselSettings(persisted, generated);
    expect(restored[0]?.agentName).toBe("custom_agent");
    expect(restored[0]?.gazeboVesselModel).toBeUndefined();
  });

  it("sends no ArduAgent control mode for USV Navigation", () => {
    const [draft] = buildInitialVesselConnectionDrafts([{ id: "1", isOwnShip: false }]);
    const map = buildInitializeSimulationConnectionsByAgentIdMap([{ ...draft!, asvSystem: "usv_navigation", controlLayer: "custom" }]);
    expect(map["1"]).toMatchObject({ asvSystem: "usv_navigation", controlLayer: "custom" });
    expect("controlMode" in map["1"]!).toBe(false);
  });

  it("upgrades settings saved with a control mode to the ASV system it names", () => {
    const generated = buildInitialVesselConnectionDrafts([{ id: "1", isOwnShip: false }]);
    const legacy = [{ vesselId: "1", controlMode: "external", agentName: "ts1_sim" }] as unknown as PersistedVesselConnectionDraft[];
    const [restored] = mergePersistedVesselSettings(legacy, generated);
    expect(restored?.asvSystem).toBe("mission_planner");
    expect(restored).not.toHaveProperty("controlMode");
  });

  it("keeps a choice saved while the ASV system was called the ASV software", () => {
    const generated = buildInitialVesselConnectionDrafts([{ id: "1", isOwnShip: false }]);
    const legacy = [{ vesselId: "1", asvSoftware: "usv_navigation", agentName: "ts1_sim" }] as unknown as PersistedVesselConnectionDraft[];
    const [restored] = mergePersistedVesselSettings(legacy, generated);
    expect(restored?.asvSystem).toBe("usv_navigation");
    expect(restored).not.toHaveProperty("asvSoftware");
  });
});

function option(simulatorType: string, asvSystem: StackOptionWire["asvSystem"], controlLayer: StackOptionWire["controlLayer"], reason = ""): StackOptionWire {
  return {
    simulatorType,
    asvSystem,
    controlLayer,
    available: reason === "",
    status: reason === "" ? "available" : "unavailable",
    reason,
    interactiveOnly: false,
    repeatabilityTier: reason === "" ? "exact" : null,
    maxSpeedup: null,
    speedupUnlimited: false,
    wind: null,
    waves: null,
  };
}

const OPTIONS: StackOptionsPayload = {
  simulatorTypes: ["Kinematic", "Gazebo", "ArduPilot Sim"],
  asvSystem: ["replay", "usv_navigation", "mission_planner"],
  controlLayers: ["ardupilot", "custom", "none"],
  combinations: [
    option("Kinematic", "replay", "none"),
    option("Kinematic", "replay", "ardupilot", "the kinematic sim integrates control internally"),
    option("Kinematic", "replay", "custom", "the kinematic sim integrates control internally"),
    option("Kinematic", "mission_planner", "none", "control layer none has no MAVLink endpoint"),
    option("Kinematic", "mission_planner", "ardupilot", "the kinematic sim integrates control internally"),
    option("Kinematic", "mission_planner", "custom", "the custom controller has no MAVLink"),
    option("Gazebo", "replay", "ardupilot"),
    option("Gazebo", "replay", "custom"),
    option("Gazebo", "replay", "none", "Gazebo needs actuator commands"),
  ],
};

describe("stack choices from the resolver's options", () => {
  it("disables a ruled-out control layer with the resolver's reason", () => {
    expect(controlLayerChoice(OPTIONS, "Kinematic", "replay", "none")).toEqual({ available: true, reason: "" });
    expect(controlLayerChoice(OPTIONS, "Kinematic", "replay", "ardupilot")).toEqual({
      available: false,
      reason: "the kinematic sim integrates control internally",
    });
  });

  it("disables an ASV system no control layer runs, with every distinct reason in the control layer column's order", () => {
    expect(asvSystemChoice(OPTIONS, "Kinematic", "replay").available).toBe(true);
    const missionPlanner = asvSystemChoice(OPTIONS, "Kinematic", "mission_planner");
    expect(missionPlanner.available).toBe(false);
    expect(missionPlanner.reason).toBe(
      "the kinematic sim integrates control internally; the custom controller has no MAVLink; control layer none has no MAVLink endpoint"
    );
  });

  it("offers everything until the backend has sent its options", () => {
    expect(controlLayerChoice(null, "Kinematic", "replay", "ardupilot").available).toBe(true);
  });

  it("switches a vessel to a control layer that runs its ASV system on the simulator", () => {
    const [draft] = buildInitialVesselConnectionDrafts([{ id: "1", isOwnShip: false }]);
    expect(normalizeDraftStack(draft!, "Kinematic", OPTIONS).controlLayer).toBe("none");
    expect(normalizeDraftStack(draft!, "Gazebo", OPTIONS)).toBe(draft);
  });

  it("leaves a vessel whose ASV system nothing runs as it is, for the backend to refuse with its reason", () => {
    const [draft] = buildInitialVesselConnectionDrafts([{ id: "0", isOwnShip: true }]);
    expect(normalizeDraftStack(draft!, "Kinematic", OPTIONS)).toBe(draft);
  });
});

describe("groundControlEndpointLabels", () => {
  it("lists where Mission Planner connects, by vessel id", () => {
    expect(groundControlEndpointLabels({ "10": 49155, "2": 49153 })).toEqual([
      "vessel 2: TCP localhost:49153",
      "vessel 10: TCP localhost:49155",
    ]);
    expect(groundControlEndpointLabels({})).toEqual([]);
  });
});

describe("real vessel choices", () => {
  const REAL_OPTIONS: StackOptionsPayload = {
    ...OPTIONS,
    combinations: [
      ...OPTIONS.combinations,
      option("Real vessel", "replay", "real_vessel"),
      option("Real vessel", "mission_planner", "real_vessel"),
      option("Real vessel", "on_board", "real_vessel"),
      option("Real vessel", "usv_navigation", "real_vessel", "ArduAgent has no command for USV Navigation"),
    ],
  };

  it("offers what ArduAgent can steer and the vessel's own software", () => {
    expect(realVesselSoftwareChoice(REAL_OPTIONS, "on_board")).toEqual({ available: true, reason: "" });
    expect(realVesselSoftwareChoice(REAL_OPTIONS, "usv_navigation")).toEqual({ available: false, reason: "ArduAgent has no command for USV Navigation" });
    expect(realVesselSoftwareChoice(OPTIONS, "replay")).toEqual({ available: false, reason: "The server does not offer real vessels." });
    expect(realVesselSoftwareChoice(null, "on_board").available).toBe(true);
  });

  it("gives a real vessel software that can steer it, and a simulated one software it runs", () => {
    const [draft] = buildInitialVesselConnectionDrafts([{ id: "0", isOwnShip: true }]);
    const real = { ...draft!, context: "real" as const, asvSystem: "usv_navigation" as const };
    expect(normalizeDraftStack(real, "Gazebo", REAL_OPTIONS).asvSystem).toBe("replay");
    const onBoard = { ...real, asvSystem: "on_board" as const };
    expect(normalizeDraftStack(onBoard, "Gazebo", REAL_OPTIONS)).toBe(onBoard);
    expect(normalizeDraftStack({ ...onBoard, context: "simulation" }, "Kinematic", REAL_OPTIONS)).toMatchObject({ asvSystem: "replay", controlLayer: "none" });
  });
});

describe("the Mission Planner endpoints of an attended job", () => {
  it("name the worker node that runs the vessels", () => {
    expect(groundControlEndpointLabels({ "0": 49153 }, "10.88.0.7")).toEqual(["vessel 0: TCP 10.88.0.7:49153"]);
    expect(groundControlEndpointLabels({}, "10.88.0.7")).toEqual([]);
  });
});
