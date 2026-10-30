import { describe, expect, it, vi } from "vitest";
import { sampleCampaignDetail, sampleVerdict } from "../../test/fixtures/clusterViews";
import type { VerdictFilters } from "./operatorApi";
import {
  clampPage,
  DEFAULT_VERDICT_FILTERS,
  describeRange,
  fetchVerdictPage,
  fetchVerdictSummary,
  hasActiveFilters,
  masterSorts,
  pageCount,
  pageWindow,
  runIndexesOf,
  splitFailedRule,
  summarizeVerdicts,
  toApiFilters,
} from "./resultsApi";
import { campaignDetailSchema, verdictSchema, type Verdict } from "./schemas";

function verdict(id: number, overrides: Record<string, unknown> = {}): Verdict {
  return verdictSchema.parse({
    ...sampleVerdict,
    verdict_id: id,
    case_id: id,
    case_index: id,
    state: "passed",
    failed_rules: [],
    first_failure_time_s: null,
    margin: null,
    ...overrides,
  });
}

/** A master holding `total` verdicts; answers limit and offset like the real route and counts the calls. */
function fakeLister(total: number | null, build: (index: number) => Verdict = (index) => verdict(index)) {
  const calls: VerdictFilters[] = [];
  const listVerdicts = vi.fn(async (_campaignId: string, filters: VerdictFilters = {}) => {
    calls.push(filters);
    const offset = filters.offset ?? 0;
    const limit = filters.limit ?? 100;
    const count = total ?? 1_000_000;
    const items = Array.from({ length: Math.max(0, Math.min(limit, count - offset)) }, (_, i) => build(offset + i));
    return { items, total };
  });
  return { client: { listVerdicts } as never, calls, listVerdicts };
}

describe("filter state", () => {
  it("has no active filter by default and turns the set ones into query filters", () => {
    expect(hasActiveFilters(DEFAULT_VERDICT_FILTERS)).toBe(false);
    expect(toApiFilters(DEFAULT_VERDICT_FILTERS)).toEqual({});
    const filters = { classId: "a/1", state: "failed" as const, runIndex: 0, sensitive: "yes" as const };
    expect(hasActiveFilters(filters)).toBe(true);
    expect(toApiFilters(filters)).toEqual({ fec_id: "a/1", state: "failed", run_index: 0, sensitive: true });
    expect(toApiFilters({ ...filters, runIndex: null, sensitive: "no" })).toEqual({ fec_id: "a/1", state: "failed", sensitive: false });
  });

  it("narrows the query to one step when given", () => {
    expect(toApiFilters(DEFAULT_VERDICT_FILTERS, "trajectories")).toEqual({ step: "trajectories" });
    expect(toApiFilters({ ...DEFAULT_VERDICT_FILTERS, state: "failed" }, "scene")).toEqual({ step: "scene", state: "failed" });
  });

  it("keeps run 0 as a filter", () => {
    expect(toApiFilters({ ...DEFAULT_VERDICT_FILTERS, runIndex: 0 })).toEqual({ run_index: 0 });
  });

  it("lists the runs a campaign has verdicts for", () => {
    const detail = campaignDetailSchema.parse(sampleCampaignDetail());
    expect(runIndexesOf(detail)).toEqual(expect.arrayContaining([0]));
    expect(runIndexesOf(undefined)).toEqual([]);
  });
});

describe("paging", () => {
  it("counts pages and keeps the page in range", () => {
    expect(pageCount(0, 50)).toBe(1);
    expect(pageCount(101, 50)).toBe(3);
    expect(clampPage(9, 101, 50)).toBe(2);
    expect(clampPage(-1, 101, 50)).toBe(0);
  });

  it("reads ascending pages from the start", () => {
    expect(pageWindow(120, { page: 0, pageSize: 50, direction: "asc" })).toEqual({ offset: 0, limit: 50, reverse: false });
    expect(pageWindow(120, { page: 2, pageSize: 50, direction: "asc" })).toEqual({ offset: 100, limit: 50, reverse: false });
  });

  it("reads descending pages from the end, the last one short", () => {
    expect(pageWindow(120, { page: 0, pageSize: 50, direction: "desc" })).toEqual({ offset: 70, limit: 50, reverse: true });
    expect(pageWindow(120, { page: 1, pageSize: 50, direction: "desc" })).toEqual({ offset: 20, limit: 50, reverse: true });
    expect(pageWindow(120, { page: 2, pageSize: 50, direction: "desc" })).toEqual({ offset: 0, limit: 20, reverse: true });
    expect(pageWindow(0, { page: 0, pageSize: 50, direction: "desc" }).limit).toBe(0);
    // a page past the end is the last page
    expect(pageWindow(120, { page: 9, pageSize: 50, direction: "desc" })).toEqual({ offset: 0, limit: 20, reverse: true });
  });

  it("describes the shown range", () => {
    expect(describeRange(120, { page: 1, pageSize: 50, direction: "asc" }, 50)).toBe("51 to 100 of 120");
    expect(describeRange(0, { page: 0, pageSize: 50, direction: "asc" }, 0)).toBe("0 of 0");
  });

  it("fetches an ascending page in one call with the filters", async () => {
    const { client, calls } = fakeLister(120);
    const page = await fetchVerdictPage(client, "c1", { ...DEFAULT_VERDICT_FILTERS, state: "failed" }, { page: 1, pageSize: 50, direction: "asc" });
    expect(calls).toEqual([{ state: "failed", limit: 50, offset: 50 }]);
    expect(page.total).toBe(120);
    expect(page.items.map((item) => item.case_index)).toEqual(Array.from({ length: 50 }, (_, i) => 50 + i));
  });

  it("fetches a descending page from the end and reverses it on a master that does not sort", async () => {
    const { client, calls } = fakeLister(120);
    const first = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 50, direction: "desc" });
    expect(calls).toEqual([
      { sort: "fec_id", order: "desc", limit: 50, offset: 0 }, // asked for the server order first: the rows came without encounters
      { limit: 1, offset: 0 },
      { limit: 50, offset: 70 },
    ]);
    expect(first.serverSort).toBe(false);
    expect(first.items[0].case_index).toBe(119);
    expect(first.items[49].case_index).toBe(70);
    const last = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 2, pageSize: 50, direction: "desc" });
    expect(last.items.map((item) => item.case_index)).toEqual(Array.from({ length: 20 }, (_, i) => 19 - i));
  });

  it("answers an empty descending page without a second call", async () => {
    const { client, listVerdicts } = fakeLister(0);
    const page = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 50, direction: "desc" });
    expect(page).toEqual({ items: [], total: 0 });
    expect(listVerdicts).toHaveBeenCalledTimes(1); // an empty page says nothing about the master: no fallback
  });

  it("falls back to the first page, reversed, when the master sends no total", async () => {
    const { client } = fakeLister(null);
    const page = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 3, direction: "desc" });
    expect(page.total).toBeNull();
    expect(page.items.map((item) => item.case_index)).toEqual([2, 1, 0]);
  });
});

/** A master of Phase 7: sorts like the route (a small subset of it) and sends `encounters` on every verdict. */
function sortingLister(total: number) {
  const calls: VerdictFilters[] = [];
  const listVerdicts = vi.fn(async (_campaignId: string, filters: VerdictFilters = {}) => {
    calls.push(filters);
    const all = Array.from({ length: total }, (_, i) => verdict(i, { encounters: i % 2 === 0 ? { "OS_0 - TS_1": ["HEAD_ON"] } : null, first_failure_time_s: i % 3 === 0 ? null : i }));
    if (filters.sort === "first_failure_time_s") {
      const sign = filters.order === "desc" ? -1 : 1;
      all.sort((a, b) => (a.first_failure_time_s === null ? 1 : b.first_failure_time_s === null ? -1 : sign * (a.first_failure_time_s - b.first_failure_time_s))); // nulls last, as the route does
    } else if (filters.order === "desc") {
      all.reverse();
    }
    const offset = filters.offset ?? 0;
    return { items: all.slice(offset, offset + (filters.limit ?? 100)), total };
  });
  return { client: { listVerdicts } as never, calls, listVerdicts };
}

describe("verdict encounters", () => {
  it("reads the encounter types of a verdict, null for an old one and nothing from an older master", () => {
    expect(verdict(1, { encounters: { "OS_0 - TS_1": ["HEAD_ON", "OTHER"] } }).encounters).toEqual({ "OS_0 - TS_1": ["HEAD_ON", "OTHER"] });
    expect(verdict(1, { encounters: null }).encounters).toBeNull();
    expect(verdict(1).encounters).toBeUndefined();
  });
});

describe("verdict sort", () => {
  it("asks a master of Phase 7 for the sorted page and takes it as it comes", async () => {
    const { client, calls } = sortingLister(120);
    const page = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 1, pageSize: 50, direction: "desc", sort: "first_failure_time_s" });
    expect(calls).toEqual([{ sort: "first_failure_time_s", order: "desc", limit: 50, offset: 50 }]);
    expect(page.serverSort).toBe(true);
    const times = page.items.map((item) => item.first_failure_time_s as number);
    expect(times).toHaveLength(50);
    expect([...times].sort((a, b) => b - a)).toEqual(times); // the server's order, not re-read from the end
    expect(page.total).toBe(120);
  });

  it("sends no sort for the default order and still learns that the master sorts", async () => {
    const { client, calls } = sortingLister(10);
    const page = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 5, direction: "asc" });
    expect(calls).toEqual([{ limit: 5, offset: 0 }]);
    expect(page.serverSort).toBe(true);
  });

  it("sends a descending FEC order as a sort too", async () => {
    const { client, calls } = sortingLister(10);
    await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 5, direction: "desc", sort: "fec_id" });
    expect(calls).toEqual([{ sort: "fec_id", order: "desc", limit: 5, offset: 0 }]);
  });

  it("keeps a verdict list with a null encounters value as a master that sorts", () => {
    expect(masterSorts([verdict(1, { encounters: null })])).toBe(true);
    expect(masterSorts([verdict(1)])).toBe(false);
    expect(masterSorts([])).toBeNull();
  });

  it("falls back to the FEC order on a master that ignores sort, and remembers it", async () => {
    const { client, calls } = fakeLister(120);
    const first = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 0, pageSize: 50, direction: "asc", sort: "state" });
    expect(first.serverSort).toBe(false);
    expect(first.items.map((item) => item.case_index)).toEqual(Array.from({ length: 50 }, (_, i) => i)); // the FEC order, whatever column was asked
    expect(calls).toEqual([
      { sort: "state", order: "asc", limit: 50, offset: 0 },
      { limit: 50, offset: 0 },
    ]);
    calls.length = 0;
    const second = await fetchVerdictPage(client, "c1", DEFAULT_VERDICT_FILTERS, { page: 1, pageSize: 50, direction: "asc", sort: "first_failure_time_s" });
    expect(second.serverSort).toBe(false);
    expect(calls).toEqual([{ limit: 50, offset: 50 }]); // no second try with a sort the master ignored
  });
});

describe("failed rule text", () => {
  it("splits the relation from a rule name that holds a colon", () => {
    expect(splitFailedRule("OS_0 - TS_1: Rule 16: Give-Way Vessel Takes Early and Substantial Action (OS_0)")).toEqual({
      relation: "OS_0 - TS_1",
      rule: "Rule 16: Give-Way Vessel Takes Early and Substantial Action (OS_0)",
    });
    expect(splitFailedRule("OS_0 - TS_1: Rule 8: Passing at a Safe Distance (OS_0 - TS_1)")).toEqual({
      relation: "OS_0 - TS_1",
      rule: "Rule 8: Passing at a Safe Distance (OS_0 - TS_1)",
    });
    expect(splitFailedRule("0->1: Rule 16: Give-Way Vessel")).toEqual({ relation: "0->1", rule: "Rule 16: Give-Way Vessel" });
  });

  it("leaves a text without a relation alone, also when a rule name holds a dash", () => {
    expect(splitFailedRule("rule_8")).toEqual({ relation: null, rule: "rule_8" });
    expect(splitFailedRule("Rule 8: Passing")).toEqual({ relation: null, rule: "Rule 8: Passing" });
    expect(splitFailedRule("Rule 17 - Stand-On: keeps course")).toEqual({ relation: null, rule: "Rule 17 - Stand-On: keeps course" });
    expect(splitFailedRule("Rule 8: Passing at a Safe Distance (OS_0 - TS_1)")).toEqual({ relation: null, rule: "Rule 8: Passing at a Safe Distance (OS_0 - TS_1)" });
  });
});

describe("summarizeVerdicts", () => {
  const verdicts = [
    verdict(1, { run_index: 0, state: "failed", failed_rules: ["OS_0 - TS_1: Rule 16: A", "OS_0 - TS_2: Rule 8: B"], first_failure_time_s: 30 }),
    verdict(2, { run_index: 0, state: "failed", failed_rules: ["OS_0 - TS_1: Rule 16: A"], first_failure_time_s: 12 }),
    verdict(3, { run_index: 0, state: "passed" }),
    verdict(4, { run_index: 1, state: "failed", failed_rules: ["OS_0 - TS_1: Rule 16: A", "OS_0 - TS_2: Rule 16: A"], first_failure_time_s: 50, sensitive: true }),
    verdict(5, { run_index: 1, state: "unmonitored" }),
  ];

  it("counts verdicts per run and state", () => {
    const summary = summarizeVerdicts(verdicts, 5);
    expect(summary.byState).toEqual({ passed: 1, failed: 3, unmonitored: 1 });
    expect(summary.byRun).toEqual([
      { runIndex: 0, passed: 1, failed: 2, unmonitored: 0, total: 3 },
      { runIndex: 1, passed: 0, failed: 1, unmonitored: 1, total: 2 },
    ]);
    expect(summary.analyzed).toBe(5);
    expect(summary.partial).toBe(false);
    expect(summary.sensitive).toBe(1);
  });

  it("ranks failed rules by the verdicts they failed in, counting a verdict once per rule", () => {
    const { failedRules } = summarizeVerdicts(verdicts, 5);
    expect(failedRules.map((rule) => [rule.rule, rule.verdicts])).toEqual([
      ["Rule 16: A", 3],
      ["Rule 8: B", 1],
    ]);
    expect(failedRules[0].relations).toEqual(["OS_0 - TS_1", "OS_0 - TS_2"]);
    expect(failedRules[0].earliestFailureS).toBe(12);
  });

  it("marks a summary of a part of the set as partial", () => {
    expect(summarizeVerdicts(verdicts, 9).partial).toBe(true);
    expect(summarizeVerdicts([], 0)).toMatchObject({ analyzed: 0, partial: false, byRun: [], failedRules: [] });
  });
});

describe("fetchVerdictSummary", () => {
  it("reads the filtered set in pages until it is complete", async () => {
    const { client, calls } = fakeLister(2300, (i) => verdict(i, { state: i % 2 === 0 ? "failed" : "passed", failed_rules: i % 2 === 0 ? ["OS_0 - TS_1: Rule 8: B"] : [] }));
    const summary = await fetchVerdictSummary(client, "c1", { ...DEFAULT_VERDICT_FILTERS, runIndex: 0 });
    expect(calls.map((call) => [call.run_index, call.limit, call.offset])).toEqual([
      [0, 1000, 0],
      [0, 1000, 1000],
      [0, 1000, 2000],
    ]);
    expect(summary.analyzed).toBe(2300);
    expect(summary.partial).toBe(false);
    expect(summary.byState.failed).toBe(1150);
  });

  it("stops at the cap and says the summary is partial", async () => {
    const { client, listVerdicts } = fakeLister(5000);
    const summary = await fetchVerdictSummary(client, "c1", DEFAULT_VERDICT_FILTERS, undefined, 2000, 1000);
    expect(listVerdicts).toHaveBeenCalledTimes(2);
    expect(summary).toMatchObject({ analyzed: 2000, total: 5000, partial: true });
  });

  it("summarizes a master that sends no totals from what it read", async () => {
    const { client } = fakeLister(null, (i) => verdict(i));
    const summary = await fetchVerdictSummary(client, "c1", DEFAULT_VERDICT_FILTERS, undefined, 2500, 1000);
    expect(summary.analyzed).toBe(2500);
    expect(summary.partial).toBe(false);
  });
});
