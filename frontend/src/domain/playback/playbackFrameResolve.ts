import type { SimulationFrame } from "../simulation/types";

/** Largest buffered timestamp that is still <= simulation time t (requires frames sorted by timestamp). */
export function timestampAtOrBefore(frames: SimulationFrame[], t: number): number {
  if (frames.length === 0) {
    return 0;
  }
  const first = frames[0]!.timestamp;
  if (t <= first) {
    return first;
  }
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (frames[mid]!.timestamp <= t) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return frames[lo]!.timestamp;
}

/** Frames with timestamp at or before the playback cursor (requires frames sorted by timestamp). */
export function framesAtOrBeforeCursor(
  frames: SimulationFrame[],
  cursor: number
): SimulationFrame[] {
  if (frames.length === 0) {
    return [];
  }
  const cutoff = timestampAtOrBefore(frames, cursor);
  return frames.filter((frame) => frame.timestamp <= cutoff);
}
