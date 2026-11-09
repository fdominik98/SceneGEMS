import { describe, expect, it } from "vitest";
import { createActorNamer, FIRST_OBSTACLE_ID, obstacleName, vesselName } from "./actorNaming";

describe("actor names", () => {
  it("names vessels as the paper's figure does: os, ts1, ts2", () => {
    expect(vesselName(0, true)).toBe("os");
    expect([1, 2, 3].map((id) => vesselName(id, false))).toEqual(["ts1", "ts2", "ts3"]);
  });

  it("counts obstacles from 1 while their ids stay from 100", () => {
    expect([FIRST_OBSTACLE_ID, FIRST_OBSTACLE_ID + 1].map(obstacleName)).toEqual(["so1", "so2"]);
  });

  it("names actors by their ids, and those without a numeric id by their order", () => {
    const name = createActorNamer();
    expect(name("0", { isOwnShip: true, isVessel: true })).toBe("os");
    expect(name("2", { isOwnShip: false, isVessel: true })).toBe("ts2");
    expect(name("100", { isOwnShip: false, isVessel: false })).toBe("so1");
    const byOrder = createActorNamer();
    expect(byOrder("own", { isOwnShip: true, isVessel: true })).toBe("os");
    expect(byOrder("a", { isOwnShip: false, isVessel: true })).toBe("ts1");
    expect(byOrder("b", { isOwnShip: false, isVessel: true })).toBe("ts2");
    expect(byOrder("rock", { isOwnShip: false, isVessel: false })).toBe("so1");
  });
});
