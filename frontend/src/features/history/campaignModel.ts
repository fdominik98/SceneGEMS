import type { CampaignControl } from "../../domain/cluster/operatorApi";
import type {
  CampaignActualState,
  CampaignConfig,
  CampaignKind,
  CampaignStep,
  CampaignDesiredState,
  CampaignEvent,
  CampaignSummary,
  CampaignTotals,
  ClassState,
  ClassView,
} from "../../domain/cluster/schemas";

/**
 * What Campaign History shows of campaigns, as pure functions and reducers: state labels and
 * tones, progress, which controls apply, the event feed, the coverage rows and the list view.
 */

export type Tone = "ok" | "warn" | "bad" | "info" | "idle";

export const ACTUAL_STATES: readonly CampaignActualState[] = ["created", "running", "paused", "draining", "stalled", "stopped", "completed"];

export const ACTUAL_STATE_LABELS: Record<CampaignActualState, string> = {
  created: "Created",
  running: "Running",
  paused: "Paused",
  draining: "Draining",
  stalled: "Stalled",
  stopped: "Stopped",
  completed: "Completed",
};

export const ACTUAL_STATE_HINTS: Record<CampaignActualState, string> = {
  created: "Waiting for its first start.",
  running: "Cases are being generated, simulated and judged.",
  paused: "No new cases; queued jobs are held.",
  draining: "Started cases finish, no new ones begin.",
  stalled: "Running as asked, but the engine cannot make progress.",
  stopped: "Stopped by an operator or a stop condition. Final.",
  completed: "Every FEC is complete or abandoned. Final.",
};

export const DESIRED_STATE_LABELS: Record<CampaignDesiredState, string> = {
  running: "run",
  paused: "pause",
  draining: "drain",
  stopped: "stop",
};

export function actualStateTone(state: CampaignActualState): Tone {
  switch (state) {
    case "running":
      return "ok";
    case "completed":
      return "info";
    case "stalled":
      return "bad";
    case "draining":
    case "paused":
      return "warn";
    default:
      return "idle";
  }
}

export function isFinalState(state: CampaignActualState): boolean {
  return state === "stopped" || state === "completed";
}

/** Whether the desired state differs from where the campaign is on its way to (the engine has not converged yet). */
export function isConverging(summary: Pick<CampaignSummary, "desired_state" | "actual_state">): boolean {
  if (isFinalState(summary.actual_state)) {
    return false;
  }
  const reached: Record<CampaignDesiredState, readonly CampaignActualState[]> = {
    running: ["running", "stalled"],
    paused: ["paused", "created"],
    draining: ["draining"],
    stopped: ["stopped"],
  };
  return !reached[summary.desired_state].includes(summary.actual_state);
}

export interface Progress {
  complete: number;
  quota: number;
  dropped: number;
  inFlight: number;
  /** Complete cases as a share of the quota, in [0, 1]. */
  fraction: number;
}

export function campaignProgress(totals: Pick<CampaignTotals, "complete" | "quota" | "dropped" | "in_flight"> | null | undefined): Progress {
  const quota = totals?.quota ?? 0;
  const complete = totals?.complete ?? 0;
  return {
    complete,
    quota,
    dropped: totals?.dropped ?? 0,
    inFlight: totals?.in_flight ?? 0,
    fraction: quota > 0 ? Math.min(1, Math.max(0, complete / quota)) : 0,
  };
}

// Controls

export interface ControlSpec {
  control: CampaignControl;
  label: string;
  /** What the control does, in a sentence. */
  description: string;
  /** Asks for confirmation first. */
  confirm: boolean;
  tone: "primary" | "normal" | "danger";
}

export const CONTROL_SPECS: readonly ControlSpec[] = [
  { control: "start", label: "Start", description: "Begins the campaign: cases are generated, simulated and judged until every FEC is complete or abandoned.", confirm: false, tone: "primary" },
  { control: "pause", label: "Pause", description: "Holds the queued jobs and starts no new cases. Running jobs finish. Resume continues.", confirm: false, tone: "normal" },
  { control: "drain", label: "Drain", description: "Lets the cases already started finish and begins no new ones. Resume continues.", confirm: false, tone: "normal" },
  { control: "resume", label: "Resume", description: "Continues a paused or draining campaign.", confirm: false, tone: "primary" },
  { control: "stop", label: "Stop", description: "Ends the campaign for good. Queued jobs are cancelled and it cannot be started again.", confirm: true, tone: "danger" },
];

export interface ControlAvailability {
  enabled: boolean;
  /** Why the control is not available, or null. */
  reason: string | null;
}

/** Which controls apply to a campaign in its state; the master refuses the others with a 409 as well. */
/** What each control may do now; a start blocker (no machine for a needed capability) keeps Start and Resume off. */
export function controlAvailability(
  summary: Pick<CampaignSummary, "desired_state" | "actual_state" | "started_at">,
  startBlocker: string | null = null
): Record<CampaignControl, ControlAvailability> {
  const yes: ControlAvailability = { enabled: true, reason: null };
  const no = (reason: string): ControlAvailability => ({ enabled: false, reason });
  if (isFinalState(summary.actual_state)) {
    const finished = no(`The campaign is ${summary.actual_state}; a finished campaign cannot be changed.`);
    return { start: finished, resume: finished, pause: finished, drain: finished, stop: finished };
  }
  if (summary.desired_state === "stopped") {
    const stopping = no("The campaign is stopping; a stop cannot be undone.");
    return { start: stopping, resume: stopping, pause: stopping, drain: stopping, stop: stopping };
  }
  const neverStarted = summary.started_at === null;
  const wantsRunning = summary.desired_state === "running";
  const startable = startBlocker === null ? yes : no(`It cannot start: ${startBlocker}`);
  return {
    start: wantsRunning ? no("The campaign is asked to run already.") : neverStarted ? startable : no("It has started before; use Resume."),
    resume: wantsRunning ? no("The campaign is asked to run already.") : neverStarted ? no("It has not started yet; use Start.") : startable,
    pause: summary.desired_state === "paused" ? no("The campaign is paused already.") : yes,
    drain: summary.desired_state === "draining" ? no("The campaign is draining already.") : yes,
    stop: yes,
  };
}

/** The summary that is newer by `updated_at` (an answer to a control, against what the live channel last sent). */
export function newerSummary<T extends Pick<CampaignSummary, "updated_at">>(a: T, b: T | null | undefined): T {
  if (!b) {
    return a;
  }
  return Date.parse(b.updated_at) > Date.parse(a.updated_at) ? b : a;
}

// Events

export const EVENTS_KEPT = 1000;

export interface EventFeedState {
  /** Oldest first, each event once. */
  events: CampaignEvent[];
  /** The highest event id seen. */
  lastId: number;
}

export type EventFeedAction =
  | { type: "merge"; events: readonly CampaignEvent[] }
  | { type: "reset" };

export const EMPTY_EVENT_FEED: EventFeedState = { events: [], lastId: 0 };

/** Joins two event lists by id (the later list wins), oldest first, keeping the newest `EVENTS_KEPT`. */
export function mergeEvents(existing: readonly CampaignEvent[], incoming: readonly CampaignEvent[]): CampaignEvent[] {
  if (incoming.length === 0) {
    return existing as CampaignEvent[];
  }
  const byId = new Map<number, CampaignEvent>();
  for (const event of existing) {
    byId.set(event.event_id, event);
  }
  for (const event of incoming) {
    byId.set(event.event_id, event);
  }
  const merged = [...byId.values()].sort((a, b) => a.event_id - b.event_id);
  return merged.length > EVENTS_KEPT ? merged.slice(merged.length - EVENTS_KEPT) : merged;
}

export function eventFeedReducer(state: EventFeedState, action: EventFeedAction): EventFeedState {
  if (action.type === "reset") {
    return EMPTY_EVENT_FEED;
  }
  const events = mergeEvents(state.events, action.events);
  if (events === state.events) {
    return state;
  }
  return { events, lastId: events.length > 0 ? events[events.length - 1].event_id : state.lastId };
}

const EVENT_LABELS: Record<string, string> = {
  created: "Created",
  desired_state_changed: "Asked to change state",
  started: "Started",
  paused: "Paused",
  resumed: "Resumed",
  draining: "Draining",
  stalled: "Stalled",
  stopped: "Stopped",
  completed: "Completed",
  fec_complete: "FEC complete",
  fec_abandoned: "FEC abandoned",
  engine_started: "Engine started",
  note: "Note",
};

export function eventLabel(kind: string): string {
  return EVENT_LABELS[kind] ?? kind.replace(/_/g, " ");
}

export function eventTone(kind: string): Tone {
  switch (kind) {
    case "started":
    case "resumed":
    case "fec_complete":
      return "ok";
    case "completed":
      return "info";
    case "stalled":
    case "fec_abandoned":
    case "stopped":
      return "bad";
    case "paused":
    case "draining":
      return "warn";
    default:
      return "idle";
  }
}

/** The details of an event as short `key: value` pairs (objects as JSON). */
export function eventDetails(event: CampaignEvent): { key: string; value: string }[] {
  return Object.entries(event.detail).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

// Coverage

export type ClassFilter = "all" | ClassState;

export interface CoverageFilter {
  state: ClassFilter;
  search: string;
}

export type CoverageSortKey = "class" | "progress" | "state" | "dropped" | "budget";

export const COVERAGE_PAGE = 100;

/** The run indexes any class has verdicts for, plus the runs the config names, ascending. */
export function runIndexes(classes: readonly ClassView[], runCount = 0): number[] {
  const found = new Set<number>();
  for (let index = 0; index < runCount; index += 1) {
    found.add(index);
  }
  for (const entry of classes) {
    for (const key of Object.keys(entry.verdicts)) {
      const index = Number(key);
      if (Number.isInteger(index)) {
        found.add(index);
      }
    }
  }
  return [...found].sort((a, b) => a - b);
}

export function classProgress(entry: Pick<ClassView, "complete" | "quota">): number {
  return entry.quota > 0 ? Math.min(1, entry.complete / entry.quota) : 0;
}

const STATE_ORDER: Record<ClassState, number> = { open: 0, abandoned: 1, complete: 2 };

/** The failure budget a class has left; an unlimited one has the most. */
function budgetLeft(entry: ClassView): number {
  return entry.failure_budget_left ?? Number.MAX_SAFE_INTEGER;
}

export function filterAndSortClasses(classes: readonly ClassView[], filter: CoverageFilter, sort: CoverageSortKey, descending = false): ClassView[] {
  const needle = filter.search.trim().toLowerCase();
  const kept = classes.filter((entry) => (filter.state === "all" || entry.state === filter.state) && (needle === "" || entry.fec_id.toLowerCase().includes(needle)));
  const compare = (a: ClassView, b: ClassView): number => {
    switch (sort) {
      case "progress":
        return classProgress(a) - classProgress(b);
      case "state":
        return STATE_ORDER[a.state] - STATE_ORDER[b.state];
      case "dropped":
        return a.dropped - b.dropped;
      case "budget":
        return budgetLeft(a) - budgetLeft(b);
      default:
        return 0;
    }
  };
  // The sort is stable, so equal keys stay in the campaign's class order
  const sorted = sort === "class" ? [...kept] : [...kept].sort(compare);
  return descending ? sorted.reverse() : sorted;
}

export function countByState(classes: readonly ClassView[]): Record<ClassFilter, number> {
  const counts: Record<ClassFilter, number> = { all: classes.length, open: 0, complete: 0, abandoned: 0 };
  for (const entry of classes) {
    counts[entry.state] += 1;
  }
  return counts;
}

export const VERDICT_STATES = ["passed", "failed", "unmonitored"] as const;

/** The verdict counts of one run of a class, by state (zero for missing). */
export function runVerdicts(entry: Pick<ClassView, "verdicts">, runIndex: number): Record<(typeof VERDICT_STATES)[number], number> {
  const counts = entry.verdicts[String(runIndex)] ?? {};
  return { passed: counts.passed ?? 0, failed: counts.failed ?? 0, unmonitored: counts.unmonitored ?? 0 };
}

function currentVersion(config: CampaignConfig) {
  return config.versions.find((version) => version.version === config.current_version) ?? config.versions[config.versions.length - 1];
}

/** The names of a campaign's runs from its current config version (an unnamed run gets "Run <index>"). */
export function runNames(config: CampaignConfig | null | undefined): string[] {
  if (!config) {
    return [];
  }
  const execution = currentVersion(config)?.config.execution as { runs?: { name?: string | null }[] } | undefined;
  return (execution?.runs ?? []).map((run, index) => (run.name ? run.name : `Run ${index}`));
}

/** The base seed of the current config version: case k of every FEC runs with it + k. */
export function baseSeed(config: CampaignConfig | null | undefined): number | null {
  if (!config) {
    return null;
  }
  const seed = (currentVersion(config)?.config.policy as { seed?: unknown } | undefined)?.seed;
  return typeof seed === "number" ? seed : null;
}

/**
 * Whether the current config version monitors a step, or null without a config. As the master reads
 * it: a generation step when its monitor is not empty (a format 1 config stores none), the simulation
 * when any run's is (a run without one is monitored post hoc).
 */
export function stepMonitored(config: CampaignConfig | null | undefined, step: CampaignStep): boolean | null {
  if (!config) {
    return null;
  }
  const values = (currentVersion(config)?.config ?? {}) as {
    scene_generation?: { monitor?: string };
    trajectories?: { monitor?: string };
    execution?: { runs?: { monitor?: string }[] };
  };
  switch (step) {
    case "scene_generation":
      return (values.scene_generation?.monitor ?? "empty") !== "empty";
    case "trajectory_generation":
      return (values.trajectories?.monitor ?? "empty") !== "empty";
    case "simulation":
      return (values.execution?.runs ?? []).some((run) => (run.monitor ?? "post_hoc") !== "empty");
  }
}

// The list view

export const LIST_PAGE_SIZES = [10, 20, 50] as const;

export interface ListViewState {
  /** Actual states to show; empty shows every campaign. */
  states: CampaignActualState[];
  /** Only campaigns or only workbench runs; absent shows both. */
  kind?: CampaignKind | null;
  /** Only entries that run this step; absent shows every entry. */
  step?: CampaignStep | null;
  /** The name contains this text. */
  q?: string;
  page: number;
  pageSize: number;
}

export type ListViewAction =
  | { type: "toggleState"; state: CampaignActualState }
  | { type: "clearStates" }
  | { type: "setKind"; kind: CampaignKind | null }
  | { type: "setStep"; step: CampaignStep | null }
  | { type: "setQuery"; q: string }
  | { type: "setPage"; page: number }
  | { type: "setPageSize"; pageSize: number }
  /** The total shrank (an entry was deleted, the filter or the cluster changed): keep the page inside it. */
  | { type: "clampPage"; total: number };

export const INITIAL_LIST_VIEW: ListViewState = { states: [], page: 0, pageSize: 20 };

export function listViewReducer(state: ListViewState, action: ListViewAction): ListViewState {
  switch (action.type) {
    case "toggleState": {
      const states = state.states.includes(action.state) ? state.states.filter((entry) => entry !== action.state) : [...state.states, action.state];
      return { ...state, states: ACTUAL_STATES.filter((entry) => states.includes(entry)), page: 0 };
    }
    case "clearStates":
      return state.states.length === 0 ? state : { ...state, states: [], page: 0 };
    case "setKind":
      return (state.kind ?? null) === action.kind ? state : { ...state, kind: action.kind, page: 0 };
    case "setStep":
      return (state.step ?? null) === action.step ? state : { ...state, step: action.step, page: 0 };
    case "setQuery":
      return (state.q ?? "") === action.q ? state : { ...state, q: action.q, page: 0 };
    case "setPage":
      return { ...state, page: Math.max(0, action.page) };
    case "setPageSize":
      return { ...state, pageSize: action.pageSize, page: 0 };
    case "clampPage": {
      const last = Math.max(0, Math.ceil(action.total / state.pageSize) - 1);
      return state.page > last ? { ...state, page: last } : state;
    }
  }
}

/**
 * The query the list route takes for a list view. The route has no step filter, so `step` is
 * applied to the rows of the page (`matchesListView`).
 */
export function listQuery(state: ListViewState): { state?: CampaignActualState[]; kind?: CampaignKind; q?: string; limit: number; offset: number } {
  const q = state.q?.trim() ?? "";
  return {
    ...(state.states.length > 0 ? { state: state.states } : {}),
    ...(state.kind ? { kind: state.kind } : {}),
    ...(q !== "" ? { q } : {}),
    limit: state.pageSize,
    offset: state.page * state.pageSize,
  };
}

export interface PageInfo {
  from: number;
  to: number;
  total: number;
  pages: number;
  hasPrevious: boolean;
  hasNext: boolean;
}

export function pageInfo(state: Pick<ListViewState, "page" | "pageSize">, shown: number, total: number | null): PageInfo {
  const known = total ?? state.page * state.pageSize + shown;
  const pages = Math.max(1, Math.ceil(known / state.pageSize));
  return {
    from: shown === 0 ? 0 : state.page * state.pageSize + 1,
    to: state.page * state.pageSize + shown,
    total: known,
    pages,
    hasPrevious: state.page > 0,
    hasNext: total === null ? shown === state.pageSize : (state.page + 1) * state.pageSize < total,
  };
}
