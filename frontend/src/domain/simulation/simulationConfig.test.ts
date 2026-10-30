import { describe, expect, it } from "vitest";
import { gatewayWsUrl } from "./simulationConfig";

describe("workbench gateway URL", () => {
  it("follows the active cluster's operator URL", () => {
    expect(gatewayWsUrl("http://127.0.0.1:5174")).toBe("ws://127.0.0.1:5174/ws/scenegems_backend_service");
    expect(gatewayWsUrl("https://master.example/")).toBe("wss://master.example/ws/scenegems_backend_service");
  });

  it("is absent without a cluster", () => {
    expect(gatewayWsUrl(null)).toBeNull();
    expect(gatewayWsUrl("")).toBeNull();
  });
});
