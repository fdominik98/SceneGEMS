/**
 * Sample operator API payloads, shaped as `cluster/control_node/api/views.py` and
 * `campaign_views.py` build them (FastAPI serializes datetimes as ISO strings).
 */

export function sampleWorkerNode(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    worker_node_id: "worker-node-a1",
    name: "worker-a",
    machine: "lab-gpu-1",
    status: "online",
    connected: true,
    out_of_date: false,
    fingerprint_mismatches: [],
    software_revision: "2c8a4001f00dbeef",
    labels: { site: "lab", gpu: "true" },
    resources: { cpus: 16, memory_mb: 32000, free_memory_mb: 20000, free_disk_mb: 250000, load_average: 0.42 },
    slots: {
      scene_generation: { slots: 4, slots_in_use: 1 },
      simulation: { slots: 8, slots_in_use: 8 },
    },
    components: [
      { component: "asv_system/replay", images: [], state: "usable" },
      { component: "control_layer/none", images: [], state: "usable" },
      { component: "simulation_layer/kinematic", images: ["scenegems-simulation-subsystem:latest"], state: "usable" },
      { component: "scene_generation", images: ["scenegems-scene-generation-subsystem:latest"], state: "usable" },
    ],
    leases: ["lease-1"],
    registered_at: "2026-10-26T08:00:00+00:00",
    last_seen_at: "2026-10-26T09:59:50+00:00",
    ...overrides,
  };
}

export const sampleControlNodeStatus = {
  control_node_id: "control-node-1",
  expected_fingerprints: {
    state: "ready",
    error: null,
    images: { "scenegems-worker-node": "sha256:aaaa", "scenegems-scene-generation": "sha256:bbbb" },
  },
  connected_worker_nodes: ["worker-node-a1"],
};

export function sampleJob(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    job_id: "job-1",
    job_type: "scene_generation",
    state: "running",
    priority: 100,
    attempt: 1,
    failed_attempts: 0,
    max_attempts: 3,
    idempotency_key: "campaign:c1:case:1:generate_scene",
    requirements: { labels: {}, components: ["scene_generation"], fingerprints: { "scenegems-worker-node": "sha256:aaaa" }, min_memory_mb: 0, min_cpus: 0 },
    lease_owner: "worker-node-a1",
    lease_expires_at: "2026-10-26T10:05:00+00:00",
    submitted_at: "2026-10-26T09:58:00+00:00",
    available_at: "2026-10-26T09:58:00+00:00",
    started_at: "2026-10-26T09:58:05+00:00",
    finished_at: null,
    result: null,
    error: null,
    progress: { lease_id: "lease-1", progress: 0.5, message: "sampling", at: "2026-10-26T09:59:00+00:00" },
    ...overrides,
  };
}

export const sampleLogLine = {
  timestamp: "2026-10-26T09:59:01+00:00",
  stream: "stdout",
  source: "scene-generation",
  text: "sample 12 valid",
};

export function sampleClass(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    fec_id: "class-a",
    state: "open",
    state_reason: null,
    content_hash: "f00d",
    vessel_count: 2,
    obstacle_count: 0,
    quota: 10,
    failure_budget: 5,
    failure_budget_left: 4,
    complete: 3,
    dropped: 1,
    in_flight: 2,
    verdicts: { "0": { passed: 2, failed: 1 } },
    created_at: "2026-10-26T09:00:00+00:00",
    updated_at: "2026-10-26T09:50:00+00:00",
    finished_at: null,
    ...overrides,
  };
}

export const sampleCampaignSummary = {
  campaign_id: "c1",
  name: "head-on sweep",
  desired_state: "running",
  actual_state: "running",
  state_reason: null,
  config_version: 1,
  pinned_fingerprints: { "scenegems-worker-node": "sha256:aaaa" },
  created_at: "2026-10-26T09:00:00+00:00",
  updated_at: "2026-10-26T09:00:10+00:00",
  started_at: "2026-10-26T09:00:10+00:00",
  finished_at: null,
};

export function sampleCampaignDetail(): Record<string, unknown> {
  return {
    ...sampleCampaignSummary,
    totals: {
      fecs: 1,
      fecs_open: 1,
      fecs_complete: 0,
      fecs_abandoned: 0,
      quota: 10,
      complete: 3,
      dropped: 1,
      in_flight: 2,
      verdicts: { passed: 2, failed: 1 },
    },
    fecs: [sampleClass()],
  };
}

export const sampleEvent = {
  event_id: 7,
  at: "2026-10-26T09:00:10+00:00",
  kind: "started",
  fec_id: null,
  detail: {},
};

export const sampleRunRecord = {
  run_record_id: 11,
  case_id: 5,
  campaign_id: "c1",
  fec_id: "class-a",
  run_index: 0,
  repeat_index: 0,
  trajectory_generator: "straight",
  trajectories_complete: true,
  stack: { simulation: "kinematic" },
  repeatability_tier: "deterministic",
  environment: {},
  seed: 42,
  dt: 0.1,
  steps: 600,
  state_digest: "abcd",
  artifacts: { state_log: "sha256:cccc" },
  job_id: "job-9",
  worker_node_id: "worker-node-a1",
  fingerprints: { "scenegems-worker-node": "sha256:aaaa" },
  durations_s: { simulate: 12.5 },
  created_at: "2026-10-26T09:30:00+00:00",
};

export const sampleVerdict = {
  verdict_id: 3,
  case_id: 5,
  campaign_id: "c1",
  fec_id: "class-a",
  run_index: 0,
  run_record_id: 11,
  state: "failed",
  monitor: "post_hoc",
  rule_outcomes: { rule_8: "failed" },
  failed_rules: ["rule_8"],
  first_failure_time_s: 31.2,
  margin: -4.1,
  sensitive: false,
  early_stop_time_s: null,
  created_at: "2026-10-26T09:31:00+00:00",
};

export const sampleCase = {
  case_id: 5,
  campaign_id: "c1",
  fec_id: "class-a",
  case_index: 2,
  seed: 42,
  config_version: 1,
  stage: "verdict",
  state: "complete",
  scene_artifact: "sha256:dddd",
  trajectories_artifact: "sha256:eeee",
  trajectories_complete: true,
  reason: null,
  created_at: "2026-10-26T09:10:00+00:00",
  updated_at: "2026-10-26T09:31:00+00:00",
  finished_at: "2026-10-26T09:31:00+00:00",
};
