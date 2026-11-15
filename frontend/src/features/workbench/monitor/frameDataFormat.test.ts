import { describe, expect, it } from "vitest";
import { ACTOR_FIELD_PRIORITY, actorDisplayFields, asRecord, formatScalar, humanizeKey, sortKeys } from "./frameDataFormat";

describe("frameDataFormat", () => {
  it("asRecord accepts plain objects only", () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord([1])).toBeNull();
    expect(asRecord(null)).toBeNull();
  });

  it("humanizeKey splits camelCase and snake_case", () => {
    expect(humanizeKey("maxSpeed")).toBe("Max Speed");
    expect(humanizeKey("min_length")).toBe("Min length");
  });

  it("formatScalar formats booleans, numbers and empties", () => {
    expect(formatScalar(true)).toBe("Yes");
    expect(formatScalar(null)).toBe("-");
    expect(formatScalar(1.5)).toBe("1.5");
    expect(formatScalar(12345.678)).toBe("1.235e+4");
  });

  it("sortKeys puts priority keys first, rest alphabetical", () => {
    expect(sortKeys(["z", "b", "x", "a"], ["x", "z"])).toEqual(["x", "z", "a", "b"]);
  });

  it("orders the block coefficient with the hull dimensions and the steering type before the rudder", () => {
    const keys = ["rudderMass", "steeringType", "mass", "blockCoefficient", "draft", "maxAcceleration", "id"];
    expect(sortKeys(keys, ACTOR_FIELD_PRIORITY)).toEqual([
      "id",
      "draft",
      "blockCoefficient",
      "mass",
      "maxAcceleration",
      "steeringType",
      "rudderMass",
    ]);
    expect(humanizeKey("steeringType")).toBe("Steering Type");
    expect(humanizeKey("blockCoefficient")).toBe("Block Coefficient");
  });

  it("actorDisplayFields writes the steering type in words and leaves the rest as it is", () => {
    const vessel = { id: "1", type: "CargoShip", steeringType: "vectored_thrust", blockCoefficient: 0.72 };
    expect(actorDisplayFields(vessel)).toEqual({ id: "1", type: "CargoShip", steeringType: "vectored thrust", blockCoefficient: 0.72 });
    expect(vessel.steeringType).toBe("vectored_thrust");
    expect(actorDisplayFields({ steeringType: "rudder" }).steeringType).toBe("rudder");
    expect(actorDisplayFields({ steeringType: "skid" }).steeringType).toBe("skid");
    expect(formatScalar(actorDisplayFields(vessel).blockCoefficient)).toBe("0.72");
  });

  it("actorDisplayFields leaves an actor without a steering type untouched", () => {
    const obstacle = { id: "2", type: "SmallObstacle", isVessel: false };
    expect(actorDisplayFields(obstacle)).toBe(obstacle);
    expect(actorDisplayFields(obstacle)).not.toHaveProperty("steeringType");
  });
});
