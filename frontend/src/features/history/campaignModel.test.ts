import { describe, expect, it } from "vitest";
import { campaignConfigSchema, campaignEventSchema, campaignSummarySchema, classViewSchema } from "../../domain/cluster/schemas";
import { sampleCampaignSummary, sampleClass } from "../../test/fixtures/clusterViews";
import {
  actualStateTone,
  baseSeed,
  campaignProgress,
  classProgress,
  controlAvailability,
  countByState,
  EMPTY_EVENT_FEED,
  eventDetails,
  eventLabel,
  eventTone,
  eventFeedReducer,
  EVENTS_KEPT,
  filterAndSortClasses,
  INITIAL_LIST_VIEW,
  isConverging,
  listQuery,
  listViewReducer,
  mergeEvents,
  newerSummary,
  pageInfo,
  runIndexes,
  runNames,
  runVerdicts,
  stepMonitored,
} from "./campaignModel";

const summary = (overrides: Record<string, unknown> = {}) => campaignSummarySchema.parse({ ...sampleCampaignSummary, ...overrides });
const event = (id: number, kind = "note", detail: Record<string, unknown> = {}) =>
  campaignEventSchema.parse({ event_id: id, at: "2026-10-26T09:00:00+00:00", kind, fec_id: null, detail });
const classView = (overrides: Record<string, unknown> = {}) => classViewSchema.parse(sampleClass(overrides));

describe("progress and state", () => {
  it("measures complete cases against the quota", () => {
    expect(campaignProgress({ complete: 3, quota: 10, dropped: 1, in_flight: 2 })).toEqual({ complete: 3, quota: 10, dropped: 1, inFlight: 2, fraction: 0.3 });
    expect(campaignProgress({ complete: 12, quota: 10, dropped: 0, in_flight: 0 }).fraction).toBe(1);
    expect(campaignProgress({ complete: 0, quota: 0, dropped: 0, in_flight: 0 }).fraction).toBe(0);
    expect(campaignProgress(null).quota).toBe(0);
  });

  it("gives each state a tone", () => {
    expect(actualStateTone("running")).toBe("ok");
    expect(actualStateTone("stalled")).toBe("bad");
    expect(actualStateTone("paused")).toBe("warn");
    expect(actualStateTone("completed")).toBe("info");
    expect(actualStateTone("created")).toBe("idle");
  });

  it("tells when the engine has not reached the desired state", () => {
    expect(isConverging(summary({ desired_state: "running", actual_state: "paused" }))).toBe(true);
    expect(isConverging(summary({ desired_state: "running", actual_state: "running" }))).toBe(false);
    expect(isConverging(summary({ desired_state: "running", actual_state: "stalled" }))).toBe(false);
    expect(isConverging(summary({ desired_state: "paused", actual_state: "created" }))).toBe(false);
    expect(isConverging(summary({ desired_state: "stopped", actual_state: "running" }))).toBe(true);
    expect(isConverging(summary({ desired_state: "stopped", actual_state: "stopped" }))).toBe(false);
  });
});

describe("controlAvailability", () => {
  const enabled = (value: ReturnType<typeof summary>) =>
    Object.entries(controlAvailability(value))
      .filter(([, availability]) => availability.enabled)
      .map(([control]) => control);

  it("offers start, pause, drain and stop to a campaign that was created paused", () => {
    expect(enabled(summary({ desired_state: "paused", actual_state: "created", started_at: null }))).toEqual(["start", "drain", "stop"]);
  });

  it("offers pause, drain and stop to a running campaign", () => {
    expect(enabled(summary({ desired_state: "running", actual_state: "running" }))).toEqual(["pause", "drain", "stop"]);
  });

  it("offers resume, drain and stop to a paused campaign that has started before", () => {
    expect(enabled(summary({ desired_state: "paused", actual_state: "paused" }))).toEqual(["resume", "drain", "stop"]);
  });

  it("offers resume, pause and stop to a draining one", () => {
    expect(enabled(summary({ desired_state: "draining", actual_state: "draining" }))).toEqual(["resume", "pause", "stop"]);
  });

  it("offers nothing once the campaign is finished or stopping, and says why", () => {
    expect(enabled(summary({ desired_state: "stopped", actual_state: "stopped" }))).toEqual([]);
    expect(enabled(summary({ desired_state: "running", actual_state: "completed" }))).toEqual([]);
    const stopping = controlAvailability(summary({ desired_state: "stopped", actual_state: "running" }));
    expect(stopping.stop.enabled).toBe(false);
    expect(stopping.stop.reason).toMatch(/cannot be undone/);
    expect(controlAvailability(summary({ actual_state: "completed", desired_state: "running" })).pause.reason).toMatch(/finished/);
  });

  it("explains a control that makes no change", () => {
    const running = controlAvailability(summary({ desired_state: "running", actual_state: "running" }));
    expect(running.start.reason).toMatch(/asked to run already/);
    expect(running.resume.reason).toMatch(/asked to run already/);
  });

  it("keeps Start and Resume off while a needed capability has no machine", () => {
    const blocker = "No usable machine of the campaign runs post hoc monitoring.";
    const created = controlAvailability(summary({ desired_state: "paused", actual_state: "created", started_at: null }), blocker);
    expect(created.start).toEqual({ enabled: false, reason: `It cannot start: ${blocker}` });
    expect(created.drain.enabled && created.stop.enabled).toBe(true);
    const paused = controlAvailability(summary({ desired_state: "paused", actual_state: "paused", started_at: "2026-10-26T09:00:00+00:00" }), blocker);
    expect(paused.resume.reason).toBe(`It cannot start: ${blocker}`);
    expect(controlAvailability(summary({ desired_state: "running", actual_state: "running" }), blocker).pause.enabled).toBe(true);
  });
});

describe("newerSummary", () => {
  it("keeps the summary updated last", () => {
    const older = summary({ updated_at: "2026-10-26T09:00:00+00:00" });
    const newer = summary({ updated_at: "2026-10-26T09:00:05+00:00", desired_state: "paused" });
    expect(newerSummary(older, newer)).toBe(newer);
    expect(newerSummary(newer, older)).toBe(newer);
    expect(newerSummary(older, null)).toBe(older);
  });
});

describe("event feed", () => {
  it("names and colors the FEC events the control node sends", () => {
    expect([eventLabel("fec_complete"), eventTone("fec_complete")]).toEqual(["FEC complete", "ok"]);
    expect([eventLabel("fec_abandoned"), eventTone("fec_abandoned")]).toEqual(["FEC abandoned", "bad"]);
  });

  it("joins histories and pushes by id, oldest first, with the later copy winning", () => {
    const merged = mergeEvents([event(1), event(2, "started")], [event(2, "paused"), event(3), event(0)]);
    expect(merged.map((entry) => entry.event_id)).toEqual([0, 1, 2, 3]);
    expect(merged[2].kind).toBe("paused");
  });

  it("returns the same list when nothing is added", () => {
    const existing = [event(1)];
    expect(mergeEvents(existing, [])).toBe(existing);
  });

  it("keeps only the newest events", () => {
    const many = Array.from({ length: EVENTS_KEPT + 5 }, (_, index) => event(index + 1));
    const merged = mergeEvents([], many);
    expect(merged).toHaveLength(EVENTS_KEPT);
    expect(merged[0].event_id).toBe(6);
  });

  it("reduces merges and resets, tracking the highest id", () => {
    let state = eventFeedReducer(EMPTY_EVENT_FEED, { type: "merge", events: [event(5), event(4)] });
    expect(state.events.map((entry) => entry.event_id)).toEqual([4, 5]);
    expect(state.lastId).toBe(5);
    const same = eventFeedReducer(state, { type: "merge", events: [] });
    expect(same).toBe(state);
    state = eventFeedReducer(state, { type: "merge", events: [event(6)] });
    expect(state.lastId).toBe(6);
    expect(eventFeedReducer(state, { type: "reset" })).toBe(EMPTY_EVENT_FEED);
  });

  it("lists an event's details as text", () => {
    expect(eventDetails(event(1, "desired_state_changed", { from: "paused", to: "running", extra: { a: 1 } }))).toEqual([
      { key: "from", value: "paused" },
      { key: "to", value: "running" },
      { key: "extra", value: '{"a":1}' },
    ]);
  });
});

describe("coverage rows", () => {
  const classes = [
    classView({ fec_id: "a/1", state: "open", quota: 10, complete: 2, dropped: 0, failure_budget_left: 5 }),
    classView({ fec_id: "a/2", state: "complete", quota: 10, complete: 10, dropped: 3, failure_budget_left: 1, verdicts: { "0": { passed: 9, failed: 1 }, "1": { passed: 10 } } }),
    classView({ fec_id: "b/1", state: "abandoned", quota: 10, complete: 4, dropped: 6, failure_budget_left: 0 }),
  ];

  it("counts the classes per state", () => {
    expect(countByState(classes)).toEqual({ all: 3, open: 1, complete: 1, abandoned: 1 });
  });

  it("filters by state and by a part of the class id", () => {
    expect(filterAndSortClasses(classes, { state: "all", search: "" }, "class").map((entry) => entry.fec_id)).toEqual(["a/1", "a/2", "b/1"]);
    expect(filterAndSortClasses(classes, { state: "complete", search: "" }, "class").map((entry) => entry.fec_id)).toEqual(["a/2"]);
    expect(filterAndSortClasses(classes, { state: "all", search: " B/ " }, "class").map((entry) => entry.fec_id)).toEqual(["b/1"]);
  });

  it("sorts by progress, dropped cases, failure budget left and state", () => {
    const ids = (sort: Parameters<typeof filterAndSortClasses>[2], descending = false) =>
      filterAndSortClasses(classes, { state: "all", search: "" }, sort, descending).map((entry) => entry.fec_id);
    expect(ids("progress")).toEqual(["a/1", "b/1", "a/2"]);
    expect(ids("progress", true)).toEqual(["a/2", "b/1", "a/1"]);
    expect(ids("dropped", true)).toEqual(["b/1", "a/2", "a/1"]);
    expect(ids("budget")).toEqual(["b/1", "a/2", "a/1"]);
    expect(ids("state")).toEqual(["a/1", "b/1", "a/2"]);
    expect(classProgress(classes[0])).toBe(0.2);
  });

  it("sorts an unlimited failure budget as the most left", () => {
    const unlimited = [classView({ fec_id: "u/1", failure_budget: null, failure_budget_left: null }), ...classes, classView({ fec_id: "u/2", failure_budget: null, failure_budget_left: null })];
    const ids = (descending: boolean) => filterAndSortClasses(unlimited, { state: "all", search: "" }, "budget", descending).map((entry) => entry.fec_id);
    expect(ids(false)).toEqual(["b/1", "a/2", "a/1", "u/1", "u/2"]);
    expect(ids(true)).toEqual(["u/2", "u/1", "a/1", "a/2", "b/1"]);
  });

  it("finds the runs of the verdicts and reads their counts", () => {
    expect(runIndexes(classes)).toEqual([0, 1]);
    expect(runIndexes([], 3)).toEqual([0, 1, 2]);
    expect(runVerdicts(classes[1], 0)).toEqual({ passed: 9, failed: 1, unmonitored: 0 });
    expect(runVerdicts(classes[1], 5)).toEqual({ passed: 0, failed: 0, unmonitored: 0 });
  });

  it("names the runs from the current config version", () => {
    const config = campaignConfigSchema.parse({
      current_version: 2,
      versions: [
        { version: 1, config_hash: "a", created_at: "2026-10-26T09:00:00+00:00", config: { execution: { runs: [{ name: "old" }] } } },
        { version: 2, config_hash: "b", created_at: "2026-10-26T09:10:00+00:00", config: { execution: { runs: [{ name: "usv" }, { name: null }, {}] } } },
      ],
    });
    expect(runNames(config)).toEqual(["usv", "Run 1", "Run 2"]);
    expect(runNames(null)).toEqual([]);
  });

  it("reads the base seed of the current config version", () => {
    const config = campaignConfigSchema.parse({
      current_version: 2,
      versions: [
        { version: 1, config_hash: "a", created_at: "2026-10-26T09:00:00+00:00", config: { policy: { seed: 7 } } },
        { version: 2, config_hash: "b", created_at: "2026-10-26T10:00:00+00:00", config: { policy: { seed: 20261029 } } },
      ],
    });
    expect(baseSeed(config)).toBe(20261029);
    expect(baseSeed(campaignConfigSchema.parse({ current_version: 1, versions: [{ version: 1, config_hash: "a", created_at: "2026-10-26T09:00:00+00:00", config: {} }] }))).toBeNull();
    expect(baseSeed(null)).toBeNull();
  });

  describe("which steps the config monitors", () => {
    const configWith = (config: Record<string, unknown>) =>
      campaignConfigSchema.parse({ current_version: 2, versions: [{ version: 1, config_hash: "a", created_at: "2026-10-26T09:00:00+00:00", config: {} }, { version: 2, config_hash: "b", created_at: "2026-10-26T10:00:00+00:00", config }] });

    it("reads the monitor of a generation step, off when the config stores none", () => {
      const config = configWith({ scene_generation: { monitor: "post_hoc" }, trajectories: { monitor: "empty" } });
      expect(stepMonitored(config, "scene_generation")).toBe(true);
      expect(stepMonitored(config, "trajectory_generation")).toBe(false);
      expect(stepMonitored(configWith({}), "scene_generation")).toBe(false);
      expect(stepMonitored(configWith({}), "trajectory_generation")).toBe(false);
    });

    it("monitors the simulation when any run does, a run without a monitor post hoc", () => {
      expect(stepMonitored(configWith({ execution: { runs: [{ monitor: "empty" }, { monitor: "live" }] } }), "simulation")).toBe(true);
      expect(stepMonitored(configWith({ execution: { runs: [{}] } }), "simulation")).toBe(true);
      expect(stepMonitored(configWith({ execution: { runs: [{ monitor: "empty" }] } }), "simulation")).toBe(false);
      expect(stepMonitored(configWith({}), "simulation")).toBe(false);
    });

    it("does not know without a config", () => {
      expect(stepMonitored(null, "simulation")).toBeNull();
      expect(stepMonitored(undefined, "scene_generation")).toBeNull();
    });
  });
});

describe("list view", () => {
  it("toggles state filters in the states' order and returns to the first page", () => {
    let state = listViewReducer({ ...INITIAL_LIST_VIEW, page: 3 }, { type: "toggleState", state: "stopped" });
    expect(state).toMatchObject({ states: ["stopped"], page: 0 });
    state = listViewReducer(state, { type: "toggleState", state: "running" });
    expect(state.states).toEqual(["running", "stopped"]);
    state = listViewReducer(state, { type: "toggleState", state: "stopped" });
    expect(state.states).toEqual(["running"]);
    state = listViewReducer({ ...state, page: 2 }, { type: "clearStates" });
    expect(state).toMatchObject({ states: [], page: 0 });
  });

  it("changes the page and the page size", () => {
    let state = listViewReducer(INITIAL_LIST_VIEW, { type: "setPage", page: 2 });
    expect(state.page).toBe(2);
    expect(listViewReducer(state, { type: "setPage", page: -4 }).page).toBe(0);
    state = listViewReducer(state, { type: "setPageSize", pageSize: 50 });
    expect(state).toMatchObject({ pageSize: 50, page: 0 });
  });

  it("keeps the page inside the total", () => {
    const state = { ...INITIAL_LIST_VIEW, page: 4, pageSize: 20 };
    expect(listViewReducer(state, { type: "clampPage", total: 45 }).page).toBe(2);
    expect(listViewReducer(state, { type: "clampPage", total: 0 }).page).toBe(0);
    expect(listViewReducer(state, { type: "clampPage", total: 500 })).toBe(state);
  });

  it("builds the list query", () => {
    expect(listQuery(INITIAL_LIST_VIEW)).toEqual({ limit: 20, offset: 0 });
    expect(listQuery({ states: ["running", "paused"], page: 2, pageSize: 10 })).toEqual({ state: ["running", "paused"], limit: 10, offset: 20 });
    expect(listQuery({ ...INITIAL_LIST_VIEW, kind: "workbench", step: "simulation", q: "  head " })).toEqual({ kind: "workbench", q: "head", limit: 20, offset: 0 });
    expect(listQuery({ ...INITIAL_LIST_VIEW, kind: null, q: "   " })).toEqual({ limit: 20, offset: 0 });
  });

  it("kind, step and name filters return to the first page and keep the state when unchanged", () => {
    const paged = { ...INITIAL_LIST_VIEW, page: 3 };
    expect(listViewReducer(paged, { type: "setKind", kind: "campaign" })).toMatchObject({ kind: "campaign", page: 0 });
    expect(listViewReducer(paged, { type: "setStep", step: "scene_generation" })).toMatchObject({ step: "scene_generation", page: 0 });
    expect(listViewReducer(paged, { type: "setQuery", q: "head" })).toMatchObject({ q: "head", page: 0 });
    expect(listViewReducer(paged, { type: "setKind", kind: null })).toBe(paged);
    expect(listViewReducer(paged, { type: "setQuery", q: "" })).toBe(paged);
  });

  it("describes the page", () => {
    expect(pageInfo({ page: 1, pageSize: 20 }, 20, 45)).toEqual({ from: 21, to: 40, total: 45, pages: 3, hasPrevious: true, hasNext: true });
    expect(pageInfo({ page: 2, pageSize: 20 }, 5, 45)).toMatchObject({ from: 41, to: 45, hasNext: false });
    expect(pageInfo({ page: 0, pageSize: 20 }, 0, 0)).toMatchObject({ from: 0, to: 0, pages: 1, hasNext: false, hasPrevious: false });
    expect(pageInfo({ page: 0, pageSize: 10 }, 10, null)).toMatchObject({ hasNext: true });
  });
});
