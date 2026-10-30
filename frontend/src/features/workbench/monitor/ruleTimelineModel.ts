import type {
  RuleEvaluation,
  RuleKind,
  RuleResult,
  SimulationFrame,
} from "../../../domain/simulation/types";

/** A value held from `start` (inclusive) to `end` (exclusive), in scenario seconds. */
export interface TimelineSegment<T> {
  start: number;
  end: number;
  value: T;
}

export interface EncounterTypeValue {
  type: string;
  label: string;
}

export interface RuleTrack {
  /** Stable identity across frames: the monitor's rule id, else rule name plus subject vessel. */
  key: string;
  ruleName: string;
  title: string;
  ruleNumber: string;
  kind: RuleKind;
  subjectActorId: string | null;
  subjectActorName: string;
  segments: TimelineSegment<RuleResult>[];
  /**
   * First time the rule was FAILED over the whole run, or null: the monitor's `firstFailedAt`
   * when the frames carry it (right even when frames were missed or thinned), else the first
   * frame showing it FAILED.
   */
  firstFailure: number | null;
}

export interface PairTrack {
  relationId: string;
  actor1Id: string;
  actor2Id: string;
  encounter: TimelineSegment<EncounterTypeValue>[];
  rules: RuleTrack[];
}

export interface RuleTimelineModel {
  start: number;
  end: number;
  pairs: PairTrack[];
}

/** A rule's identity within its relation: the monitor's `ruleId`, or on older frames its name and subject vessel. */
export function ruleKey(evaluation: Pick<RuleEvaluation, "ruleName" | "subjectActorId" | "ruleId">): string {
  return evaluation.ruleId ?? `${evaluation.ruleName}#${evaluation.subjectActorId ?? ""}`;
}

/** The earlier of two failure times, either of which may be missing. */
function earlier(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.min(a, b);
}

/** Short tag of a rule: "R16", or "Tip" for an advisory suggestion. */
export function ruleTag(rule: Pick<RuleEvaluation, "kind" | "ruleNumber">): string {
  return rule.kind === "suggestion" ? "Tip" : `R${rule.ruleNumber || "?"}`;
}

/** Rules before suggestions, then by rule number, then subject, then name. */
export function compareRules(
  a: Pick<RuleTrack, "kind" | "ruleNumber" | "subjectActorName" | "ruleName">,
  b: Pick<RuleTrack, "kind" | "ruleNumber" | "subjectActorName" | "ruleName">
): number {
  if (a.kind !== b.kind) {
    return a.kind === "rule" ? -1 : 1;
  }
  const byNumber = a.ruleNumber.localeCompare(b.ruleNumber, undefined, { numeric: true });
  if (byNumber !== 0) {
    return byNumber;
  }
  const bySubject = a.subjectActorName.localeCompare(b.subjectActorName);
  return bySubject !== 0 ? bySubject : a.ruleName.localeCompare(b.ruleName);
}

/** Relations ordered so pairs with the own ship come first, then by id. */
export function compareRelations(ownShipId: string | null) {
  return (a: { relationId: string; actor1Id: string; actor2Id: string }, b: typeof a) => {
    const aOwn = ownShipId !== null && (a.actor1Id === ownShipId || a.actor2Id === ownShipId);
    const bOwn = ownShipId !== null && (b.actor1Id === ownShipId || b.actor2Id === ownShipId);
    if (aOwn !== bOwn) {
      return aOwn ? -1 : 1;
    }
    return a.relationId.localeCompare(b.relationId, undefined, { numeric: true });
  };
}

function pushValue<T>(
  segments: TimelineSegment<T>[],
  start: number,
  end: number,
  value: T,
  same: (a: T, b: T) => boolean
) {
  const last = segments[segments.length - 1];
  if (last && last.end === start && same(last.value, value)) {
    last.end = end;
    return;
  }
  segments.push({ start, end, value });
}

/**
 * Per pair and rule, the rule's result over the run as segments (consecutive frames with
 * the same result joined), plus the encounter type over time. A frame's value holds until
 * the next frame; the last frame holds for one time step. A rule absent from a frame leaves
 * a gap. `frames` must be sorted by timestamp.
 */
export function buildRuleTimeline(
  frames: SimulationFrame[],
  timeStep?: number | null
): RuleTimelineModel {
  if (frames.length === 0) {
    return { start: 0, end: 0, pairs: [] };
  }
  const pairs = new Map<string, PairTrack>();
  const rulesByPair = new Map<string, Map<string, RuleTrack>>();
  const pairFor = (relationId: string, actor1Id?: string, actor2Id?: string): PairTrack => {
    let pair = pairs.get(relationId);
    if (!pair) {
      const [first, second] = relationId.split("->");
      pair = {
        relationId,
        actor1Id: actor1Id ?? first ?? relationId,
        actor2Id: actor2Id ?? second ?? relationId,
        encounter: [],
        rules: [],
      };
      pairs.set(relationId, pair);
      rulesByPair.set(relationId, new Map());
    }
    return pair;
  };

  for (let index = 0; index < frames.length; index += 1) {
    const frame = frames[index]!;
    const next = frames[index + 1];
    const step = timeStep ?? frame.timeStep ?? 1;
    const start = frame.timestamp;
    const end = next ? next.timestamp : start + step;

    for (const context of frame.situationContexts) {
      const pair = pairFor(context.relationId, context.actor1Id, context.actor2Id);
      pushValue(
        pair.encounter,
        start,
        end,
        { type: context.situationType, label: context.situationLabel || context.situationType },
        (a, b) => a.type === b.type
      );
    }

    for (const result of frame.ruleResults) {
      const pair = pairFor(result.relationId);
      const tracks = rulesByPair.get(result.relationId)!;
      for (const evaluation of result.evaluations) {
        const key = ruleKey(evaluation);
        let track = tracks.get(key);
        if (!track) {
          track = {
            key,
            ruleName: evaluation.ruleName,
            title: evaluation.title || evaluation.ruleName,
            ruleNumber: evaluation.ruleNumber,
            kind: evaluation.kind,
            subjectActorId: evaluation.subjectActorId,
            subjectActorName: evaluation.subjectActorName,
            segments: [],
            firstFailure: null,
          };
          tracks.set(key, track);
          pair.rules.push(track);
        }
        pushValue(track.segments, start, end, evaluation.result, (a, b) => a === b);
        if (typeof evaluation.firstFailedAt === "number") {
          track.firstFailure = earlier(track.firstFailure, evaluation.firstFailedAt);
        } else if (evaluation.result === "FAILED") {
          track.firstFailure = earlier(track.firstFailure, start);
        }
      }
    }
  }

  const ownShipId = frames[0]!.actors.find((actor) => actor.isOwnShip)?.id ?? null;
  const ordered = [...pairs.values()].sort(compareRelations(ownShipId));
  for (const pair of ordered) {
    pair.rules.sort(compareRules);
  }
  const last = frames[frames.length - 1]!;
  return {
    start: frames[0]!.timestamp,
    end: last.timestamp + (timeStep ?? last.timeStep ?? 1),
    pairs: ordered,
  };
}

/** The segment's value at time `t`, or null in a gap. */
export function valueAt<T>(segments: TimelineSegment<T>[], t: number): T | null {
  let lo = 0;
  let hi = segments.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const segment = segments[mid]!;
    if (t < segment.start) {
      hi = mid - 1;
    } else if (t >= segment.end) {
      lo = mid + 1;
    } else {
      return segment.value;
    }
  }
  return null;
}

/** First failure of a rule at or before `t`, or null when it has not failed yet. */
export function firstFailureAtOrBefore(track: RuleTrack | undefined, t: number): number | null {
  if (!track || track.firstFailure === null) {
    return null;
  }
  return track.firstFailure <= t ? track.firstFailure : null;
}

/** Worst result over a pair's rules in each time slice (FAILED over UNKNOWN over PASSED). */
export function pairSummarySegments(pair: PairTrack, includeSuggestions = false): TimelineSegment<RuleResult>[] {
  const rank: Record<RuleResult, number> = { FAILED: 0, UNKNOWN: 1, PASSED: 2 };
  const tracks = pair.rules.filter((rule) => includeSuggestions || rule.kind === "rule");
  const cuts = new Set<number>();
  for (const track of tracks) {
    for (const segment of track.segments) {
      cuts.add(segment.start);
      cuts.add(segment.end);
    }
  }
  const times = [...cuts].sort((a, b) => a - b);
  const out: TimelineSegment<RuleResult>[] = [];
  for (let i = 0; i < times.length - 1; i += 1) {
    const start = times[i]!;
    const end = times[i + 1]!;
    let worst: RuleResult | null = null;
    for (const track of tracks) {
      const value = valueAt(track.segments, start);
      if (value !== null && (worst === null || rank[value] < rank[worst])) {
        worst = value;
      }
    }
    if (worst !== null) {
      pushValue(out, start, end, worst, (a, b) => a === b);
    }
  }
  return out;
}

const TIME_STEPS_S = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];

/** Round spacing of time axis ticks: the smallest step giving at most `maxTicks` ticks over `span` seconds. */
export function niceTimeStep(span: number, maxTicks = 8): number {
  return TIME_STEPS_S.find((step) => span / step <= maxTicks) ?? TIME_STEPS_S[TIME_STEPS_S.length - 1]!;
}
