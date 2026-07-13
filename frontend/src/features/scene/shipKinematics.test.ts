import { describe, expect, it } from "vitest";
import { getRenderHeading } from "./shipKinematics";

describe("getRenderHeading", () => {
  it("uses heading directly when speed is zero", () => {
    const heading = Math.PI / 4;
    expect(getRenderHeading({ x: 0, y: 0, speed: 0, heading })).toBeCloseTo(heading);
  });

  it("keeps velocity-based orientation when speed is negative", () => {
    const heading = Math.PI / 4;
    expect(getRenderHeading({ x: 0, y: 0, speed: -2, heading })).toBeCloseTo(
      heading - Math.PI
    );
  });
});
