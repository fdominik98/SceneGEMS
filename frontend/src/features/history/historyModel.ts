import type { InputSource, OutputRow, OutputVerdict } from "../../domain/cluster/historyApi";
import type { CampaignsTopicState, CampaignsUpdate } from "../../domain/cluster/liveTopics";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { splitFailedRule } from "../../domain/cluster/resultsApi";
import {
  CAMPAIGN_STEPS,
  IMPLIED_STEPS,
  type CampaignKind,
  type CampaignOrigin,
  type CampaignRow,
  type CampaignRowTotals,
  type CampaignStep,
  type CampaignSummary,
  type VerdictState,
  type VerdictStep,
} from "../../domain/cluster/schemas";
import { encounterTypeLabel } from "../../domain/simulation/encounterTypes";
import { formatDuration, plural } from "../campaigns/campaignFormat";
import { isEncounter, type VesselRole } from "../workbench/monitor/encounterPairs";
import { WORKBENCH_PAGE_OF_STEP, type WorkbenchTarget } from "../workbench/pages/workbenchTarget";
import { isFinalState, newerSummary, type ListViewState, type Tone } from "./campaignModel";

/**
 * What Campaign History shows, as pure functions: entry kinds, origins and steps, the row totals,
 * the filters the list route cannot apply, the live list updates, the outputs of a step with their
 * monitor result summary and the workbench target of an output.
 */

export const KIND_LABELS: Record<CampaignKind, string> = {
  campaign: "Campaign",
  workbench: "Workbench run",
};

export const ORIGIN_LABELS: Record<CampaignOrigin, string> = {
  wizard: "wizard",
  cli: "command line",
  design_space_exploration: "design space exploration page",
  scene_generation: "scene generation page",
  trajectory_generation: "trajectory generation page",
  simulation: "simulation page",
  live_session: "live session",
};

export const STEP_LABELS: Record<CampaignStep, string> = {
  design_space_exploration: "Design space exploration",
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
};

/** What one output of a step is called. */
export const STEP_OUTPUT_NOUNS: Record<CampaignStep, { one: string; many: string }> = {
  design_space_exploration: { one: "FEC", many: "FECs" },
  scene_generation: { one: "scene", many: "scenes" },
  trajectory_generation: { one: "trajectory set", many: "trajectory sets" },
  simulation: { one: "run", many: "runs" },
};

/** The verdict step of each campaign step, as the list row totals name it; the design space exploration has no monitor and no verdicts. */
export const VERDICT_STEP_OF: Record<CampaignStep, VerdictStep | null> = {
  design_space_exploration: null,
  scene_generation: "scene",
  trajectory_generation: "trajectories",
  simulation: "simulation",
};

/** The kind of an entry; a control node without Phase 6 sends none, and then every entry is a campaign. */
export function entryKind(entry: Pick<CampaignSummary, "kind">): CampaignKind {
  return entry.kind ?? "campaign";
}

/** Who made the entry; campaigns created before migration 0005 recorded no origin. */
export function originLabel(origin: CampaignOrigin | null | undefined): string {
  return origin ? `the ${ORIGIN_LABELS[origin]}` : "not recorded";
}

/** The origin as a list row says it: "from the wizard", or "origin not recorded". */
export function madeByLabel(origin: CampaignOrigin | null | undefined): string {
  return origin ? `from the ${ORIGIN_LABELS[origin]}` : "origin not recorded";
}

const WORKBENCH_PAGE_ORIGINS: ReadonlySet<CampaignOrigin> = new Set<CampaignOrigin>(["design_space_exploration", "scene_generation", "trajectory_generation", "simulation"]);

/**
 * What a list row says about the origin beside the kind, or null when the row says it already: a workbench
 * run comes from the page of the step its Steps column names.
 */
export function rowOriginNote(entry: Pick<CampaignSummary, "kind" | "origin">): string | null {
  const repeated = entryKind(entry) === "workbench" && entry.origin != null && WORKBENCH_PAGE_ORIGINS.has(entry.origin);
  return repeated ? null : madeByLabel(entry.origin);
}

/** The executed steps in chain order; an entry without `steps` (format 1, or a control node without Phase 6) runs the chain of then. */
export function entrySteps(entry: Pick<CampaignSummary, "steps">): CampaignStep[] {
  const steps = entry.steps ?? [];
  return steps.length === 0 ? [...IMPLIED_STEPS] : CAMPAIGN_STEPS.filter((step) => steps.includes(step));
}

export function stepsLabel(steps: readonly CampaignStep[]): string {
  return steps.map((step, index) => (index === 0 ? STEP_LABELS[step] : STEP_LABELS[step].toLowerCase())).join(", ");
}

const CASE_STATE_ORDER = ["complete", "active", "dropped", "failed", "cancelled"];

export interface VerdictLine {
  step: CampaignStep;
  passed: number;
  failed: number;
  unmonitored: number;
}

export interface RowTotalsSummary {
  /** Cases by state, the most telling first ("5 complete, 4 active, 1 dropped"), or null without totals. */
  cases: string | null;
  /** Verdicts of each executed step that has any. */
  verdicts: VerdictLine[];
}

export function rowTotalsSummary(totals: CampaignRowTotals | undefined, steps: readonly CampaignStep[]): RowTotalsSummary {
  if (!totals) {
    return { cases: null, verdicts: [] };
  }
  const states = Object.entries(totals.cases)
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => rank(a) - rank(b));
  const cases = states.length === 0 ? "no cases yet" : states.map(([state, count]) => `${count} ${state}`).join(", ");
  const verdicts: VerdictLine[] = [];
  for (const step of steps) {
    const verdictStep = VERDICT_STEP_OF[step];
    const counts = verdictStep === null ? undefined : totals.verdicts[verdictStep];
    if (!counts) {
      continue;
    }
    const line = { step, passed: counts.passed ?? 0, failed: counts.failed ?? 0, unmonitored: counts.unmonitored ?? 0 };
    if (line.passed + line.failed + line.unmonitored > 0) {
      verdicts.push(line);
    }
  }
  return { cases, verdicts };
}

function rank(state: string): number {
  const index = CASE_STATE_ORDER.indexOf(state);
  return index === -1 ? CASE_STATE_ORDER.length : index;
}

// The list

/** Whether a row belongs in the list view: the route filters by kind, state and name, the step only here. */
export function matchesListView(row: CampaignRow, view: ListViewState): boolean {
  if (view.kind && entryKind(row) !== view.kind) {
    return false;
  }
  if (view.states.length > 0 && !view.states.includes(row.actual_state)) {
    return false;
  }
  if (view.step && !entrySteps(row).includes(view.step)) {
    return false;
  }
  const q = view.q?.trim().toLowerCase() ?? "";
  return q === "" || row.name.toLowerCase().includes(q);
}

/** The page as the live channel has it now: rows replaced by newer pushed ones, deleted ones and ones that left the filter dropped. */
export function mergeLiveRows(page: readonly CampaignRow[], live: CampaignsTopicState | null, view: ListViewState): CampaignRow[] {
  const rows = live
    ? page
        .filter((row) => !live.deleted.includes(row.campaign_id))
        .map((row) => {
          const pushed = live.rows[row.campaign_id];
          return pushed ? newerSummary(row, pushed) : row;
        })
    : [...page];
  return rows.filter((row) => matchesListView(row, view));
}

/**
 * Whether a pushed update changes more than the rows on the page, so the page must be read
 * again: a deletion (the page and the total shrink), a row that left the filter, or a matching
 * entry the page does not hold (a new one at the top, or one moved in by the filter).
 */
export function liveNeedsRefetch(pageIds: readonly string[], view: ListViewState, update: CampaignsUpdate): boolean {
  if ("deleted" in update) {
    return true;
  }
  const onPage = pageIds.includes(update.campaign.campaign_id);
  const matches = matchesListView(update.campaign, view);
  return onPage ? !matches : matches;
}

export function canDelete(entry: Pick<CampaignSummary, "actual_state">): boolean {
  return isFinalState(entry.actual_state);
}

/** Why the control node refused a delete, in words the operator can act on. */
export function deleteRefusal(error: unknown): string {
  if (error instanceof OperatorApiError) {
    if (error.status === 409) {
      return "The entry is not finished. Stop it first, then delete it.";
    }
    if (error.status === 404) {
      return "The entry is not on this control node any more.";
    }
  }
  return describeOperatorError(error);
}

// Outputs of a step

export const OUTPUT_PAGE_SIZE = 20;

/** The output exists, so it can be loaded on its workbench page. */
export function canOpenOutput(row: OutputRow): boolean {
  return row.artifact !== null;
}

/** The case is still working on this step's output: its job can be followed live. */
export function isOutputRunning(row: OutputRow): boolean {
  return row.state === "active" && row.artifact === null;
}

/** The workbench target of an output: its page, case and step, the run record of a simulated run, and `live` to follow a running job. */
export function outputTarget(campaignId: string, step: CampaignStep, row: OutputRow, live = false): WorkbenchTarget {
  return {
    page: WORKBENCH_PAGE_OF_STEP[step],
    campaignId,
    caseId: row.case_id,
    step,
    ...(step === "simulation" && row.run_record_id !== null ? { runRecordId: row.run_record_id } : {}),
    // An explored FEC is a row of the exploration case: the page loads the exploration and selects the FEC
    ...(step === "design_space_exploration" ? { caseIndex: 0, fecId: row.fec_id } : {}),
    ...(live ? { live: true } : {}),
  };
}

export interface OutputFlag {
  label: string;
  tone: Tone;
  title: string;
}

/** The valid and complete flags of an output; a flag the control node leaves null is not shown. */
export function outputFlags(row: OutputRow): OutputFlag[] {
  const flags: OutputFlag[] = [];
  if (row.valid === true) {
    flags.push({ label: "valid", tone: "ok", title: "The output exists and the case did not drop at this step." });
  } else if (row.valid === false) {
    flags.push({ label: "not valid", tone: "bad", title: "The case dropped at this step, so a later step cannot use the output." });
  }
  if (row.complete === true) {
    flags.push({ label: "complete", tone: "ok", title: "A complete plan: it covers the planned stretch and fails no COLREGS rule." });
  } else if (row.complete === false) {
    flags.push({ label: "incomplete", tone: "warn", title: "Not a complete plan, the best path the planner found: it ends early or still fails a COLREGS rule." });
  }
  return flags;
}

/**
 * What an output's case is called: a case of a catalog class (with its folder), a case of a
 * scenario given as content, or the input item a case of a later start stands for (one case each).
 * Cases are counted from 1 for people (the API's `case_index` from 0), as the workbench pages count them.
 */
export function outputCaseLabel(row: Pick<OutputRow, "fec_id" | "case_index">): { title: string; detail: string | null } {
  const number = row.case_index + 1;
  const slash = row.fec_id.indexOf("/");
  const folder = slash === -1 ? "" : row.fec_id.slice(0, slash);
  const name = slash === -1 ? row.fec_id : row.fec_id.slice(slash + 1);
  if (folder === "item") {
    return { title: `input item ${name}`, detail: null };
  }
  if (folder === "scenario") {
    return { title: `case ${number} of ${name}`, detail: "scenario given as content" };
  }
  const last = name.lastIndexOf("/");
  return last === -1
    ? { title: `case ${number} of ${name}`, detail: folder || null }
    : { title: `case ${number} of ${name.slice(last + 1)}`, detail: `${folder}/${name.slice(0, last)}` };
}

/** The run and repeat of a simulated output, counted from 1, or null for other steps. */
export function runLabel(row: Pick<OutputRow, "run_index" | "repeat_index">): string | null {
  if (row.run_index === null) {
    return null;
  }
  return row.repeat_index === null ? `run ${row.run_index + 1}` : `run ${row.run_index + 1}, repeat ${row.repeat_index + 1}`;
}

export type SourceLabel =
  | { kind: "entry"; campaignId: string; text: string }
  | { kind: "text"; text: string };

/** Where an output's input came from: a case of another entry (a link), an uploaded file, or an entry deleted since. */
export function inputSourceLabel(source: InputSource | null): SourceLabel | null {
  if (source === null) {
    return null;
  }
  if (source.file) {
    return { kind: "text", text: `file ${source.file}` };
  }
  if (source.campaign_id) {
    const step = source.step && source.step in STEP_LABELS ? ` (${STEP_LABELS[source.step as CampaignStep].toLowerCase()})` : "";
    // The source names the case by its database id, not by its number in the entry: say so, or it reads as a case number
    const caseText = source.case_id !== undefined ? `case id ${source.case_id}` : "an output";
    return { kind: "entry", campaignId: source.campaign_id, text: `${caseText}${step}` };
  }
  return { kind: "text", text: "a deleted entry" };
}

// The monitor result summary of an output (the API calls it the output's verdict)

export interface MonitorEncounter {
  type: string;
  label: string;
  /** Each vessel with its role, give-way first; null when the verdict did not record them. */
  roles: { vessel: string; role: VesselRole }[] | null;
}

export interface MonitorPair {
  relation: string;
  /** What the pair met in, in order of first appearance; empty when it never met in an encounter. */
  encounters: MonitorEncounter[];
  /** The rules that failed for the pair, without the pair's name. */
  failedRules: string[];
}

export interface MonitorSummary {
  state: VerdictState;
  /** "no rule failed" or "2 rules failed, first at 1 min 1 s"; null when no monitor judged the output. */
  headline: string | null;
  /** The pairs worth a line: those in an encounter or with a failed rule, by name. */
  pairs: MonitorPair[];
  /** How many pairs were left out: they never met in an encounter and failed nothing. */
  quietPairs: number;
  /** Failed rules of no listed pair: a vessel's own, or of a pair the verdict has no encounters for. */
  otherFailedRules: string[];
}

/** A vessel's own rules are kept under the relation of the vessel with itself (`os - os`). */
function isOwnRelation(relation: string): boolean {
  const [first, second] = relation.split(" - ");
  return first === second;
}

function monitorEncounter(type: string, roles: { give_way: string[]; stand_on: string[] } | undefined): MonitorEncounter {
  return {
    type,
    label: encounterTypeLabel(type),
    roles: roles
      ? [...roles.give_way.map((vessel) => ({ vessel, role: "give-way" as const })), ...roles.stand_on.map((vessel) => ({ vessel, role: "stand-on" as const }))]
      : null,
  };
}

function monitorHeadline(verdict: OutputVerdict): string | null {
  if (verdict.state === "unmonitored") {
    return null;
  }
  if (verdict.failed_rules.length === 0) {
    return "no rule failed";
  }
  const first = verdict.first_failure_time_s;
  return `${plural(verdict.failed_rules.length, "rule")} failed${first === null || first === undefined ? "" : `, first at ${formatDuration(first)}`}`;
}

/** A verdict as its row shows it: the state, each vessel pair's encounter types with the vessels' roles, and the failed rules under their pair. */
export function monitorSummary(verdict: OutputVerdict): MonitorSummary {
  const pairs = new Map<string, MonitorPair>();
  for (const [relation, types] of Object.entries(verdict.encounters ?? {})) {
    pairs.set(relation, {
      relation,
      encounters: types.filter((type) => isEncounter(type)).map((type) => monitorEncounter(type, verdict.encounter_roles?.[relation]?.[type])),
      failedRules: [],
    });
  }
  const otherFailedRules: string[] = [];
  for (const text of verdict.failed_rules) {
    const { relation, rule } = splitFailedRule(text);
    const pair = relation === null ? undefined : pairs.get(relation);
    if (pair) {
      pair.failedRules.push(rule);
    } else {
      otherFailedRules.push(relation !== null && isOwnRelation(relation) ? rule : text);
    }
  }
  const listed = [...pairs.values()]
    .filter((pair) => pair.encounters.length > 0 || pair.failedRules.length > 0)
    .sort((a, b) => a.relation.localeCompare(b.relation, undefined, { numeric: true }));
  return { state: verdict.state, headline: monitorHeadline(verdict), pairs: listed, quietPairs: pairs.size - listed.length, otherFailedRules };
}

/** Whether the outputs show the summary: the step has a monitor configured, or (the config not read yet, or changed since) a row says a monitor judged it. */
export function showsMonitorSummary(monitored: boolean | null, rows: readonly OutputRow[]): boolean {
  return monitored === true || rows.some((row) => row.verdict !== null && row.verdict.state !== "unmonitored");
}

/** The tab a detail opens on: the remembered step when the entry runs it, else the last executed step. */
export function initialStep(steps: readonly CampaignStep[], remembered: CampaignStep | null): CampaignStep {
  return remembered && steps.includes(remembered) ? remembered : steps[steps.length - 1];
}
