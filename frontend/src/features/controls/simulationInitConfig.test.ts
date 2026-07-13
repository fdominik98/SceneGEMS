import { describe, expect, it } from "vitest";
import {
  buildInitializeSimulationConnectionsByAgentIdMap,
  buildInitialVesselConnectionDrafts,
  extractVesselDescriptorsFromSceneRaw,
  mergePersistedVesselSettings,
  toPersistedVesselDrafts,
  toTopicSegment,
  type VesselDescriptor,
  type VesselInitConnectionDraft,
} from "./simulationInitConfig";

const vessels: VesselDescriptor[] = [
  { id: "os", isOwnShip: true },
  { id: "ts-1", isOwnShip: false },
  { id: "ts-2", isOwnShip: false },
];

describe("simulationInitConfig", () => {
  it("creates deterministic default vessel names and topics", () => {
    const drafts = buildInitialVesselConnectionDrafts(vessels);
    expect(drafts[0]?.agentName).toBe("OS_0_SIM");
    expect(drafts[0]?.topic).toBe("waraps/unit/surface/simulation/OS_0_SIM");
    expect(drafts[0]?.controlMode).toBe("autonomous");
    expect(drafts[0]?.context).toBe("simulation");
    expect(drafts[0]?.port).toBe(14570);
    expect(drafts[1]?.agentName).toBe("TS_1_SIM");
    expect(drafts[1]?.controlMode).toBe("autonomous");
    expect(drafts[1]?.context).toBe("simulation");
    expect(drafts[1]?.port).toBe(14571);
    expect(drafts[2]?.agentName).toBe("TS_2_SIM");
    expect(drafts[2]?.controlMode).toBe("autonomous");
    expect(drafts[2]?.context).toBe("simulation");
    expect(drafts[2]?.port).toBe(14572);
  });

  it("computes default ports from numeric vessel id", () => {
    const drafts = buildInitialVesselConnectionDrafts([
      { id: "0", isOwnShip: true },
      { id: "3", isOwnShip: false },
    ]);
    expect(drafts[0]?.port).toBe(14570);
    expect(drafts[0]?.controlMode).toBe("external");
    expect(drafts[1]?.port).toBe(14573);
    expect(drafts[1]?.controlMode).toBe("autonomous");
  });

  it("normalizes context labels used in topics", () => {
    expect(toTopicSegment("simulation")).toBe("simulation");
    expect(toTopicSegment("real")).toBe("real");
  });

  it("builds backend map by agent id (simulation includes port)", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "simulation",
      controlMode: "autonomous",
      agentName: "OS_0_SIM",
      topic: "waraps/unit/surface/simulation/OS_0_SIM",
      port: 14572,
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect(map).toEqual({
      os: {
        context: "simulation",
        controlMode: "autonomous",
        agentName: "OS_0_SIM",
        topic: "waraps/unit/surface/simulation/OS_0_SIM",
        port: 14572,
      },
    });
  });

  it("omits port for real context in backend map", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "real",
      controlMode: "external",
      agentName: "OS_0_REAL",
      topic: "waraps/unit/surface/real/OS_0_REAL",
      port: 14572,
    };
    const map = buildInitializeSimulationConnectionsByAgentIdMap([draft]);
    expect(map).toEqual({
      os: {
        context: "real",
        controlMode: "external",
        agentName: "OS_0_REAL",
        topic: "waraps/unit/surface/real/OS_0_REAL",
      },
    });
    expect("port" in map.os!).toBe(false);
  });

  it("includes gazeboVesselModel in backend map when present", () => {
    const draft: VesselInitConnectionDraft = {
      vesselId: "os",
      context: "simulation",
      controlMode: "autonomous",
      agentName: "OS_0_SIM",
      topic: "waraps/unit/surface/simulation/OS_0_SIM",
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
      controlMode: "autonomous",
      agentName: "OS_0_SIM",
      topic: "waraps/unit/surface/simulation/OS_0_SIM",
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

  it("extracts vessels from non-canonical scenario actor shapes", () => {
    const descriptors = extractVesselDescriptorsFromSceneRaw({
      actors: [
        { id: "os_main", type: "MiniUSV", isOwnShip: true },
        { id: "ts_alpha", kind: "vessel" },
        { id: "buoy_1", type: "buoy" },
      ],
    });
    expect(descriptors).toEqual([
      { id: "os_main", isOwnShip: true },
      { id: "ts_alpha", isOwnShip: false },
    ]);
  });
});
