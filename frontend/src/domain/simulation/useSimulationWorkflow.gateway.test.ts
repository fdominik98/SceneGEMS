import { describe, expect, it } from "vitest";
import { isRetiredGatewayMessage } from "./useSimulationWorkflow";
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
