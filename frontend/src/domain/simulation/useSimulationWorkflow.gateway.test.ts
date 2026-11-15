import { describe, expect, it } from "vitest";
import { isRetiredGatewayMessage, isUnknownVesselModelPresetsQuery } from "./useSimulationWorkflow";
import { RETIRED_GATEWAY_MESSAGES } from "./wireTypes";

describe("the gateway messages of the former live session", () => {
  it.each([...RETIRED_GATEWAY_MESSAGES])("are recognised by their type: %s", (type) => {
    expect(isRetiredGatewayMessage({ type, status: "connected" })).toBe(true);
  });

  it("are no other message, and nothing without a type", () => {
    expect(isRetiredGatewayMessage({ type: "stack_options" })).toBe(false);
    expect(isRetiredGatewayMessage({ type: "something_new" })).toBe(false);
    expect(isRetiredGatewayMessage({ status: "connected" })).toBe(false);
    expect(isRetiredGatewayMessage({ type: 7 })).toBe(false);
    expect(isRetiredGatewayMessage(null)).toBe(false);
    expect(isRetiredGatewayMessage("simulation_status")).toBe(false);
  });
});

describe("a control node of an earlier release, asked for the vessel model presets", () => {
  it("refuses the request it does not know, which is no error to show", () => {
    expect(isUnknownVesselModelPresetsQuery("Unknown message type: query_vessel_model_presets")).toBe(true);
    expect(isUnknownVesselModelPresetsQuery(" Unknown message type: query_vessel_model_presets\n")).toBe(true);
  });

  it("is told apart from every other error", () => {
    expect(isUnknownVesselModelPresetsQuery("Unknown message type: query_something_else")).toBe(false);
    expect(isUnknownVesselModelPresetsQuery("No scenario is loaded.")).toBe(false);
    expect(isUnknownVesselModelPresetsQuery("Invalid simulation configuration: vessel 0 cannot take the vessel model preset mariner")).toBe(false);
    expect(isUnknownVesselModelPresetsQuery("")).toBe(false);
  });
});
