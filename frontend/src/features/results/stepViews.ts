import type { Findings } from "../../domain/cluster/historyApi";
import {
  CAMPAIGN_STEPS,
  type CampaignKind,
  type CampaignSummary,
  type CampaignOrigin,
  type CampaignStep,
  type CaseDetail,
  type CaseState,
  type Verdict,
  type VerdictStep,
} from "../../domain/cluster/schemas";
import { encounterTypeLabel } from "../../domain/simulation/encounterTypes";
import { formatSeconds, formatTime } from "./resultsFormat";

/**
 * The step views of the Results section (design doc 6.6): which steps an entry executed, which one
 * is shown, how a step's findings read, and how a case lists its steps. All pure; the components
 * only draw what these functions return.
 */

export const STEP_LABEL: Record<CampaignStep, string> = {
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
};

/** What each step produces, for the plain sentences. */
export const STEP_OUTPUT: Record<CampaignStep, string> = {
  scene_generation: "scenes",
  trajectory_generation: "trajectory sets",
  simulation: "simulated runs",
};

const VERDICT_STEP: Record<CampaignStep, VerdictStep> = {
  scene_generation: "scene",
  trajectory_generation: "trajectories",
  simulation: "simulation",
};

/** The step name verdicts carry (`scene`, `trajectories`, `simulation`). */
export function verdictStepOf(step: CampaignStep): VerdictStep {
  return VERDICT_STEP[step];
}

/** The step a verdict belongs to, as the verdict cards name it. */
export const VERDICT_STEP_LABEL: Record<VerdictStep, string> = {
  scene: "Scene",
  trajectories: "Trajectories",
  simulation: "Simulation",
};

export const KIND_LABEL: Record<CampaignKind, string> = { campaign: "Campaign", workbench: "Workbench run" };

const ORIGIN_LABEL: Record<CampaignOrigin, string> = {
  wizard: "made in the wizard",
  cli: "made on the command line",
  scene_generation: "run on the scene generation page",
  trajectory_generation: "run on the trajectory generation page",
  simulation: "run on the simulation page",
  live_session: "recorded from a live session",
};

/** Who made the entry, as a phrase; empty for the campaigns that predate origins. */
export function describeOrigin(origin: CampaignOrigin | null | undefined): string {
  return origin ? ORIGIN_LABEL[origin] : "";
}

export type KindFilter = CampaignKind | "any";

const STATE_TONE: Partial<Record<CampaignSummary["actual_state"], string>> = {
  running: "ok",
  completed: "ok",
  stalled: "bad",
  draining: "warn",
  paused: "warn",
};

export function stateBadgeClass(state: CampaignSummary["actual_state"]): string {
  return `section-badge${STATE_TONE[state] ? ` section-badge--${STATE_TONE[state]}` : ""}`;
}

/** The option text of an entry: `name (Campaign, completed, 2026-10-28 10:00)`. */
export function entryOption(entry: CampaignSummary): string {
  const kind = entry.kind ? `${KIND_LABEL[entry.kind]}, ` : "";
  return `${entry.name} (${kind}${entry.actual_state}, ${formatTime(entry.created_at).slice(0, 16)})`;
}

interface EntryLike {
  steps?: readonly CampaignStep[];
}

/**
 * The steps an entry executed, in chain order. A master without Phase 6 sends no steps: every
 * campaign it ran was the full chain.
 */
export function executedSteps(entry: EntryLike | null | undefined): CampaignStep[] {
  const steps = entry?.steps;
  if (!steps || steps.length === 0) {
    return [...CAMPAIGN_STEPS];
  }
  return CAMPAIGN_STEPS.filter((step) => steps.includes(step));
}

/** The step to show: the chosen one when the entry executed it, else the last executed step. */
export function chooseStep(entry: EntryLike | null | undefined, chosen: CampaignStep | null): CampaignStep {
  const steps = executedSteps(entry);
  return chosen !== null && steps.includes(chosen) ? chosen : steps[steps.length - 1];
}

/** Whether the master that sent the entry knows the step filter and the findings route. */
export function hasStepViews(entry: EntryLike | null | undefined): boolean {
  return entry?.steps !== undefined;
}

// Findings

/** Case states in the order a reader looks for them. */
const CASE_STATE_ORDER: CaseState[] = ["complete", "active", "dropped", "failed", "cancelled"];

export interface CountEntry {
  label: string;
  count: number;
}

/** The cases of a step by state, known states first, an unknown state (a newer master) after them; zero counts left out. */
export function caseStateCounts(cases: Readonly<Record<string, number>>): CountEntry[] {
  const known = CASE_STATE_ORDER.filter((state) => (cases[state] ?? 0) > 0).map((state) => ({ label: state, count: cases[state] }));
  const unknown = Object.entries(cases)
    .filter(([state, count]) => count > 0 && !CASE_STATE_ORDER.includes(state as CaseState))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([state, count]) => ({ label: state, count }));
  return [...known, ...unknown];
}

export function totalCases(cases: Readonly<Record<string, number>>): number {
  return Object.values(cases).reduce((sum, count) => sum + count, 0);
}

export interface RankedRule {
  rule: string;
  count: number;
  /** The earliest first failure over the verdicts the rule failed in. */
  firstMin: string;
  firstMedian: string;
}

/** Failed rules most often first, ties by name. */
export function rankFailedRules(rules: Findings["failed_rules"]): RankedRule[] {
  return [...rules]
    .sort((a, b) => b.count - a.count || a.rule.localeCompare(b.rule))
    .map((rule) => ({
      rule: rule.rule,
      count: rule.count,
      firstMin: formatSeconds(rule.first_failure_time_s.min),
      firstMedian: formatSeconds(rule.first_failure_time_s.median),
    }));
}

/** The vessel pairs of a step by the first encounter type of each, most pairs first then by label, OTHER last among equals; empty counts and an older master's missing field give none. */
export function encounterTypeCounts(counts: Readonly<Record<string, number>> | undefined): CountEntry[] {
  return Object.entries(counts ?? {})
    .filter(([, count]) => count > 0)
    .map(([type, count]) => ({ label: encounterTypeLabel(type), count, other: type.toUpperCase() === "OTHER" }))
    .sort((a, b) => b.count - a.count || Number(a.other) - Number(b.other) || a.label.localeCompare(b.label))
    .map(({ label, count }) => ({ label, count }));
}

export interface ClassRow {
  classId: string;
  cases: number;
  passed: number;
  failed: number;
}

/** FECs with the most failures first, then by name (numbers inside names in order). */
export function rankClasses(classes: Findings["fecs"]): ClassRow[] {
  return classes
    .map((view) => ({ classId: view.fec_id, cases: view.cases, passed: view.passed, failed: view.failed }))
    .sort((a, b) => b.failed - a.failed || a.classId.localeCompare(b.classId, undefined, { numeric: true }));
}

export interface FindingsView {
  step: CampaignStep;
  monitored: boolean;
  /** An unmonitored step gives statistics only: the verdicts and the failed rules are left out. */
  partial: boolean;
  /** The sentence that says plainly what the numbers are. */
  statement: string;
  cases: CountEntry[];
  totalCases: number;
  outputs: { count: number; valid: number; complete: number };
  /** Whether "complete" says more than "valid" (a valid scene is complete by definition). */
  showComplete: boolean;
  verdicts: { passed: number; failed: number; unmonitored: number; judged: number } | null;
  failedRules: RankedRule[];
  /** The vessel pairs by their first encounter type; empty when the step is unmonitored or the master predates them. */
  encounters: CountEntry[];
  classes: ClassRow[];
  duration: { median: string; p90: string } | null;
}

/** The findings of a step as the panel shows them. */
export function describeFindings(findings: Findings): FindingsView {
  const label = STEP_LABEL[findings.step];
  const monitored = findings.monitored;
  const judged = findings.verdicts.passed + findings.verdicts.failed;
  const hasDuration = findings.durations_s.median !== null || findings.durations_s.p90 !== null;
  return {
    step: findings.step,
    monitored,
    partial: !monitored,
    statement: monitored
      ? `A monitor judged the ${STEP_OUTPUT[findings.step]} of this step: ${findings.verdicts.passed} passed and ${findings.verdicts.failed} failed.`
      : `No monitor judged this step. These are partial findings: statistics about the ${STEP_OUTPUT[findings.step]} of ${label.toLowerCase()}, without monitor result summaries.`,
    cases: caseStateCounts(findings.cases),
    totalCases: totalCases(findings.cases),
    outputs: findings.outputs,
    showComplete: findings.step !== "scene_generation",
    verdicts: monitored ? { ...findings.verdicts, judged } : null,
    failedRules: monitored ? rankFailedRules(findings.failed_rules) : [],
    encounters: monitored ? encounterTypeCounts(findings.encounter_types) : [],
    classes: rankClasses(findings.fecs),
    duration: hasDuration ? { median: formatSeconds(findings.durations_s.median), p90: formatSeconds(findings.durations_s.p90) } : null,
  };
}

// The case page

export interface CaseStepRow {
  step: CampaignStep;
  label: string;
  /** False for a step the entry did not execute (its row still shows, so the case reads as a whole chain). */
  executed: boolean;
  /** What the case has of the step's output. */
  output: string;
  /** The step's verdicts by state; empty when no monitor judged the step for this case. */
  verdicts: { passed: number; failed: number; unmonitored: number };
  failedRules: string[];
  monitored: boolean;
}

function verdictsOfStep(verdicts: readonly Verdict[], step: CampaignStep): Verdict[] {
  const name = verdictStepOf(step);
  // A master before Phase 6 sends no step: all its verdicts are of the simulation.
  return verdicts.filter((verdict) => (verdict.step ?? "simulation") === name);
}

function outputOf(detail: CaseDetail, step: CampaignStep): string {
  switch (step) {
    case "scene_generation":
      return detail.scene_artifact !== null ? "scene stored" : "no scene";
    case "trajectory_generation":
      if (detail.trajectories_artifact === null) {
        return "no trajectories";
      }
      return detail.trajectories_complete === false ? "trajectories stored, incomplete" : "trajectories stored";
    case "simulation": {
      const runs = detail.run_records.length;
      return runs === 0 ? "no run" : `${runs} ${runs === 1 ? "run" : "runs"}`;
    }
  }
}

/** One row per step of the chain, with the case's output and verdicts of that step. */
export function caseStepRows(detail: CaseDetail, executed: readonly CampaignStep[]): CaseStepRow[] {
  return CAMPAIGN_STEPS.map((step) => {
    const verdicts = verdictsOfStep(detail.verdicts, step);
    const counts = { passed: 0, failed: 0, unmonitored: 0 };
    for (const verdict of verdicts) {
      counts[verdict.state] += 1;
    }
    const failedRules = [...new Set(verdicts.flatMap((verdict) => verdict.failed_rules))];
    return {
      step,
      label: STEP_LABEL[step],
      executed: executed.includes(step),
      output: outputOf(detail, step),
      verdicts: counts,
      failedRules,
      monitored: counts.passed + counts.failed > 0,
    };
  });
}

/** The monitor result summary column of a case step row: "passed", "failed (2 of 3 runs)" or why there is none. */
export function describeStepVerdict(row: CaseStepRow): string {
  if (!row.executed) {
    return "step not executed";
  }
  const { passed, failed, unmonitored } = row.verdicts;
  const judged = passed + failed;
  if (judged === 0) {
    return unmonitored > 0 ? "not monitored" : "no monitor result summary";
  }
  if (judged === 1) {
    return failed === 1 ? "failed" : "passed";
  }
  return failed > 0 ? `failed in ${failed} of ${judged} runs` : `passed in ${judged} runs`;
}
