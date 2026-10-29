import { z } from "zod";

/**
 * Zod schemas of the master's operator API views. They mirror
 * `backend/src/scenegems_tool/cluster/master/api/views.py` (node, job, master status) and
 * `campaign_views.py` (campaigns, classes, cases, verdicts, run records, events). Times are
 * ISO strings as the server sends them. Enum fields that grow with the backend (job type,
 * event kind, monitor) are plain strings; the `*_VALUES` lists name the known ones.
 */

const isoTime = z.string();
const nullableTime = isoTime.nullable();
const stringMap = z.record(z.string(), z.string());
const jsonObject = z.record(z.string(), z.unknown());

export const nodeStatusSchema = z.enum(["online", "draining", "offline"]);
export const jobStateSchema = z.enum(["queued", "leased", "running", "succeeded", "failed", "cancelled"]);
export const campaignDesiredStateSchema = z.enum(["running", "paused", "draining", "stopped"]);
export const campaignActualStateSchema = z.enum([
  "created",
  "running",
  "paused",
  "draining",
  "stalled",
  "stopped",
  "completed",
]);
export const classStateSchema = z.enum(["open", "complete", "abandoned"]);
export const pipelineStageSchema = z.enum([
  "generate_scene",
  "monitor_scene",
  "generate_trajectories",
  "monitor_trajectories",
  "simulate",
  "monitor",
  "calibrate",
  "verdict",
]);
export const caseStateSchema = z.enum(["active", "complete", "dropped", "failed", "cancelled"]);
export const verdictStateSchema = z.enum(["passed", "failed", "unmonitored"]);

// Phase 6: partial campaigns (design doc 6.3). The chain a campaign runs a consecutive part of, in order.
export const CAMPAIGN_STEPS = ["scene_generation", "trajectory_generation", "simulation"] as const;
export const campaignStepSchema = z.enum(CAMPAIGN_STEPS);
/** The step a verdict belongs to: `scene` and `trajectories` verdicts have run index 0. */
export const verdictStepSchema = z.enum(["scene", "trajectories", "simulation"]);
export const campaignKindSchema = z.enum(["campaign", "workbench"]);
export const CAMPAIGN_ORIGINS = ["wizard", "cli", "scene_generation", "trajectory_generation", "simulation", "live_session"] as const;
export const campaignOriginSchema = z.enum(CAMPAIGN_ORIGINS);
/** Where a run record came from: a cluster job or a recorded live session. */
export const runSourceSchema = z.enum(["job", "live_session"]);
export type JobState = z.infer<typeof jobStateSchema>;
export type CampaignDesiredState = z.infer<typeof campaignDesiredStateSchema>;
export type CampaignActualState = z.infer<typeof campaignActualStateSchema>;
export type ClassState = z.infer<typeof classStateSchema>;
export type PipelineStage = z.infer<typeof pipelineStageSchema>;
export type CaseState = z.infer<typeof caseStateSchema>;
export type VerdictState = z.infer<typeof verdictStateSchema>;
export type CampaignStep = z.infer<typeof campaignStepSchema>;
export type VerdictStep = z.infer<typeof verdictStepSchema>;
export type CampaignKind = z.infer<typeof campaignKindSchema>;
export type CampaignOrigin = z.infer<typeof campaignOriginSchema>;

// Nodes and the master (views.py, operator_routes.py)

export const fingerprintMismatchSchema = z.object({
  image: z.string(),
  required: z.string(),
  /** Null when the node has no fingerprinted image of that name. */
  actual: z.string().nullable(),
});

export const nodeResourcesSchema = z.object({
  cpus: z.number(),
  memory_mb: z.number(),
  free_memory_mb: z.number(),
  free_disk_mb: z.number(),
  load_average: z.number().default(0),
});

export const capabilityUsageSchema = z.object({
  slots: z.number().int(),
  slots_in_use: z.number().int(),
});

export const nodeViewSchema = z.object({
  node_id: z.string(),
  name: z.string(),
  /** The machine the node runs on (P5.1); missing or null from masters before it. */
  machine: z.string().nullable().optional(),
  status: nodeStatusSchema,
  connected: z.boolean(),
  out_of_date: z.boolean(),
  fingerprint_mismatches: z.array(fingerprintMismatchSchema),
  software_revision: z.string(),
  labels: stringMap,
  resources: nodeResourcesSchema,
  /** Job type to its slots and slots in use. */
  capabilities: z.record(z.string(), capabilityUsageSchema),
  leases: z.array(z.string()),
  registered_at: isoTime,
  last_seen_at: isoTime,
});

export const nodeListSchema = z.array(nodeViewSchema);

export const masterStatusSchema = z.object({
  master_id: z.string(),
  expected_fingerprints: z.object({
    state: z.string(),
    error: z.string().nullable(),
    images: stringMap,
  }),
  connected_nodes: z.array(z.string()),
});
export type NodeView = z.infer<typeof nodeViewSchema>;
export type MasterStatus = z.infer<typeof masterStatusSchema>;

// Jobs (views.py)

export const jobRequirementsSchema = z.object({
  labels: stringMap,
  fingerprints: stringMap,
  min_memory_mb: z.number(),
  min_cpus: z.number(),
});

/** The latest status a running job reported (`JobProgress`), kept in the master's memory. */
export const jobProgressSchema = z.object({
  lease_id: z.string(),
  progress: z.number().nullable(),
  message: z.string(),
  at: isoTime,
});

export const logLineSchema = z.object({
  timestamp: isoTime,
  stream: z.string(),
  source: z.string(),
  text: z.string(),
});

export const jobViewSchema = z.object({
  job_id: z.string(),
  job_type: z.string(),
  state: jobStateSchema,
  priority: z.number().int(),
  attempt: z.number().int(),
  failed_attempts: z.number().int(),
  max_attempts: z.number().int(),
  idempotency_key: z.string(),
  requirements: jobRequirementsSchema,
  lease_owner: z.string().nullable(),
  lease_expires_at: nullableTime,
  submitted_at: isoTime,
  /** Not claimed before this time; far in the future while the job is held. */
  available_at: isoTime,
  started_at: nullableTime,
  finished_at: nullableTime,
  result: jsonObject.nullable(),
  error: z.string().nullable(),
  progress: jobProgressSchema.nullable(),
});

export const jobEventSchema = z.object({
  at: isoTime,
  kind: z.string(),
  from_state: jobStateSchema.nullable(),
  to_state: jobStateSchema,
  attempt: z.number().int(),
  lease_id: z.string().nullable(),
  node_id: z.string().nullable(),
  detail: z.unknown(),
});

export const jobDetailSchema = jobViewSchema.extend({
  payload: jsonObject,
  events: z.array(jobEventSchema),
  /** The recent log lines the master keeps (at most 200). */
  log_lines: z.array(logLineSchema),
});

export const cancelJobResultSchema = z.object({
  cancelled: z.boolean(),
  job: jobViewSchema,
});

export const nodeRemovedSchema = z.object({ removed: z.string() });
export type JobProgress = z.infer<typeof jobProgressSchema>;
export type LogLine = z.infer<typeof logLineSchema>;
export type JobView = z.infer<typeof jobViewSchema>;

export const artifactRefSchema = z.object({
  sha256: z.string(),
  size_bytes: z.number().int().nonnegative(),
  kind: z.string(),
  media_type: z.string().default("application/json"),
  /** JSON pointer into the document, such as "/trajectories"; the whole document when null. */
  pointer: z.string().nullish(),
});

export type ArtifactRef = z.infer<typeof artifactRefSchema>;

// Campaigns (campaign_views.py)

/** What a list row says about a campaign's input (6.5): the first step it runs and how many items it takes. */
export const campaignInputSummarySchema = z.object({
  first_step: campaignStepSchema,
  item_count: z.number().int().nonnegative(),
});

export const campaignSummarySchema = z.object({
  campaign_id: z.string(),
  name: z.string(),
  desired_state: campaignDesiredStateSchema,
  actual_state: campaignActualStateSchema,
  state_reason: z.string().nullable(),
  config_version: z.number().int(),
  pinned_fingerprints: stringMap,
  created_at: isoTime,
  updated_at: isoTime,
  started_at: nullableTime,
  finished_at: nullableTime,
  // Phase 6 (6.5): optional, so a master without Phase 6 still parses.
  kind: campaignKindSchema.optional(),
  /** Null for campaigns created before migration 0005, which recorded no origin. */
  origin: campaignOriginSchema.nullish(),
  steps: z.array(campaignStepSchema).optional(),
  input: campaignInputSummarySchema.optional(),
  /** Campaign ids the items of this campaign came from. */
  made_from: z.array(z.string()).optional(),
});

/** The `totals` of a list row (6.5): cases by state and verdicts by step and state. Not the detail's `campaignTotalsSchema`. */
export const campaignRowTotalsSchema = z.object({
  cases: z.record(z.string(), z.number().int()),
  verdicts: z.record(z.string(), z.record(z.string(), z.number().int())),
});

/** One row of `GET /cluster/campaigns`: the summary plus the row totals, so the list needs no detail call per row. */
export const campaignRowSchema = campaignSummarySchema.extend({
  totals: campaignRowTotalsSchema.optional(),
});

/** Run index (as a string) to verdict state to count. */
export const verdictCountsSchema = z.record(z.string(), z.record(z.string(), z.number().int()));

export const classViewSchema = z.object({
  class_id: z.string(),
  state: classStateSchema,
  state_reason: z.string().nullable(),
  content_hash: z.string(),
  vessel_count: z.number().int(),
  obstacle_count: z.number().int(),
  quota: z.number().int(),
  failure_budget: z.number().int(),
  failure_budget_left: z.number().int(),
  complete: z.number().int(),
  dropped: z.number().int(),
  in_flight: z.number().int(),
  verdicts: verdictCountsSchema,
  created_at: isoTime,
  updated_at: isoTime,
  finished_at: nullableTime,
});

export const campaignTotalsSchema = z.object({
  classes: z.number().int(),
  classes_open: z.number().int(),
  classes_complete: z.number().int(),
  classes_abandoned: z.number().int(),
  quota: z.number().int(),
  complete: z.number().int(),
  dropped: z.number().int(),
  in_flight: z.number().int(),
  /** Verdict state to count over every class and run. */
  verdicts: z.record(z.string(), z.number().int()),
});

export const campaignDetailSchema = campaignSummarySchema.extend({
  totals: campaignTotalsSchema,
  classes: z.array(classViewSchema),
});

export const caseViewSchema = z.object({
  case_id: z.number().int(),
  campaign_id: z.string(),
  class_id: z.string(),
  case_index: z.number().int(),
  seed: z.number().int(),
  config_version: z.number().int(),
  stage: pipelineStageSchema,
  state: caseStateSchema,
  scene_artifact: z.string().nullable(),
  trajectories_artifact: z.string().nullable(),
  trajectories_complete: z.boolean().nullable(),
  /** The artifact the case started from (a functional scenario or an item), null for a catalog class; an older master leaves it out. */
  input_artifact: z.string().nullish(),
  input_source: z.record(z.string(), z.unknown()).nullish(),
  reason: z.string().nullable(),
  created_at: isoTime,
  updated_at: isoTime,
  finished_at: nullableTime,
});

export const caseJobSchema = z.object({
  stage: pipelineStageSchema,
  run_index: z.number().int().nullable(),
  repeat_index: z.number().int().nullable(),
  idempotency_key: z.string(),
  job_id: z.string().nullable(),
  intent: z.boolean(),
  created_at: isoTime,
  submitted_at: nullableTime,
  job: z
    .object({
      job_type: z.string(),
      state: jobStateSchema,
      priority: z.number().int(),
      attempt: z.number().int(),
      failed_attempts: z.number().int(),
      max_attempts: z.number().int(),
      lease_owner: z.string().nullable(),
      available_at: nullableTime,
      started_at: nullableTime,
      finished_at: nullableTime,
      error: z.string().nullable(),
    })
    .nullable(),
});

export const runRecordSchema = z.object({
  run_record_id: z.number().int(),
  case_id: z.number().int(),
  /** The case's index in its class (P5.1); missing from masters before it. */
  case_index: z.number().int().optional(),
  campaign_id: z.string(),
  class_id: z.string(),
  run_index: z.number().int(),
  repeat_index: z.number().int(),
  /** Null for trajectories taken from an item or a live session (Phase 6). */
  trajectory_generator: z.string().nullable(),
  trajectories_complete: z.boolean(),
  /** Phase 6; missing from masters before it, which only ran jobs. */
  source: runSourceSchema.optional(),
  stack: jsonObject,
  repeatability_tier: z.string().nullable(),
  environment: jsonObject,
  seed: z.number().int(),
  dt: z.number().nullable(),
  steps: z.number().int().nullable(),
  state_digest: z.string().nullable(),
  /** Artifact role to sha256. */
  artifacts: stringMap,
  job_id: z.string().nullable(),
  node_id: z.string().nullable(),
  fingerprints: stringMap,
  durations_s: z.record(z.string(), z.number()),
  created_at: isoTime,
});

export const verdictSchema = z.object({
  verdict_id: z.number().int(),
  case_id: z.number().int(),
  /** The case's index in its class (P5.1); missing from masters before it. */
  case_index: z.number().int().optional(),
  campaign_id: z.string(),
  class_id: z.string(),
  /** Phase 6; missing from masters before it, whose verdicts are all of the simulation. */
  step: verdictStepSchema.optional(),
  run_index: z.number().int(),
  run_record_id: z.number().int().nullable(),
  state: verdictStateSchema,
  monitor: z.string(),
  rule_outcomes: jsonObject,
  failed_rules: z.array(z.string()),
  first_failure_time_s: z.number().nullable(),
  margin: z.number().nullable(),
  sensitive: z.boolean(),
  early_stop_time_s: z.number().nullable(),
  created_at: isoTime,
});

export const caseDetailSchema = caseViewSchema.extend({
  progress: jsonObject,
  jobs: z.array(caseJobSchema),
  run_records: z.array(runRecordSchema),
  verdicts: z.array(verdictSchema),
});

export const campaignEventSchema = z.object({
  event_id: z.number().int(),
  at: isoTime,
  kind: z.string(),
  class_id: z.string().nullable(),
  detail: jsonObject,
});

export const configVersionSchema = z.object({
  version: z.number().int(),
  config_hash: z.string(),
  created_at: isoTime,
  config: jsonObject,
});

export const campaignConfigSchema = z.object({
  current_version: z.number().int(),
  versions: z.array(configVersionSchema),
});
export type CampaignRowTotals = z.infer<typeof campaignRowTotalsSchema>;
export type CampaignRow = z.infer<typeof campaignRowSchema>;
export type CampaignSummary = z.infer<typeof campaignSummarySchema>;
export type ClassView = z.infer<typeof classViewSchema>;
export type CampaignTotals = z.infer<typeof campaignTotalsSchema>;
export type CampaignDetail = z.infer<typeof campaignDetailSchema>;
export type CaseView = z.infer<typeof caseViewSchema>;
export type CaseJob = z.infer<typeof caseJobSchema>;
export type RunRecord = z.infer<typeof runRecordSchema>;
export type Verdict = z.infer<typeof verdictSchema>;
export type CaseDetail = z.infer<typeof caseDetailSchema>;
export type CampaignEvent = z.infer<typeof campaignEventSchema>;
export type CampaignConfig = z.infer<typeof campaignConfigSchema>;
