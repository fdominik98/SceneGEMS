import { parseFrame } from "./protocol";
import type { SimulationFrame } from "./types";

/**
 * A series of monitored frames as the backend writes it (`scenegems_tool/gateway/frame_series.py`,
 * which this module must agree with): the plain list of its frames, or
 *
 *     {"encoding": "carry_forward", "encoded_frames": [first frame, {changed sections}, ...]}
 *
 * where every frame after the first leaves out the sections (actors, ruleResults, ...) that equal
 * the previous frame's. Most of a long series repeats: of the 59 MB of a run of 1600 scenes with
 * three vessels, 44 MB are rule results that change in a few frames. Two things come this way: the
 * frames artifact of a monitoring job and the `monitor_frames` of planned trajectories. A series
 * written before the encoding is a plain list, which reads the same.
 */

export const CARRY_FORWARD = "carry_forward";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The frames of a series as they were before it was written: a plain list as it is, a
 * carry_forward series with every section carried forward again. Null for anything else. Frames
 * that share a section share the object, which `frameSeriesParser` makes use of.
 */
export function decodeFrameSeries(value: unknown): unknown[] | null {
  if (Array.isArray(value)) {
    return value;
  }
  if (!isRecord(value) || value.encoding !== CARRY_FORWARD || !Array.isArray(value.encoded_frames)) {
    return null;
  }
  const frames: Record<string, unknown>[] = [];
  let carried: Record<string, unknown> = {};
  for (const changed of value.encoded_frames) {
    if (!isRecord(changed)) {
      return null;
    }
    carried = { ...carried, ...changed };
    frames.push(carried);
  }
  return frames;
}

/**
 * The sections that repeat from frame to frame and that `parseFrame` reads on their own, without
 * looking at another section: parsed once, their result serves every frame that carries the same
 * object. `empty` is what the frame is parsed with in their place.
 */
const SHARED_SECTIONS: readonly { key: "actors" | "ruleResults"; empty: unknown }[] = [
  { key: "actors", empty: [] },
  { key: "ruleResults", empty: [] },
];

/**
 * A parser for the frames of one series, in order. It gives what `parseFrame` gives, and parses a
 * section that is the same object as in the frame before only once: the rule results of a run are
 * most of its bytes and nearly always the previous frame's, so reading a decoded series costs a
 * fraction of the time and the memory of reading every frame whole. Frames of a plain list share
 * no objects and are parsed whole.
 */
export function frameSeriesParser(parse: (raw: unknown) => SimulationFrame = parseFrame): (raw: unknown) => SimulationFrame {
  let previousRaw: Record<string, unknown> | null = null;
  let previous: SimulationFrame | null = null;
  return (raw) => {
    if (!isRecord(raw)) {
      previousRaw = null;
      previous = null;
      return parse(raw);
    }
    const before = previousRaw;
    const parsedBefore = previous;
    const shared = before === null || parsedBefore === null ? [] : SHARED_SECTIONS.filter(({ key }) => typeof raw[key] === "object" && raw[key] !== null && raw[key] === before[key]);
    let frame: SimulationFrame;
    if (shared.length === 0 || parsedBefore === null) {
      frame = parse(raw);
    } else {
      const light = { ...raw };
      for (const { key, empty } of shared) {
        light[key] = empty;
      }
      frame = parse(light);
      for (const { key } of shared) {
        if (key === "actors") {
          frame.actors = parsedBefore.actors;
        } else {
          frame.ruleResults = parsedBefore.ruleResults;
        }
      }
    }
    previousRaw = raw;
    previous = frame;
    return frame;
  };
}
