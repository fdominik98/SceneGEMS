import type { SimulationFrame } from "../../../domain/simulation/types";
import { frameRelations, isEncounter } from "../monitor/encounterPairs";
import { computeCpa, type Point } from "./encounterGeometry";

/** One actor's positions over the buffered frames, sorted by time. */
export interface ActorTrack {
  t: number[];
  points: Point[];
}

/** Positions of every actor across `frames` (sorted by timestamp). */
export function buildActorTracks(frames: SimulationFrame[]): Record<string, ActorTrack> {
  const tracks: Record<string, ActorTrack> = {};
  for (const frame of frames) {
    for (const [actorId, state] of Object.entries(frame.statesByActorId)) {
      const track = (tracks[actorId] ??= { t: [], points: [] });
      track.t.push(frame.timestamp);
      track.points.push({ x: state.x, y: state.y });
    }
  }
  return tracks;
}

const trackCache = new WeakMap<SimulationFrame[], Record<string, ActorTrack>>();

/** `buildActorTracks`, computed once per frame array (playback re-renders reuse it). */
export function actorTracksFor(frames: SimulationFrame[]): Record<string, ActorTrack> {
  let tracks = trackCache.get(frames);
  if (!tracks) {
    tracks = buildActorTracks(frames);
    trackCache.set(frames, tracks);
  }
  return tracks;
}

/** Number of track samples at or before `t` (the past part of the track). */
export function pastSampleCount(track: ActorTrack, t: number): number {
  let lo = 0;
  let hi = track.t.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (track.t[mid]! <= t) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo;
}

/**
 * The past track up to `t` and the path ahead of it, each joined at the current position so
 * the two lines meet. A planned path the frame carries (`trajectoriesByActorId`) replaces
 * the path ahead.
 */
export function splitTrack(
  track: ActorTrack | undefined,
  t: number,
  current: Point | null,
  planned?: Point[]
): { past: Point[]; ahead: Point[] } {
  const samples = track ? pastSampleCount(track, t) : 0;
  const past = track ? track.points.slice(0, samples) : [];
  const hasPlan = Boolean(planned && planned.length >= 2);
  let ahead = hasPlan ? planned! : track ? track.points.slice(samples) : [];
  if (current) {
    past.push(current);
    if (!hasPlan) {
      ahead = [current, ...ahead];
    }
  }
  return { past: past.length >= 2 ? past : [], ahead: ahead.length >= 2 ? ahead : [] };
}

/** Every n-th point, keeping the last, so long tracks stay cheap to draw. */
export function thinPoints(points: Point[], maxPoints = 1500): Point[] {
  if (points.length <= maxPoints) {
    return points;
  }
  const step = Math.ceil(points.length / maxPoints);
  const out: Point[] = [];
  for (let i = 0; i < points.length; i += step) {
    out.push(points[i]!);
  }
  if (out[out.length - 1] !== points[points.length - 1]) {
    out.push(points[points.length - 1]!);
  }
  return out;
}

export function polylinePoints(points: Point[]): string {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

export interface CpaMark {
  relationId: string;
  aId: string;
  bId: string;
  pointA: Point;
  pointB: Point;
  tcpa: number;
  dcpa: number;
  /** The CPA lies inside the pair's safety distance. */
  inside: boolean;
  /** The monitor reports a collision course. */
  collisionCourse: boolean;
}

/** CPA marks further ahead than this are left out. */
export const CPA_HORIZON_S = 3600;

export interface MonitorCpa {
  pointA: Point;
  pointB: Point;
  tcpa: number | null;
  dcpa: number;
}

/**
 * The pair's CPA as the monitor computed it: both positions at its tcpa. Null when the
 * monitor reports no CPA ahead (no relative motion, or already behind); undefined when the
 * frame predates the monitor's CPA positions.
 */
export function monitorCpa(
  frame: SimulationFrame,
  relationId: string,
  actor1Id: string,
  actor2Id: string
): MonitorCpa | null | undefined {
  const raw = frame.metrics?.relations?.[relationId];
  if (!raw || !("cpaPositionsByActorId" in raw)) {
    return undefined;
  }
  const positions = frame.metrics?.cpaPositionsByRelationId?.[relationId];
  const pointA = positions?.[actor1Id];
  const pointB = positions?.[actor2Id];
  if (!pointA || !pointB) {
    return null;
  }
  return {
    pointA,
    pointB,
    tcpa: typeof raw.tcpa === "number" ? raw.tcpa : null,
    dcpa: typeof raw.dcpa === "number" ? raw.dcpa : Math.hypot(pointB.x - pointA.x, pointB.y - pointA.y),
  };
}

/**
 * Where each approaching pair will be closest: the monitor's CPA positions when the frame has
 * them, else computed from the states held on course and speed. Drawn for pairs in an encounter, pairs on a collision course and the selected pair (or for
 * every approaching pair with `allPairs`), when the CPA lies within the horizon.
 */
export function cpaMarks(
  frame: SimulationFrame | null,
  options: { selectedRelationId?: string | null; allPairs?: boolean } = {}
): CpaMark[] {
  if (!frame) {
    return [];
  }
  const marks: CpaMark[] = [];
  for (const relation of frameRelations(frame)) {
    const a = frame.statesByActorId[relation.actor1Id];
    const b = frame.statesByActorId[relation.actor2Id];
    if (!a || !b) {
      continue;
    }
    const context = frame.situationContexts.find((c) => c.relationId === relation.relationId);
    const colregs = frame.colregsStates.find((s) => s.relationId === relation.relationId);
    const collisionCourse = Boolean(colregs?.actorsOnCollisionCourse);
    const wanted =
      options.allPairs ||
      relation.relationId === options.selectedRelationId ||
      isEncounter(context?.situationType) ||
      collisionCourse;
    if (!wanted) {
      continue;
    }
    const fromMonitor = monitorCpa(frame, relation.relationId, relation.actor1Id, relation.actor2Id);
    if (fromMonitor === null) {
      continue;
    }
    const cpa = fromMonitor ?? computeCpa(a, b);
    if (cpa.tcpa === null || cpa.tcpa <= 0 || cpa.tcpa > CPA_HORIZON_S || !cpa.pointA || !cpa.pointB) {
      continue;
    }
    const safety = frame.metrics?.relations?.[relation.relationId]?.safetyDistance;
    marks.push({
      relationId: relation.relationId,
      aId: relation.actor1Id,
      bId: relation.actor2Id,
      pointA: cpa.pointA,
      pointB: cpa.pointB,
      tcpa: cpa.tcpa,
      dcpa: cpa.dcpa,
      inside: typeof safety === "number" && cpa.dcpa < safety,
      collisionCourse,
    });
  }
  return marks;
}

/** Minutes between the time marks of a vector, so marks stay at least `minPixels` apart. */
export function vectorTickMinutes(speed: number, pixelsPerMeter: number, minPixels = 6): number | null {
  const perMinute = speed * 60 * pixelsPerMeter;
  for (const minutes of [1, 2, 5, 10, 30]) {
    if (perMinute * minutes >= minPixels) {
      return minutes;
    }
  }
  return null;
}

export interface LabelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

function overlaps(a: LabelBox, b: LabelBox): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function inside(box: LabelBox, bounds: LabelBox): boolean {
  return (
    box.x >= bounds.x &&
    box.y >= bounds.y &&
    box.x + box.width <= bounds.x + bounds.width &&
    box.y + box.height <= bounds.y + bounds.height
  );
}

/**
 * Places each label beside its anchor, trying right-above, right-below, left-above and
 * left-below: the first spot inside `bounds` that overlaps no label placed before, else the
 * first free spot, else the first spot.
 */
export function placeLabels(
  items: { anchor: Point; width: number; height: number }[],
  bounds?: LabelBox,
  gap = 14
): LabelBox[] {
  const placed: LabelBox[] = [];
  for (const item of items) {
    const { anchor, width, height } = item;
    const candidates: LabelBox[] = [
      { x: anchor.x + gap, y: anchor.y - height - 4, width, height },
      { x: anchor.x + gap, y: anchor.y + 6, width, height },
      { x: anchor.x - gap - width, y: anchor.y - height - 4, width, height },
      { x: anchor.x - gap - width, y: anchor.y + 6, width, height },
    ];
    const free = candidates.filter((candidate) => placed.every((other) => !overlaps(candidate, other)));
    const best = (bounds ? free.find((candidate) => inside(candidate, bounds)) : undefined) ?? free[0] ?? candidates[0]!;
    placed.push(best);
  }
  return placed;
}
