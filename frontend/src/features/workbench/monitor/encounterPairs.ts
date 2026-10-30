import type {
  ColregsMonitorStateData,
  ManeuverStateData,
  RuleKind,
  RuleResult,
  RuleResultData,
  SimulationFrame,
  SituationContextData,
} from "../../../domain/simulation/types";
import {
  bearingSector,
  computeCpa,
  courseDeg,
  rangeBetween,
  relativeBearingDeg,
  trueBearingDeg,
  type BearingSector,
} from "../scene/encounterGeometry";
import {
  compareRelations,
  compareRules,
  firstFailureAtOrBefore,
  ruleKey,
  ruleTag,
  type RuleTimelineModel,
} from "./ruleTimelineModel";

export type VesselRole = "give-way" | "stand-on";

/** Short code of an encounter type for canvas labels; the legend spells them out. */
export function encounterAbbreviation(situationType: string): string {
  const type = situationType.toUpperCase();
  if (type === "HEAD_ON") return "HO";
  if (type.startsWith("TWO_WAY_CROSSING")) return "TW";
  if (type.startsWith("CROSSING")) return "CR";
  if (type.startsWith("OVERTAKING")) return "OT";
  if (type === "OTHER") return "";
  return type
    .split("_")
    .map((word) => word.charAt(0))
    .join("");
}

export function isEncounter(situationType: string | undefined): boolean {
  return Boolean(situationType) && situationType!.toUpperCase() !== "OTHER";
}

/** Give-way or stand-on of each vessel of a monitored encounter; none outside one. */
export function roleOf(context: SituationContextData | undefined, actorId: string): VesselRole | null {
  if (!context || !isEncounter(context.situationType)) {
    return null;
  }
  const giveWay = context.isGiveWayByActorId[actorId];
  if (giveWay === undefined) {
    return null;
  }
  return giveWay ? "give-way" : "stand-on";
}

export interface PairVessel {
  id: string;
  name: string;
  isOwnShip: boolean;
  role: VesselRole | null;
  /** Side the rules judge the vessel against (RIGHT, LEFT, FORWARD...). */
  avoidance: string | null;
  courseDeg: number | null;
  speed: number | null;
  /** True bearing of the other vessel from this one. */
  bearingToOther: number | null;
  /** Bearing of the other vessel relative to this vessel's bow. */
  relativeBearingToOther: number | null;
  sectorOfOther: BearingSector | null;
  maneuver: ManeuverStateData | null;
}

export interface PairRule {
  key: string;
  tag: string;
  title: string;
  ruleName: string;
  ruleNumber: string;
  description: string;
  kind: RuleKind;
  subjectActorId: string | null;
  subjectActorName: string;
  result: RuleResult;
  /** First FAILED at or before the current time. */
  firstFailure: number | null;
}

export type PairSeverity = "fail" | "risk" | "ok" | "none";

export interface PairModel {
  relationId: string;
  /** The own ship when it is part of the pair, else the relation's first vessel. */
  a: PairVessel;
  b: PairVessel;
  situationType: string;
  encounterLabel: string;
  encounterActive: boolean;
  /** Last encounter type before now, for a pair whose encounter has ended. */
  previousEncounterLabel: string | null;
  since: number | null;
  range: number | null;
  dcpa: number | null;
  /** Seconds to CPA; null when the range does not change; negative once passed. */
  tcpa: number | null;
  cpaSource: "monitor" | "computed" | null;
  safetyDistance: number | null;
  visibilityDistance: number | null;
  colregs: ColregsMonitorStateData | null;
  context: SituationContextData | null;
  rules: PairRule[];
  overallStatus: RuleResultData["overallStatus"] | null;
  failedRuleCount: number;
  severity: PairSeverity;
}

function relationMetric(frame: SimulationFrame, relationId: string, key: string): number | null {
  const metrics = frame.metrics;
  if (!metrics) {
    return null;
  }
  const raw = metrics.relations?.[relationId]?.[key];
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw;
  }
  const byRelation =
    key === "distance"
      ? metrics.distanceByRelationId
      : key === "dcpa"
        ? metrics.dcpaByRelationId
        : key === "tcpa"
          ? metrics.tcpaByRelationId
          : undefined;
  const value = byRelation?.[relationId];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function maneuverFor(frame: SimulationFrame, actorId: string, relationId: string): ManeuverStateData | null {
  const own = frame.maneuverStates.filter((state) => state.actorId === actorId);
  return own.find((state) => state.relationId === relationId) ?? own[0] ?? null;
}

interface RelationRef {
  relationId: string;
  actor1Id: string;
  actor2Id: string;
}

/** Every relation the frame mentions, in display order (own ship pairs first). */
export function frameRelations(frame: SimulationFrame): RelationRef[] {
  const byId = new Map<string, RelationRef>();
  const add = (relationId: string, actor1Id?: string, actor2Id?: string) => {
    if (byId.has(relationId)) {
      return;
    }
    const [first, second] = relationId.split("->");
    if (!first || !second || first === second) {
      return;
    }
    byId.set(relationId, { relationId, actor1Id: actor1Id ?? first, actor2Id: actor2Id ?? second });
  };
  frame.situationContexts.forEach((c) => add(c.relationId, c.actor1Id, c.actor2Id));
  frame.ruleResults.forEach((r) => add(r.relationId));
  frame.colregsStates.forEach((s) => add(s.relationId));
  const ownShipId = frame.actors.find((actor) => actor.isOwnShip)?.id ?? null;
  return [...byId.values()].sort(compareRelations(ownShipId));
}

/**
 * One model per vessel pair of the frame for the pair cards: the encounter type and roles
 * from the situation contexts, range, CPA and TCPA from the monitor's metrics (computed
 * from the states when the frame has none), bearings computed from the states, the rules'
 * results with their first failure from the timeline.
 */
export function buildPairModels(
  frame: SimulationFrame | null,
  timeline: RuleTimelineModel | null,
  currentTime?: number
): PairModel[] {
  if (!frame) {
    return [];
  }
  const now = currentTime ?? frame.timestamp;
  const actorsById = new Map(frame.actors.map((actor) => [actor.id, actor]));
  const ownShipId = frame.actors.find((actor) => actor.isOwnShip)?.id ?? null;

  return frameRelations(frame).map((relation) => {
    const { relationId } = relation;
    const context = frame.situationContexts.find((c) => c.relationId === relationId) ?? null;
    const colregs = frame.colregsStates.find((s) => s.relationId === relationId) ?? null;
    const ruleResult = frame.ruleResults.find((r) => r.relationId === relationId) ?? null;
    const pairTrack = timeline?.pairs.find((p) => p.relationId === relationId);

    const swap = ownShipId !== null && relation.actor2Id === ownShipId;
    const aId = swap ? relation.actor2Id : relation.actor1Id;
    const bId = swap ? relation.actor1Id : relation.actor2Id;
    const stateA = frame.statesByActorId[aId];
    const stateB = frame.statesByActorId[bId];

    const vessel = (id: string, other: typeof stateA, self: typeof stateA): PairVessel => {
      const actor = actorsById.get(id);
      const relative = self && other ? relativeBearingDeg(self, other) : null;
      return {
        id,
        name: actor?.name ?? id,
        isOwnShip: actor?.isOwnShip ?? false,
        role: roleOf(context ?? undefined, id),
        avoidance:
          context?.effectiveAvoidanceDirectionByActorId?.[id] ??
          context?.avoidanceDirectionByActorId[id] ??
          null,
        courseDeg: self ? courseDeg(self.heading) : null,
        speed: self ? self.speed : null,
        bearingToOther: self && other ? trueBearingDeg(self, other) : null,
        relativeBearingToOther: relative,
        sectorOfOther: relative === null ? null : bearingSector(relative),
        maneuver: maneuverFor(frame, id, relationId),
      };
    };

    const computed = stateA && stateB ? computeCpa(stateA, stateB) : null;
    const monitorRange = relationMetric(frame, relationId, "distance");
    const monitorDcpa = relationMetric(frame, relationId, "dcpa");
    const monitorTcpa = relationMetric(frame, relationId, "tcpa");
    const fromMonitor = monitorDcpa !== null && monitorTcpa !== null;

    const rules: PairRule[] = (ruleResult?.evaluations ?? [])
      .map((evaluation) => {
        const key = ruleKey(evaluation);
        return {
          key,
          tag: ruleTag(evaluation),
          title: evaluation.title || evaluation.ruleName,
          ruleName: evaluation.ruleName,
          ruleNumber: evaluation.ruleNumber,
          description: evaluation.description,
          kind: evaluation.kind,
          subjectActorId: evaluation.subjectActorId,
          subjectActorName: evaluation.subjectActorName,
          result: evaluation.result,
          // The monitor's own first failure time when the frame has it (null: never failed);
          // older frames fall back to the timeline, then to this frame.
          firstFailure:
            evaluation.firstFailedAt !== undefined
              ? evaluation.firstFailedAt
              : (firstFailureAtOrBefore(
                  pairTrack?.rules.find((track) => track.key === key),
                  now
                ) ?? (evaluation.result === "FAILED" ? frame.timestamp : null)),
        };
      })
      .sort(compareRules);

    const situationType = context?.situationType ?? "OTHER";
    const encounterActive = isEncounter(situationType);
    let previousEncounterLabel: string | null = null;
    if (!encounterActive && pairTrack) {
      const before = pairTrack.encounter.filter(
        (segment) => segment.start <= now && isEncounter(segment.value.type)
      );
      previousEncounterLabel = before[before.length - 1]?.value.label ?? null;
    }
    const failedRuleCount = rules.filter((rule) => rule.kind === "rule" && rule.result === "FAILED").length;
    const risky = Boolean(
      colregs?.actorsOnCollisionCourse || colregs?.actorsViolateSafetyDomain || colregs?.actorsHaveLowTcpa
    );
    const severity: PairSeverity =
      failedRuleCount > 0 || ruleResult?.overallStatus === "FAILED"
        ? "fail"
        : encounterActive && risky
          ? "risk"
          : encounterActive
            ? "ok"
            : "none";

    return {
      relationId,
      a: vessel(aId, stateB, stateA),
      b: vessel(bId, stateA, stateB),
      situationType,
      encounterLabel: context?.situationLabel || situationType,
      encounterActive,
      previousEncounterLabel,
      since: encounterActive && context ? context.startTimestamp : null,
      range: monitorRange ?? (stateA && stateB ? rangeBetween(stateA, stateB) : null),
      dcpa: fromMonitor ? monitorDcpa : (computed?.dcpa ?? null),
      tcpa: fromMonitor ? monitorTcpa : (computed?.tcpa ?? null),
      cpaSource: fromMonitor ? "monitor" : computed ? "computed" : null,
      safetyDistance: relationMetric(frame, relationId, "safetyDistance"),
      visibilityDistance: relationMetric(frame, relationId, "visibilityDistance"),
      colregs,
      context,
      rules,
      overallStatus: ruleResult?.overallStatus ?? null,
      failedRuleCount,
      severity,
    };
  });
}

/** Per vessel, the encounters it is in now with its role in each, for canvas labels. */
export interface VesselEncounterTag {
  otherId: string;
  otherName: string;
  abbreviation: string;
  label: string;
  role: VesselRole | null;
}

export function encounterTagsByVessel(frame: SimulationFrame | null): Record<string, VesselEncounterTag[]> {
  const out: Record<string, VesselEncounterTag[]> = {};
  if (!frame) {
    return out;
  }
  const names = new Map(frame.actors.map((actor) => [actor.id, actor.name]));
  for (const context of frame.situationContexts) {
    if (!isEncounter(context.situationType)) {
      continue;
    }
    for (const [self, other] of [
      [context.actor1Id, context.actor2Id],
      [context.actor2Id, context.actor1Id],
    ] as const) {
      (out[self] ??= []).push({
        otherId: other,
        otherName: names.get(other) ?? other,
        abbreviation: encounterAbbreviation(context.situationType),
        label: context.situationLabel || context.situationType,
        role: roleOf(context, self),
      });
    }
  }
  return out;
}
