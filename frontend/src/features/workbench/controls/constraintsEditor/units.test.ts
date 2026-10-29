import { describe, expect, it } from "vitest";
import {
  alternateUnit,
  formatDisplayNumber,
  fromAlternateUnit,
  parseFieldComment,
  toAlternateUnit,
} from "./units";

describe("parseFieldComment", () => {
  it("reads seconds from parentheses and cleans the description", () => {
    const parsed = parseFieldComment(" Time (seconds) for a course change to be readily apparent");
    expect(parsed.unit).toBe("seconds");
    expect(parsed.description).toBe("Time for a course change to be readily apparent");
  });

  it("reads radians and drops the spelled out conversion to degrees", () => {
    const parsed = parseFieldComment(" Minimum heading change (radians) to be readily apparent: 30.0 degrees");
    expect(parsed.unit).toBe("radians");
    expect(parsed.description).toBe("Minimum heading change to be readily apparent");
  });

  it("reads m/s from m/s in a parenthesis", () => {
    const parsed = parseFieldComment(" Minimum speed change (m/s) to be readily apparent");
    expect(parsed.unit).toBe("m/s");
    expect(parsed.description).toBe("Minimum speed change to be readily apparent");
  });

  it("prefers the unit after 'in' over a conversion", () => {
    const knots = parseFieldComment(" Maximum vessel speed: 50.0 knots in m/s");
    expect(knots.unit).toBe("m/s");
    expect(knots.description).toBe("Maximum vessel speed");

    const minutes = parseFieldComment(" Safe temporal distance: 20 minutes in seconds");
    expect(minutes.unit).toBe("seconds");
    expect(minutes.description).toBe("Safe temporal distance");
  });

  it("reads meters and trims the unit phrase", () => {
    const parsed = parseFieldComment(" Minimum vessel length in meters");
    expect(parsed.unit).toBe("meters");
    expect(parsed.description).toBe("Minimum vessel length");
  });

  it("reads rate units and keeps a leading conversion as a hint", () => {
    const parsed = parseFieldComment(" ~1.7 deg/s. Maximum angular speed in radians per second");
    expect(parsed.unit).toBe("rad/s");
    expect(parsed.hint).toBe("~1.7 deg/s");
    expect(parsed.description).toBe("Maximum angular speed");
  });

  it("reads acceleration", () => {
    const parsed = parseFieldComment(" generic upper bound. Maximum acceleration in meters per second squared");
    expect(parsed.unit).toBe("m/s²");
    expect(parsed.description).toBe("generic upper bound. Maximum acceleration");
  });

  it("treats a comment that is only a conversion as a hint", () => {
    const parsed = parseFieldComment(" ~2.9 deg/s");
    expect(parsed.description).toBe("");
    expect(parsed.hint).toBe("~2.9 deg/s");
  });

  it("recognises degrees and knots and does not confuse words that contain unit letters", () => {
    expect(parseFieldComment("Bearing (degrees)").unit).toBe("degrees");
    expect(parseFieldComment("Speed in knots").unit).toBe("knots");
    expect(parseFieldComment("Minimum radius of the known obstacle").unit).toBeNull();
    expect(parseFieldComment("Minimum persistence").unit).toBeNull();
  });

  it("handles no comment", () => {
    expect(parseFieldComment(undefined)).toMatchObject({ description: "", unit: null, hint: null });
  });
});

describe("unit conversion", () => {
  it("converts radians and degrees both ways", () => {
    expect(toAlternateUnit("radians", Math.PI)).toBeCloseTo(180, 10);
    expect(fromAlternateUnit("radians", 30)).toBe(0.5235987755982988);
    expect(alternateUnit("radians")?.symbol).toBe("deg");
    expect(fromAlternateUnit("radians", toAlternateUnit("radians", 0.123456))).toBeCloseTo(0.123456, 12);
  });

  it("converts m/s and knots both ways", () => {
    expect(toAlternateUnit("m/s", 25.722235)).toBeCloseTo(50, 3);
    expect(fromAlternateUnit("m/s", 50)).toBeCloseTo(25.7222222, 5);
    expect(toAlternateUnit("knots", 1)).toBeCloseTo(0.514444, 5);
  });

  it("converts rad/s and deg/s, seconds and minutes", () => {
    expect(toAlternateUnit("rad/s", 0.03)).toBeCloseTo(1.7188, 3);
    expect(toAlternateUnit("seconds", 1200)).toBe(20);
    expect(fromAlternateUnit("seconds", 20)).toBe(1200);
    expect(toAlternateUnit("minutes", 2)).toBe(120);
  });

  it("has no alternate for meters", () => {
    expect(alternateUnit("meters")).toBeNull();
    expect(toAlternateUnit("meters", 12)).toBe(12);
  });
});

describe("formatDisplayNumber", () => {
  it("rounds away floating point noise", () => {
    expect(formatDisplayNumber(29.999999999999996)).toBe("30");
    expect(formatDisplayNumber(1.7188733853924696)).toBe("1.718873385");
    expect(formatDisplayNumber(0)).toBe("0");
    expect(formatDisplayNumber(0.0000001234)).toBe("1.234e-7");
  });

  it("takes fewer significant digits for a converted value", () => {
    expect(formatDisplayNumber(50.00002484, 6)).toBe("50");
    expect(formatDisplayNumber(1.7188733853924696, 6)).toBe("1.71887");
    expect(formatDisplayNumber(0.0001396263402, 6)).toBe("0.000139626");
    expect(formatDisplayNumber(14.66522786, 6)).toBe("14.6652");
  });
});
