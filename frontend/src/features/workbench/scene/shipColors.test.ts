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
    expect(colors["0"]).toBe("#00a5c2");
    expect(colors["1"]).toBe("#fa6600");
    expect(colors["2"]).toBe("#19ab4e");
  });

  it("preserves explicit TS labels from generated scenes", () => {
    const actors = [
      actor({ id: "os", name: "OS", isOwnShip: true }),
      actor({ id: "ts2", name: "TS2" }),
    ];
    const colors = buildShipColorsByActorId(actors);
    expect(colors.os).toBe("#00a5c2");
    expect(colors.ts2).toBe("#19ab4e");
  });
});

describe("getShipColor", () => {
  it("uses OS color for own ship regardless of vessel type name", () => {
    expect(getShipColor(actor({ id: "0", name: "OSPassengerShip", isOwnShip: true }))).toBe(
      "#00a5c2"
    );
  });
});

describe("light mode", () => {
  const own = actor({ id: "0", name: "OS", isOwnShip: true });
  const target = actor({ id: "1", name: "TS1" });

  it("takes the colors of the paper's COLREGS scenario figure as they are", () => {
    expect(getShipColor(own, "light")).toBe("#00778c");
    expect(buildShipColorsByActorId([own, target], "light")).toEqual({ "0": "#00778c", "1": "#ad4700" });
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

describe("the paper's COLREGS scenario figure", () => {
  const vessels = [
    actor({ id: "0", name: "OS_0", isOwnShip: true }),
    actor({ id: "1", name: "TS_1" }),
    actor({ id: "2", name: "TS_2" }),
    actor({ id: "3", name: "TS_3" }),
  ];

  it("colors os, ts1, ts2 and ts3 as the figure does on the day chart", () => {
    expect(vessels.map((vessel) => getShipColor(vessel, "light"))).toEqual(["#00778c", "#ad4700", "#13813b", "#6d04d1"]);
  });

  it("keeps each figure hue on the night chart, lighter", () => {
    expect(vessels.map((vessel) => getShipColor(vessel, "dark"))).toEqual(["#00a5c2", "#fa6600", "#19ab4e", "#ba74fc"]);
  });

  it("gives the same vessel the same color on every page, whichever way it is named", () => {
    // The scene page names targets TS1, TS2 in order; the backend's frames TS_<id>; a file may use vessel types.
    expect(getShipColor(actor({ id: "2", name: "TS2" }))).toBe(getShipColor(actor({ id: "2", name: "TS_2" })));
    expect(getShipColor(actor({ id: "2", name: "FishingVessel" }))).toBe(getShipColor(actor({ id: "2", name: "TS_2" })));
    const named = buildShipColorsByActorId([vessels[0]!, actor({ id: "1", name: "CargoShip" }), actor({ id: "2", name: "FishingVessel" })]);
    expect([named["1"], named["2"]]).toEqual([getShipColor(vessels[1]!), getShipColor(vessels[2]!)]);
  });
});
