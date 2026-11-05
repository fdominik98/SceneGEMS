import { describe, expect, it } from "vitest";
import type { ActorStaticInfo } from "../../../domain/simulation/types";
import { buildShipColorsByActorId, getActorPanelDotColor, getShipColor, getSimulationStreamColor } from "./shipColors";

function actor(partial: Partial<ActorStaticInfo> & Pick<ActorStaticInfo, "id">): ActorStaticInfo {
  return {
    name: partial.id,
    isVessel: true,
    isOwnShip: false,
    type: "CargoShip",
    length: 30,
    breadth: 10,
    safetyRadius: 12,
    ...partial,
  };
}

describe("buildShipColorsByActorId", () => {
  it("assigns OS and TS colors for backend vessel-type names", () => {
    const actors = [
      actor({ id: "0", name: "OSPassengerShip", isOwnShip: true }),
      actor({ id: "1", name: "UnspecifiedVesselType" }),
      actor({ id: "2", name: "FishingVessel" }),
    ];
    const colors = buildShipColorsByActorId(actors);
    expect(colors["0"]).toBe("#06b6d4");
    expect(colors["1"]).toBe("#f97316");
    expect(colors["2"]).toBe("#22c55e");
  });

  it("preserves explicit TS labels from generated scenes", () => {
    const actors = [
      actor({ id: "os", name: "OS", isOwnShip: true }),
      actor({ id: "ts2", name: "TS2" }),
    ];
    const colors = buildShipColorsByActorId(actors);
    expect(colors.os).toBe("#06b6d4");
    expect(colors.ts2).toBe("#22c55e");
  });
});

describe("getShipColor", () => {
  it("uses OS color for own ship regardless of vessel type name", () => {
    expect(getShipColor(actor({ id: "0", name: "OSPassengerShip", isOwnShip: true }))).toBe(
      "#06b6d4"
    );
  });
});

describe("light mode", () => {
  const own = actor({ id: "0", name: "OS", isOwnShip: true });
  const target = actor({ id: "1", name: "TS1" });

  it("takes the darker shade of each vessel's hue", () => {
    expect(getShipColor(own, "light")).toBe("#0891b2");
    expect(buildShipColorsByActorId([own, target], "light")).toEqual({ "0": "#0891b2", "1": "#ea580c" });
  });

  it("gives an actor outside the fixed list a color of the light palette", () => {
    const stranger = actor({ id: "x", name: "Buoy", isVessel: false });
    const dark = buildShipColorsByActorId([stranger]).x;
    const light = buildShipColorsByActorId([stranger], "light").x;
    expect(light).not.toBe(dark);
  });

  it("keeps the simulation stream the darker twin of the preview stream", () => {
    const preview = getShipColor(target, "light");
    const simulation = getSimulationStreamColor(target, "light");
    expect(simulation).not.toBe(preview);
    expect(getActorPanelDotColor(target, "animation", "light")).toBe(preview);
    expect(getActorPanelDotColor(target, "simulation", "light")).toBe(simulation);
  });
});
