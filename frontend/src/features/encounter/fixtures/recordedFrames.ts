/**
 * Recorded monitor frames for tests and the screenshot harness (never imported by the app).
 *
 * Both come from closed-loop kinematic runs (the own ship under USV Navigation, the targets
 * replaying straight tracks), monitored with `general_maritime_constants.yaml` and written
 * by the gateway's `serialize_monitored_frame`, one frame every 10 s up to 720 s:
 * - two vessels: os northbound, ts1 (60 m) westbound from its starboard bow, a crossing
 *   where os gives way (Rule 16 fails at 70 s, os turns at about 170 s);
 * - three vessels: the same plus ts2 (45 m) southbound ahead, a head-on with os, and
 *   ts1 and ts2 in no encounter.
 */
import { parseFrame } from "../../../domain/simulation/protocol";
import type { SimulationFrame } from "../../../domain/simulation/types";
import threeVessel from "./threeVessel.json";
import twoVesselCrossing from "./twoVesselCrossing.json";

function parseAll(raw: { frames: unknown[] }): SimulationFrame[] {
  return raw.frames.map((frame) => parseFrame(frame));
}

export function twoVesselFrames(): SimulationFrame[] {
  return parseAll(twoVesselCrossing);
}

export function threeVesselFrames(): SimulationFrame[] {
  return parseAll(threeVessel);
}

export function frameAt(frames: SimulationFrame[], timestamp: number): SimulationFrame {
  const frame = frames.find((f) => f.timestamp === timestamp);
  if (!frame) {
    throw new Error(`no recorded frame at ${timestamp} s`);
  }
  return frame;
}
