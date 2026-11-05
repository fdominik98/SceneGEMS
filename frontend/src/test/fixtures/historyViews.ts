import { sampleCampaignSummary, sampleCase, sampleRunRecord, sampleVerdict } from "./clusterViews";

/**
 * Sample payloads of the Phase 6 operator API (design doc 6.5) for the packages that build on
 * the contracts: Campaign History, the wizard, the workbench pages and Results. The shapes are
 * the ones `historyApi.ts` and `schemas.ts` parse. Times are ISO strings as the server sends them.
 */

export const SCENE_SHA = "a".repeat(64);
export const TRAJECTORY_DATA_SHA = "b".repeat(64);
export const STATE_LOG_SHA = "c".repeat(64);
export const SCENARIO_SHA = "d".repeat(64);

export function sampleArtifactRef(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    sha256: SCENE_SHA,
    size_bytes: 20480,
    kind: "scene",
    media_type: "application/json",
    pointer: null,
    ...overrides,
  };
}

/** A list row of a campaign made in the wizard: scene and trajectory generation, both monitored. */
export function sampleCampaignRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...sampleCampaignSummary,
    kind: "campaign",
    origin: "wizard",
    steps: ["scene_generation", "trajectory_generation"],
    input: { first_step: "scene_generation", item_count: 0 },
    made_from: [],
    totals: {
      cases: { active: 4, complete: 5, dropped: 1 },
      verdicts: { scene: { passed: 5 }, trajectories: { passed: 3, failed: 2 } },
    },
    ...overrides,
  };
}

/** A finished one-step workbench entry made from a scene of `sampleCampaignRow`. */
export function sampleWorkbenchRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...sampleCampaignSummary,
    campaign_id: "wb1",
    name: "Trajectory generation",
    desired_state: "stopped",
    actual_state: "completed",
    started_at: "2026-10-28T10:00:01+00:00",
    finished_at: "2026-10-28T10:00:20+00:00",
    kind: "workbench",
    origin: "trajectory_generation",
    steps: ["trajectory_generation"],
    input: { first_step: "trajectory_generation", item_count: 1 },
    made_from: ["c1"],
    totals: { cases: { complete: 1 }, verdicts: {} },
    ...overrides,
  };
}

/** A workbench entry still running (its live view opens on the matching workbench page). */
export function sampleRunningWorkbenchRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return sampleWorkbenchRow({
    campaign_id: "wb2",
    name: "Simulation",
    desired_state: "running",
    actual_state: "running",
    finished_at: null,
    origin: "simulation",
    steps: ["simulation"],
    input: { first_step: "simulation", item_count: 1 },
    made_from: ["wb1"],
    totals: { cases: { active: 1 }, verdicts: {} },
    ...overrides,
  });
}

/** Entries as `GET /cluster/campaigns` lists them (newest first), with `X-Total-Count` 3. */
export const sampleHistoryRows = [sampleRunningWorkbenchRow(), sampleWorkbenchRow(), sampleCampaignRow()];
export const SAMPLE_HISTORY_TOTAL = 3;

/** A list row as the master answered before Phase 6: none of the new fields. */
export const samplePreSixCampaignRow = { ...sampleCampaignSummary };

/** An output of the scene generation step: a valid scene whose monitor passed. */
export function sampleSceneOutput(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    case_id: 5,
    case_index: 2,
    fec_id: "class-a",
    state: "complete",
    reason: null,
    artifact: sampleArtifactRef(),
    valid: true,
    complete: null,
    run_index: null,
    repeat_index: null,
    run_record_id: null,
    verdict: { state: "passed", failed_rules: [] },
    input_source: null,
    ...overrides,
  };
}

/** An output of the trajectory generation step: a partial path (the step was last) that failed its monitor. */
export function sampleTrajectoryOutput(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    case_id: 6,
    case_index: 0,
    fec_id: "item/0",
    state: "complete",
    reason: null,
    artifact: sampleArtifactRef({ sha256: TRAJECTORY_DATA_SHA, kind: "trajectory_data", pointer: "/trajectories" }),
    valid: true,
    complete: false,
    run_index: null,
    repeat_index: null,
    run_record_id: null,
    verdict: { state: "failed", failed_rules: ["rule_15"] },
    input_source: { campaign_id: "c1", case_id: 5, step: "scene_generation" },
    ...overrides,
  };
}

/** An output of the simulation step: one run, with its run record. */
export function sampleSimulationOutput(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    case_id: 7,
    case_index: 0,
    fec_id: "item/0",
    state: "complete",
    reason: null,
    artifact: sampleArtifactRef({ sha256: STATE_LOG_SHA, kind: "trajectories" }),
    valid: null,
    complete: true,
    run_index: 0,
    repeat_index: 0,
    run_record_id: 11,
    verdict: null,
    input_source: { file: "head_on.json" },
    ...overrides,
  };
}

/** A verdict as a master sends it with its monitor summary: a crossing that failed, a head-on, a pair without an encounter and a vessel's own failed rule. */
export function sampleMonitorVerdict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: "failed",
    failed_rules: ["OS_0 - TS_1: Rule 16: Give-Way Vessel Takes Early and Substantial Action (TS_1)", "OS_0 - OS_0: Rule 8: Readily Apparent Course Change (OS_0)"],
    first_failure_time_s: 61,
    encounters: {
      "OS_0 - TS_10": ["OTHER"],
      "OS_0 - TS_2": ["OTHER", "HEAD_ON"],
      "OS_0 - TS_1": ["CROSSING_FROM_PORT", "OTHER"],
    },
    encounter_roles: {
      "OS_0 - TS_1": { CROSSING_FROM_PORT: { give_way: ["TS_1"], stand_on: ["OS_0"] } },
      "OS_0 - TS_2": { HEAD_ON: { give_way: ["OS_0", "TS_2"], stand_on: [] } },
    },
    ...overrides,
  };
}

/** A case a step dropped (an invalid scene): no output. */
export function sampleDroppedOutput(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return sampleSceneOutput({ case_id: 8, case_index: 3, state: "dropped", reason: "scene is not valid", artifact: null, valid: false, verdict: null, ...overrides });
}

export const sampleOutputRows = [sampleSceneOutput(), sampleDroppedOutput()];
export const SAMPLE_OUTPUTS_TOTAL = 12;

/** The findings of a monitored trajectory generation step. */
export function sampleFindings(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    step: "trajectory_generation",
    monitored: true,
    cases: { complete: 5, dropped: 1 },
    outputs: { count: 5, valid: 5, complete: 3 },
    verdicts: { passed: 3, failed: 2, unmonitored: 0 },
    failed_rules: [{ rule: "rule_15", count: 2, first_failure_time_s: { min: 12.5, median: 20.1 } }],
    encounter_types: { HEAD_ON: 4, OTHER: 2, CROSSING_FROM_PORT: 4 },
    fecs: [{ fec_id: "class-a", cases: 5, passed: 3, failed: 2 }],
    durations_s: { median: 4.2, p90: 9.8 },
    ...overrides,
  };
}

/** The statistics of an unmonitored step: verdicts and failed rules empty. */
export const sampleUnmonitoredFindings = sampleFindings({
  step: "scene_generation",
  monitored: false,
  verdicts: { passed: 0, failed: 0, unmonitored: 0 },
  failed_rules: [],
  encounter_types: {},
  durations_s: { median: null, p90: null },
});

/** A scene verdict (step `scene`, run index 0, no run record). */
export const sampleSceneVerdict = { ...sampleVerdict, verdict_id: 20, step: "scene", run_index: 0, run_record_id: null, monitor: "post_hoc" };

/** A run record of a recorded live session: no generator, source `live_session`, no job. */
export const sampleLiveRunRecord = {
  ...sampleRunRecord,
  run_record_id: 12,
  trajectory_generator: null,
  source: "live_session",
  job_id: null,
  node_id: null,
};

/** A case of a campaign that stopped after trajectory generation, with the new monitor stages. */
export const sampleMonitoredCase = { ...sampleCase, stage: "monitor_trajectories", state: "active" };

/** The reference of an uploaded scene (`POST /cluster/artifacts?kind=scene`). */
export const sampleUploadedRef = sampleArtifactRef({ sha256: SCENARIO_SHA, kind: "scene", size_bytes: 4096 });

/** A format 2 config that continues from a scene of campaign c1: trajectory generation then simulation. */
export const sampleFormat2Config = {
  format: 2,
  name: "Planned from case 5",
  steps: ["trajectory_generation", "simulation"],
  input: {
    items: [
      {
        name: "case 5 scene",
        ref: { sha256: SCENE_SHA, kind: "scene", pointer: null },
        source: { campaign_id: "c1", case_id: 5, step: "scene_generation" },
      },
      { name: "uploaded scene", ref: { sha256: SCENARIO_SHA, kind: "scene" }, source: { file: "head_on.json" } },
    ],
  },
  trajectories: { generator: "straight", timespan_s: 600, monitor: "post_hoc" },
};

/** A format 2 config that starts from a scenario given as content. */
export const sampleScenarioConfig = {
  format: 2,
  name: "Head-on scenes",
  steps: ["scene_generation"],
  input: {
    functional_scenarios: [{ name: "my_head_on", ref: { sha256: SCENARIO_SHA, kind: "functional_scenario" }, quota: 3, failure_budget: 1 }],
  },
  scene_generation: { monitor: "post_hoc" },
};

/** The `run_recording` gateway messages in the order a live session produces them. */
export const sampleRunRecordingMessages = [
  { type: "run_recording", status: "recording", campaignId: "wb3", caseId: 1, message: "Recording the run as a workbench entry" },
  { type: "run_recording", status: "saved", campaignId: "wb3", caseId: 1, message: null },
  { type: "run_recording", status: "failed", campaignId: "wb3", caseId: 1, message: "the master refused the run record" },
  { type: "run_recording", status: "unavailable", campaignId: null, caseId: null, message: "the gateway runs without a master" },
];
