import { describe, expect, it } from "vitest";
import type { ActorStaticInfo } from "../../domain/simulation/types";
import { buildShipColorsByActorId, getShipColor } from "./shipColors";

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
