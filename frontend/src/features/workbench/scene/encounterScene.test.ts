import { describe, expect, it } from "vitest";
import { frameAt, threeVesselFrames } from "../../encounter/fixtures/recordedFrames";
import {
  buildActorTracks,
  cpaMarks,
  pastSampleCount,
  placeLabels,
  splitTrack,
  thinPoints,
  vectorTickMinutes,
} from "./encounterScene";
import { parseFrame } from "../../../domain/simulation/protocol";
import { CPA_POSITIONS, monitoredFrame } from "../../../test/fixtures/monitoredFrames";

const frames = threeVesselFrames();

describe("tracks", () => {
  const tracks = buildActorTracks(frames);

  it("collects every actor's positions in time order", () => {
    expect(Object.keys(tracks).sort()).toEqual(["0", "1", "2"]);
    expect(tracks["0"]!.t.length).toBe(frames.length);
    expect(tracks["0"]!.t[1]).toBe(10);
  });

  it("splits the track into past and ahead at the current time, joined at the vessel", () => {
    const track = tracks["0"]!;
    expect(pastSampleCount(track, 95)).toBe(10);
    const current = { x: 1, y: 2 };
    const { past, ahead } = splitTrack(track, 95, current);
    expect(past.length).toBe(11);
    expect(past[past.length - 1]).toBe(current);
    expect(ahead[0]).toBe(current);
    expect(ahead.length).toBe(frames.length - 10 + 1);
  });

  it("uses a planned path from the frame instead of the recorded path ahead", () => {
    const planned = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
    ];
    const { ahead } = splitTrack(tracks["0"]!, 95, { x: 1, y: 2 }, planned);
    expect(ahead).toBe(planned);
  });

  it("thins long tracks but keeps the last point", () => {
    const points = Array.from({ length: 4001 }, (_, i) => ({ x: i, y: 0 }));
    const thinned = thinPoints(points, 1000);
    expect(thinned.length).toBeLessThanOrEqual(1002);
    expect(thinned[thinned.length - 1]!.x).toBe(4000);
  });
});

describe("CPA marks", () => {
  it("marks the encounters ahead, not the pair without one", () => {
    const marks = cpaMarks(frameAt(frames, 100));
    expect(marks.map((m) => m.relationId).sort()).toEqual(["0->1", "0->2"]);
    const crossing = marks.find((m) => m.relationId === "0->1")!;
    expect(crossing.tcpa).toBeCloseTo(350, 0);
    expect(crossing.inside).toBe(true);
  });

  it("adds the selected pair and drops passed pairs", () => {
    expect(cpaMarks(frameAt(frames, 100), { selectedRelationId: "1->2" }).map((m) => m.relationId)).toContain("1->2");
    expect(cpaMarks(frameAt(frames, 500), { allPairs: true }).map((m) => m.relationId)).not.toContain("0->1");
  });

  it("returns nothing without a frame", () => {
    expect(cpaMarks(null)).toEqual([]);
  });
});

describe("vector time marks", () => {
  it("spaces marks by whole minutes, at least a few pixels apart", () => {
    // 8 m/s is 480 m a minute.
    expect(vectorTickMinutes(8, 0.05)).toBe(1);
    expect(vectorTickMinutes(8, 0.005)).toBe(5);
    expect(vectorTickMinutes(0, 1)).toBeNull();
  });
});

describe("label placement", () => {
  it("moves a label that would overlap one placed before", () => {
    const boxes = placeLabels([
      { anchor: { x: 100, y: 100 }, width: 80, height: 30 },
      { anchor: { x: 105, y: 102 }, width: 80, height: 30 },
    ]);
    expect(boxes[0]!.x).toBe(114);
    expect(boxes[1]!.y).toBeGreaterThan(boxes[0]!.y + boxes[0]!.height - 1);
  });

  it("keeps a label inside the bounds when a spot there is free", () => {
    const [box] = placeLabels([{ anchor: { x: 760, y: 20 }, width: 80, height: 30 }], { x: 0, y: 0, width: 800, height: 600 });
    expect(box!.x + box!.width).toBeLessThanOrEqual(800);
    expect(box!.y).toBeGreaterThanOrEqual(0);
  });
});

describe("CPA marks from the monitor", () => {
  it("draws the monitor's CPA positions with its tcpa and dcpa", () => {
    const [mark] = cpaMarks(parseFrame(monitoredFrame({ timestamp: 30, monitorHistory: true })));
    expect(mark).toMatchObject({ relationId: "0->1", pointA: CPA_POSITIONS["0"], pointB: CPA_POSITIONS["1"], tcpa: 30, dcpa: 12.5 });
  });

  it("draws nothing when the monitor reports no CPA ahead", () => {
    expect(cpaMarks(parseFrame(monitoredFrame({ timestamp: 70, monitorHistory: true })), { allPairs: true })).toEqual([]);
  });

  it("computes the CPA from the states on an older frame", () => {
    const frame = parseFrame(monitoredFrame({ timestamp: 30 }));
    const [mark] = cpaMarks(frame);
    expect(mark).toBeDefined();
    expect(mark!.pointA).not.toEqual(CPA_POSITIONS["0"]);
    expect(mark!.tcpa).toBeGreaterThan(0);
  });
});
