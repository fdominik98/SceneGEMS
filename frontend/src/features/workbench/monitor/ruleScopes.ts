import type { RuleEvaluation, RuleResult, RuleResultData } from "../../../domain/simulation/types";
import { ruleKey } from "./ruleTimelineModel";

/**
 * Titles (as slugs) of the rules on a vessel's own maneuvering. The monitor keeps their one
 * result per vessel and lists it under every encounter the vessel is in, so they repeat on
 * the wire. They mirror `make_maneuver_default_rules` in the backend's
 * `colregs_rules/default_rules.py`; a rule missing here stays under its encounters.
 */
const VESSEL_RULE_SLUGS: ReadonlySet<string> = new Set([
  "readily-apparent-course-change",
  "readily-apparent-speed-change",
  "course-change-persistence",
  "course-held-after-the-manoeuvre",
  "no-new-situation-while-manoeuvring",
  "stand-on-vessel-keeps-course-and-speed",
]);

/** The monitor's slug of a rule title: lower case, runs of other characters as one dash. */
function titleSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Whether a rule is about one vessel's own maneuvering (judged once per vessel), as opposed
 * to a rule of one encounter. A rule that names a subject vessel but belongs to an encounter,
 * such as the give-way vessel's early action, is not vessel-scoped: its result differs from
 * encounter to encounter.
 */
export function isVesselScopedRule(evaluation: Pick<RuleEvaluation, "title" | "subjectActorId">): boolean {
  return evaluation.subjectActorId !== null && VESSEL_RULE_SLUGS.has(titleSlug(evaluation.title));
}

/** The rules of one vessel's own maneuvering, each listed once. */
export interface VesselRuleGroup {
  actorId: string;
  actorName: string;
  evaluations: RuleEvaluation[];
}

/** The rules of one encounter, without the vessel-scoped rules of its two vessels. */
export interface EncounterRuleGroup {
  relationId: string;
  evaluations: RuleEvaluation[];
}

export interface RuleScopes {
  vessels: VesselRuleGroup[];
  encounters: EncounterRuleGroup[];
}

/** FAILED over UNKNOWN over PASSED. */
const SEVERITY: Record<RuleResult, number> = { FAILED: 2, UNKNOWN: 1, PASSED: 0 };

function earliest(a: number | null | undefined, b: number | null | undefined): number | null | undefined {
  if (typeof a !== "number") return typeof b === "number" ? b : a;
  if (typeof b !== "number") return a;
  return Math.min(a, b);
}

/**
 * Split a frame's rule results by what they constrain: the rules of each vessel's own
 * maneuvering, listed once per vessel, and the rules of each encounter. The copies of a
 * vessel rule carry one result; should they ever differ, the worst one and the earliest
 * first failure are kept. Vessels are ordered by name, encounters as the frame lists them.
 */
export function splitRuleResults(ruleResults: RuleResultData[]): RuleScopes {
  const vessels = new Map<string, { group: VesselRuleGroup; byKey: Map<string, number> }>();
  const encounters: EncounterRuleGroup[] = [];

  for (const result of ruleResults) {
    const own: RuleEvaluation[] = [];
    for (const evaluation of result.evaluations) {
      if (!isVesselScopedRule(evaluation)) {
        own.push(evaluation);
        continue;
      }
      const actorId = evaluation.subjectActorId as string;
      let entry = vessels.get(actorId);
      if (!entry) {
        entry = {
          group: { actorId, actorName: evaluation.subjectActorName || actorId, evaluations: [] },
          byKey: new Map(),
        };
        vessels.set(actorId, entry);
      }
      const key = ruleKey(evaluation);
      const index = entry.byKey.get(key);
      if (index === undefined) {
        entry.byKey.set(key, entry.group.evaluations.length);
        entry.group.evaluations.push(evaluation);
        continue;
      }
      const kept = entry.group.evaluations[index]!;
      const worse = SEVERITY[evaluation.result] > SEVERITY[kept.result] ? evaluation : kept;
      const firstFailedAt = earliest(kept.firstFailedAt, evaluation.firstFailedAt);
      entry.group.evaluations[index] = firstFailedAt === undefined ? worse : { ...worse, firstFailedAt };
    }
    encounters.push({ relationId: result.relationId, evaluations: own });
  }

  const vesselGroups = [...vessels.values()]
    .map((entry) => entry.group)
    .sort(
      (a, b) =>
        a.actorName.localeCompare(b.actorName, undefined, { numeric: true }) ||
        a.actorId.localeCompare(b.actorId, undefined, { numeric: true }),
    );
  return { vessels: vesselGroups, encounters };
}

/** Number of FAILED evaluations in a group. */
export function failedCount(evaluations: RuleEvaluation[]): number {
  return evaluations.reduce((count, evaluation) => count + (evaluation.result === "FAILED" ? 1 : 0), 0);
}
