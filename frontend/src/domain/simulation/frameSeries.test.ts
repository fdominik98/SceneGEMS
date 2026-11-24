import { describe, expect, it, vi } from "vitest";
import { monitoredFrames } from "../../test/fixtures/monitoredFrames";
import { parseFrames } from "../cluster/framesApi";
import { buildFramesFromTrajectoryData, hasMonitorFrames } from "../sceneGeneration/parseEvaluationDataFile";
import { CARRY_FORWARD, decodeFrameSeries, frameSeriesParser } from "./frameSeries";
import { parseFrame } from "./protocol";

/** A series the way `encode_frames` of the backend writes it (`scenegems_tool/gateway/frame_series.py`). */
function encode(frames: Record<string, unknown>[]): { encoding: string; encoded_frames: Record<string, unknown>[] } {
  const encoded = frames.map((frame, index) =>
    index === 0 ? frame : Object.fromEntries(Object.entries(frame).filter(([key, value]) => JSON.stringify(frames[index - 1][key]) !== JSON.stringify(value)))
  );
  // As an artifact holds it: no object is shared before it is read
  return JSON.parse(JSON.stringify({ encoding: CARRY_FORWARD, encoded_frames: encoded })) as { encoding: string; encoded_frames: Record<string, unknown>[] };
}

/** Six frames of a monitored run; a rule fails from the fourth on, so the rule results change once. */
const FRAMES = monitoredFrames(6, 3);

describe("a series of frames without what repeats", () => {
  it("leaves the vessels and unchanged rule results out of the frames after the first (the encoder of the test)", () => {
    const { encoded_frames: encoded } = encode(FRAMES);
    expect(encoded[0]).toEqual(FRAMES[0]);
    expect(encoded.slice(1).every((frame) => !("actors" in frame) && "timestamp" in frame)).toBe(true);
    expect(encoded.filter((frame) => "ruleResults" in frame)).toHaveLength(2);
  });

  it("is decoded into the frames as they were", () => {
    expect(decodeFrameSeries(encode(FRAMES))).toEqual(FRAMES);
  });

  it("takes a plain list as it is, and nothing else for a series", () => {
    expect(decodeFrameSeries(FRAMES)).toBe(FRAMES);
    expect(decodeFrameSeries([])).toEqual([]);
    expect(decodeFrameSeries(undefined)).toBeNull();
    expect(decodeFrameSeries({ frames: FRAMES })).toBeNull();
    expect(decodeFrameSeries({ encoding: "delta", encoded_frames: [] })).toBeNull();
    expect(decodeFrameSeries({ encoding: CARRY_FORWARD })).toBeNull();
    expect(decodeFrameSeries({ encoding: CARRY_FORWARD, encoded_frames: [FRAMES[0], 5] })).toBeNull();
  });

  it("carries a frame in which nothing changed forward whole", () => {
    const still = { timestamp: 7, actors: [{ id: "0" }] };
    expect(decodeFrameSeries({ encoding: CARRY_FORWARD, encoded_frames: [still, {}, { timestamp: 9 }] })).toEqual([still, still, { ...still, timestamp: 9 }]);
  });
});

describe("the frames artifact of a monitoring job", () => {
  it("parses the same from the series and from the plain list", () => {
    const plain = parseFrames(FRAMES);
    const series = parseFrames(encode(FRAMES));
    expect(series).toEqual(plain);
    expect(series.map((frame) => frame.timestamp)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(series[3].ruleResults).not.toEqual(series[2].ruleResults);
  });

  it("still takes an object with the list under frames, and refuses what is no series", () => {
    expect(parseFrames({ frames: FRAMES })).toEqual(parseFrames(FRAMES));
    expect(() => parseFrames({ encoding: "delta", encoded_frames: FRAMES })).toThrow(/not a list of frames/);
    expect(() => parseFrames({ encoding: CARRY_FORWARD, encoded_frames: [FRAMES[0], { timestamp: "late" }] })).toThrow(/frame 1 timestamp/);
  });

  it("parses a section the series carried forward once and shares it between the frames", () => {
    const series = parseFrames(encode(FRAMES));
    // The vessels never change; the rule results change once, at the fourth frame
    expect(series.every((frame) => frame.actors === series[0].actors)).toBe(true);
    expect(series[1].ruleResults).toBe(series[0].ruleResults);
    expect(series[2].ruleResults).toBe(series[0].ruleResults);
    expect(series[3].ruleResults).not.toBe(series[2].ruleResults);
    expect(series[5].ruleResults).toBe(series[3].ruleResults);
  });

  it("gives a shared section to the parser once per change, and a plain list frame by frame", () => {
    const seen: unknown[] = [];
    const counting = (raw: unknown) => {
      seen.push((raw as { ruleResults: unknown[] }).ruleResults);
      return parseFrame(raw);
    };
    const parse = frameSeriesParser(counting);
    const decoded = decodeFrameSeries(encode(FRAMES)) as unknown[];
    const frames = decoded.map((frame) => parse(frame));
    // Two frames carry rule results of their own; the others were parsed with an empty list in their place
    expect(seen.filter((rules) => Array.isArray(rules) && rules.length > 0)).toHaveLength(2);
    expect(frames).toEqual(FRAMES.map((frame) => parseFrame(frame)));

    const whole = vi.fn(parseFrame);
    const plain = frameSeriesParser(whole);
    FRAMES.forEach((frame) => plain(frame));
    expect(whole.mock.calls.every(([raw]) => (raw as { ruleResults: unknown[] }).ruleResults.length > 0)).toBe(true);
  });
});

describe("the monitor frames of planned trajectories", () => {
  const scene = (y: number) => ({
    _data: [
      [
        { id: 0, type: "OSPassengerShip", length: 30, breadth: 10.5, height: 4.5, draft: 1.8, mass: 346612, safety_radius: 120, _is_os: true, is_vessel: true },
        { x: 0, y, speed: 14.6, heading: 1.57 },
      ],
    ],
  });
  const monitor = FRAMES.map((frame) => ({ ruleResults: frame.ruleResults, situationContexts: frame.situationContexts, colregsStates: frame.colregsStates, maneuverStates: frame.maneuverStates, metrics: frame.metrics }));
  const trajectories = { scene_list: FRAMES.map((_, index) => scene(index * 10)), time_step: 5 };

  it("give the same frames from the series as from the list, one per scene", () => {
    const plain = buildFramesFromTrajectoryData({ trajectories, monitor_frames: monitor });
    const series = buildFramesFromTrajectoryData({ trajectories, monitor_frames: encode(monitor) });
    expect(series).toEqual(plain);
    expect(series.map((frame) => frame.timestamp)).toEqual([0, 5, 10, 15, 20, 25]);
    expect(series[4].ruleResults).toEqual(plain[4].ruleResults);
    expect(series[4].ruleResults.length).toBeGreaterThan(0);
  });

  it("judge the plan already in either form, when there is one for every scene", () => {
    expect(hasMonitorFrames({ trajectories, monitor_frames: encode(monitor) })).toBe(true);
    expect(hasMonitorFrames({ trajectories, monitor_frames: monitor })).toBe(true);
    expect(hasMonitorFrames({ trajectories, monitor_frames: encode(monitor.slice(0, 3)) })).toBe(false);
    expect(hasMonitorFrames({ trajectories, monitor_frames: { encoding: "delta", encoded_frames: monitor } })).toBe(false);
  });

  it("leave a plan without them unmonitored", () => {
    const frames = buildFramesFromTrajectoryData({ trajectories });
    expect(frames).toHaveLength(6);
    expect(frames.every((frame) => frame.ruleResults.length === 0)).toBe(true);
  });
});
