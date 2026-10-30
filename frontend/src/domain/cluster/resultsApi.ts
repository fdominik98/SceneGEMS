import type { OperatorClient, ListPage, VerdictFilters, VerdictSort } from "./operatorApi";
import type { CampaignDetail, Verdict, VerdictState, VerdictStep } from "./schemas";

/**
 * Verdict table logic of the Results section: filter and paging state, how a page is read
 * from the master, and the summary over a filtered set. A master of Phase 7 sorts verdicts
 * (`sort`, `order`); an older one orders them by class, case index and run, ascending, and
 * ignores both, so a descending page is read from the end of the set and the other sorts are
 * not offered (`VerdictPage.serverSort` says which master answered).
 */

export type { VerdictSort };

export type SensitiveFilter = "any" | "yes" | "no";
export type SortDirection = "asc" | "desc";

export interface VerdictFilterState {
  /** Empty for every class. */
  classId: string;
  state: VerdictState | "any";
  /** Null for every run. */
  runIndex: number | null;
  sensitive: SensitiveFilter;
}

export interface VerdictPaging {
  /** Zero based. */
  page: number;
  pageSize: number;
  direction: SortDirection;
  /** The column the master sorts by; `fec_id` (the default) is FEC, case, step and run. */
  sort?: VerdictSort;
}

export const DEFAULT_VERDICT_FILTERS: VerdictFilterState = { classId: "", state: "any", runIndex: null, sensitive: "any" };
export const PAGE_SIZES = [25, 50, 100, 200] as const;
export const DEFAULT_PAGE_SIZE = 50;
/** The most verdicts one summary reads (in pages of `SUMMARY_PAGE`). */
export const SUMMARY_CAP = 5000;
export const SUMMARY_PAGE = 1000;

export function hasActiveFilters(filters: VerdictFilterState): boolean {
  return (
    filters.classId !== "" || filters.state !== "any" || filters.runIndex !== null || filters.sensitive !== "any"
  );
}

/** The API's query filters (without a page) for a filter state, narrowed to one step when given. */
export function toApiFilters(filters: VerdictFilterState, step?: VerdictStep): VerdictFilters {
  const query: VerdictFilters = {};
  if (step !== undefined) {
    query.step = step;
  }
  if (filters.classId !== "") {
    query.fec_id = filters.classId;
  }
  if (filters.state !== "any") {
    query.state = filters.state;
  }
  if (filters.runIndex !== null) {
    query.run_index = filters.runIndex;
  }
  if (filters.sensitive !== "any") {
    query.sensitive = filters.sensitive === "yes";
  }
  return query;
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
}

/** The page kept inside `0 .. pageCount - 1`. */
export function clampPage(page: number, total: number, pageSize: number): number {
  return Math.min(Math.max(0, page), pageCount(total, pageSize) - 1);
}

export interface PageWindow {
  offset: number;
  limit: number;
  /** The rows of the window are shown last to first. */
  reverse: boolean;
}

/** Which rows of the ascending set a page shows; the descending pages count from the end. */
export function pageWindow(total: number, paging: VerdictPaging): PageWindow {
  const size = Math.max(1, paging.pageSize);
  const page = clampPage(paging.page, total, size);
  if (paging.direction === "asc") {
    return { offset: page * size, limit: size, reverse: false };
  }
  const end = Math.max(0, total - page * size);
  const start = Math.max(0, end - size);
  return { offset: start, limit: end - start, reverse: true };
}

/** The "first to last of total" text of a page. */
export function describeRange(total: number, paging: VerdictPaging, shown: number): string {
  if (total === 0 || shown === 0) {
    return "0 of 0";
  }
  const size = Math.max(1, paging.pageSize);
  const first = clampPage(paging.page, total, size) * size + 1;
  return `${first} to ${first + shown - 1} of ${total}`;
}

export interface VerdictPage {
  items: Verdict[];
  /** The number of verdicts the filters match; null when the master does not send `X-Total-Count`. */
  total: number | null;
  /** Whether the master sorts (true) or only has the FEC order (false); left out while the page is empty and nothing was learned yet. */
  serverSort?: boolean;
}

type VerdictLister = Pick<OperatorClient, "listVerdicts">;

/** Per client: whether its master sorts verdicts, learned from the first non-empty page. */
const sortSupport = new WeakMap<object, boolean>();

/** A master of Phase 7 sends `encounters` on every verdict (null when there are none) and sorts; null when the page is empty and says nothing. */
export function masterSorts(items: readonly Verdict[]): boolean | null {
  return items.length === 0 ? null : items.every((item) => item.encounters !== undefined);
}

/** One page of the filtered verdicts, in the order the paging asks for. */
export async function fetchVerdictPage(
  client: VerdictLister,
  campaignId: string,
  filters: VerdictFilterState,
  paging: VerdictPaging,
  signal?: AbortSignal,
  step?: VerdictStep
): Promise<VerdictPage> {
  const query = toApiFilters(filters, step);
  const sort = paging.sort ?? "fec_id";
  const plain = sort === "fec_id" && paging.direction === "asc";
  if (sortSupport.get(client) !== false) {
    const request = plain ? query : { ...query, sort, order: paging.direction };
    const page = await client.listVerdicts(campaignId, { ...request, limit: paging.pageSize, offset: paging.page * paging.pageSize }, signal);
    const sorts = masterSorts(page.items);
    if (sorts !== null) {
      sortSupport.set(client, sorts);
    }
    if (plain || sorts !== false) {
      return { items: page.items, total: page.total, ...(sorts === null ? {} : { serverSort: sorts }) };
    }
  }
  // An older master: the FEC order only, a descending page read from the end.
  const page = await fetchInFecOrder(client, campaignId, query, paging, signal);
  return { ...page, serverSort: false };
}

async function fetchInFecOrder(client: VerdictLister, campaignId: string, query: VerdictFilters, paging: VerdictPaging, signal?: AbortSignal): Promise<VerdictPage> {
  if (paging.direction === "asc") {
    const page = await client.listVerdicts(campaignId, { ...query, limit: paging.pageSize, offset: paging.page * paging.pageSize }, signal);
    return { items: page.items, total: page.total };
  }
  const probe: ListPage<Verdict> = await client.listVerdicts(campaignId, { ...query, limit: 1, offset: 0 }, signal);
  if (probe.total === null) {
    // No total to count back from: the first page, reversed within itself.
    const page = await client.listVerdicts(campaignId, { ...query, limit: paging.pageSize, offset: 0 }, signal);
    return { items: [...page.items].reverse(), total: null };
  }
  const window = pageWindow(probe.total, paging);
  if (window.limit === 0) {
    return { items: [], total: probe.total };
  }
  const page = await client.listVerdicts(campaignId, { ...query, limit: window.limit, offset: window.offset }, signal);
  return { items: [...page.items].reverse(), total: page.total ?? probe.total };
}

// Summary

export interface RunStateCounts {
  runIndex: number;
  passed: number;
  failed: number;
  unmonitored: number;
  total: number;
}

export interface RuleFailure {
  rule: string;
  /** Verdicts the rule failed in. */
  verdicts: number;
  /** Relations (pairs of vessels) it failed for, as the monitor names them. */
  relations: string[];
  /** The earliest first failure time over those verdicts, in seconds. */
  earliestFailureS: number | null;
}

export interface VerdictSummary {
  /** Verdicts read for the summary. */
  analyzed: number;
  /** Verdicts the filters match, when the master said; the summary is partial when it is larger than `analyzed`. */
  total: number | null;
  partial: boolean;
  byState: Record<VerdictState, number>;
  byRun: RunStateCounts[];
  failedRules: RuleFailure[];
  sensitive: number;
}

/** A relation reads `OS_0 - TS_1` (the backend) or `0->1`; a rule such as "Rule 16" or "Rule 17 - Stand-On" is not one. */
const RELATION_TEXT = /^(?!Rule\b|Suggestion\b)[^:]+?(?: - |->)[^:]+$/;

/** A verdict's failed rule text is `<relation>: <rule>`; the rule name itself can hold a colon, so it splits on the first `: ` after a relation. */
export function splitFailedRule(text: string): { relation: string | null; rule: string } {
  const at = text.indexOf(": ");
  if (at <= 0 || !RELATION_TEXT.test(text.slice(0, at))) {
    return { relation: null, rule: text };
  }
  return { relation: text.slice(0, at), rule: text.slice(at + 2) };
}

/** Counts per run and state and the failed rules ranked by the verdicts they failed in. */
export function summarizeVerdicts(verdicts: readonly Verdict[], total: number | null = null): VerdictSummary {
  const byState: Record<VerdictState, number> = { passed: 0, failed: 0, unmonitored: 0 };
  const runs = new Map<number, RunStateCounts>();
  const rules = new Map<string, { verdicts: number; relations: Set<string>; earliest: number | null }>();
  let sensitive = 0;
  for (const verdict of verdicts) {
    byState[verdict.state] += 1;
    if (verdict.sensitive) {
      sensitive += 1;
    }
    let run = runs.get(verdict.run_index);
    if (!run) {
      run = { runIndex: verdict.run_index, passed: 0, failed: 0, unmonitored: 0, total: 0 };
      runs.set(verdict.run_index, run);
    }
    run[verdict.state] += 1;
    run.total += 1;
    const inThisVerdict = new Set<string>();
    for (const text of verdict.failed_rules) {
      const { relation, rule } = splitFailedRule(text);
      let entry = rules.get(rule);
      if (!entry) {
        entry = { verdicts: 0, relations: new Set(), earliest: null };
        rules.set(rule, entry);
      }
      if (!inThisVerdict.has(rule)) {
        inThisVerdict.add(rule);
        entry.verdicts += 1;
        if (verdict.first_failure_time_s !== null && (entry.earliest === null || verdict.first_failure_time_s < entry.earliest)) {
          entry.earliest = verdict.first_failure_time_s;
        }
      }
      if (relation !== null) {
        entry.relations.add(relation);
      }
    }
  }
  const failedRules = [...rules.entries()]
    .map(([rule, entry]) => ({ rule, verdicts: entry.verdicts, relations: [...entry.relations].sort(), earliestFailureS: entry.earliest }))
    .sort((a, b) => b.verdicts - a.verdicts || a.rule.localeCompare(b.rule));
  return {
    analyzed: verdicts.length,
    total,
    partial: total !== null && total > verdicts.length,
    byState,
    byRun: [...runs.values()].sort((a, b) => a.runIndex - b.runIndex),
    failedRules,
    sensitive,
  };
}

/** Reads the filtered verdicts (up to `cap`, in pages) and summarizes them. */
export async function fetchVerdictSummary(
  client: VerdictLister,
  campaignId: string,
  filters: VerdictFilterState,
  signal?: AbortSignal,
  cap: number = SUMMARY_CAP,
  pageSize: number = SUMMARY_PAGE,
  step?: VerdictStep
): Promise<VerdictSummary> {
  const query = toApiFilters(filters, step);
  const verdicts: Verdict[] = [];
  let total: number | null = null;
  while (verdicts.length < cap) {
    const size = Math.min(pageSize, cap - verdicts.length);
    const page = await client.listVerdicts(campaignId, { ...query, limit: size, offset: verdicts.length }, signal);
    verdicts.push(...page.items);
    total = page.total ?? total;
    if (page.items.length < size || (total !== null && verdicts.length >= total)) {
      break;
    }
  }
  return summarizeVerdicts(verdicts, total ?? verdicts.length);
}

/** Share of `part` in `whole` as a whole percentage. */
export function percent(part: number, whole: number): number {
  return whole <= 0 ? 0 : Math.round((part / whole) * 100);
}

/** The run indexes the campaign has verdicts for, from its class counts. */
export function runIndexesOf(detail: CampaignDetail | undefined): number[] {
  const runs = new Set<number>();
  for (const view of detail?.fecs ?? []) {
    for (const run of Object.keys(view.verdicts)) {
      const index = Number(run);
      if (Number.isInteger(index)) {
        runs.add(index);
      }
    }
  }
  return [...runs].sort((a, b) => a - b);
}
