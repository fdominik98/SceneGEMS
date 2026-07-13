import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { buildTrajectoryPathsByActor } from "./buildTrajectoryPaths";

describe("buildTrajectoryPathsByActor", () => {
  it("stitches positions from buffered frames when server trajectory is absent", () => {
    const paths = buildTrajectoryPathsByActor([sampleFrames[0], sampleFrames[1]], sampleFrames[1]);
    expect(paths.own_ship?.length).toBeGreaterThanOrEqual(2);
    expect(paths.target_1?.length).toBeGreaterThanOrEqual(2);
  });

  it("prefers server trajectory when it has at least two points", () => {
    const customPath = [
      { x: 0, y: 0, speed: 0, heading: 0 },
      { x: 100, y: 0, speed: 0, heading: 0 },
      { x: 200, y: 0, speed: 0, heading: 0 },
    ];
    const frame = {
      ...sampleFrames[5],
      trajectoriesByActorId: { own_ship: customPath },
    };
    const paths = buildTrajectoryPathsByActor([frame], frame);
    expect(paths.own_ship).toEqual(customPath);
  });
});
