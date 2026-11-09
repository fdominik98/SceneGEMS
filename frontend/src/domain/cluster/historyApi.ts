import { z } from "zod";
import type { ListPage, OperatorClient } from "./operatorApi";
import {
  artifactRefSchema,
  campaignRowSchema,
  campaignStepSchema,
  caseStateSchema,
  verdictStateSchema,
  type ArtifactRef,
  type CampaignActualState,
  type CampaignKind,
  type CampaignOrigin,
  type CampaignStep,
  type CaseState,
} from "./schemas";

/**
 * The Phase 6 routes of Campaign History (design doc 6.5): the entry list with its filters and
 * row fields, deleting an entry, the outputs of a step, the findings of a step, and the upload
 * of a file as an artifact. The campaign list, verdicts (`step` filter) and run records
 * (`source`) are served by `OperatorClient` and `schemas.ts`; this module reuses that client and its
 * `OperatorApiError`, and adds no second one. A master without Phase 6 answers the older list rows
 * (the new fields are optional) and 404 for the new routes.
 */

const CAMPAIGNS_PATH = "/cluster/campaigns";
const ARTIFACTS_PATH = "/cluster/artifacts";

// Entry list

export interface HistoryFilters {
  kind?: CampaignKind;
  origin?: CampaignOrigin;
  /** The name contains this text. */
  q?: string;
  state?: CampaignActualState[];
  limit?: number;
  offset?: number;
}

/** Entries (campaigns and workbench runs) newest first, one row each with kind, origin, steps, input, made-from links and totals. */
export async function listHistory(client: OperatorClient, filters: HistoryFilters = {}, signal?: AbortSignal) {
  const { data, total } = await client.request("GET", CAMPAIGNS_PATH, campaignRowSchema.array(), { query: { ...filters }, signal });
  return { items: data, total } satisfies ListPage<(typeof data)[number]>;
}

/** Deletes a final entry, its rows and references. The master answers 409 unless the campaign is final (stop it first) and 404 when it is gone. */
export async function deleteCampaign(client: OperatorClient, campaignId: string): Promise<void> {
  await client.request("DELETE", campaignPath(campaignId), z.null());
}

// Outputs of a step

/** Where an output's input came from, as the master reports it; both forms may be absent once the source entry was deleted. */
export const inputSourceSchema = z.object({
  campaign_id: z.string().optional(),
  case_id: z.number().int().optional(),
  step: z.string().optional(),
  file: z.string().optional(),
});

export const outputVerdictSchema = z.object({
  state: verdictStateSchema,
  failed_rules: z.array(z.string()),
  /** The earliest failure over all rules, in seconds. This and the two below are missing from an older master. */
  first_failure_time_s: z.number().nullable().optional(),
  /** Per vessel pair (`os - ts1`; `OS_0 - TS_1` in verdicts stored before 2026-11-09), the encounter types in order of first appearance; null for a verdict stored before them. */
  encounters: z.record(z.string(), z.array(z.string())).nullable().optional(),
  /**
   * Per vessel pair and encounter type (OTHER has none), the vessel names by role when the type first
   * appeared; null for a verdict stored before them, or when no pair met in an encounter.
   */
  encounter_roles: z
    .record(z.string(), z.record(z.string(), z.object({ give_way: z.array(z.string()), stand_on: z.array(z.string()) })))
    .nullable()
    .optional(),
});

/** One output of a step: a scene, a trajectory set or a simulated run, with the verdict of the step when it was monitored. */
export const outputRowSchema = z.object({
  case_id: z.number().int(),
  case_index: z.number().int(),
  fec_id: z.string(),
  state: caseStateSchema,
  reason: z.string().nullable(),
  /** The output: a scene, trajectory data with its pointer, or the run's trajectories. Null while the step has not produced it. */
  artifact: artifactRefSchema.nullable(),
  valid: z.boolean().nullable(),
  complete: z.boolean().nullable(),
  run_index: z.number().int().nullable(),
  repeat_index: z.number().int().nullable(),
  run_record_id: z.number().int().nullable(),
  verdict: outputVerdictSchema.nullable(),
  input_source: inputSourceSchema.nullable(),
});

export type InputSource = z.infer<typeof inputSourceSchema>;
export type OutputVerdict = z.infer<typeof outputVerdictSchema>;
export type OutputRow = z.infer<typeof outputRowSchema>;

export interface OutputFilters {
  step: CampaignStep;
  state?: CaseState;
  fec_id?: string;
  limit?: number;
  offset?: number;
}

/** The outputs of one step, a page at a time (`total` is `X-Total-Count`). */
export async function listOutputs(client: OperatorClient, campaignId: string, filters: OutputFilters, signal?: AbortSignal) {
  const { data, total } = await client.request("GET", `${campaignPath(campaignId)}/outputs`, outputRowSchema.array(), {
    query: { ...filters },
    signal,
  });
  return { items: data, total } satisfies ListPage<OutputRow>;
}

// Findings of a step

const durationSummarySchema = z.object({
  median: z.number().nullable(),
  p90: z.number().nullable(),
});

export const findingsSchema = z.object({
  step: campaignStepSchema,
  /** False for a step without monitoring: `verdicts` and `failed_rules` are then empty and the rest is statistics. */
  monitored: z.boolean(),
  /** Case state to count. */
  cases: z.record(z.string(), z.number().int()),
  outputs: z.object({ count: z.number().int(), valid: z.number().int(), complete: z.number().int() }),
  verdicts: z.object({ passed: z.number().int(), failed: z.number().int(), unmonitored: z.number().int() }),
  failed_rules: z.array(
    z.object({
      rule: z.string(),
      count: z.number().int(),
      first_failure_time_s: z.object({ min: z.number().nullable(), median: z.number().nullable() }),
    })
  ),
  /** Phase 7: vessel pairs by the first encounter type of each (COLREGSType name); missing from an older master, empty for an unmonitored step. */
  encounter_types: z.record(z.string(), z.number().int()).optional(),
  fecs: z.array(z.object({ fec_id: z.string(), cases: z.number().int(), passed: z.number().int(), failed: z.number().int() })),
  durations_s: durationSummarySchema,
});

export type Findings = z.infer<typeof findingsSchema>;

/** The monitor findings (or, unmonitored, the statistics) of one executed step. */
export async function getFindings(client: OperatorClient, campaignId: string, step: CampaignStep, signal?: AbortSignal): Promise<Findings> {
  return (await client.request("GET", `${campaignPath(campaignId)}/findings`, findingsSchema, { query: { step }, signal })).data;
}

// Uploads

/** What an uploaded file may be: the kinds the operator route accepts. */
export const UPLOAD_KINDS = ["functional_scenario", "scene", "trajectories"] as const;
export type UploadKind = (typeof UPLOAD_KINDS)[number];

/**
 * Stores a file as an artifact and answers its reference. The reference carries an `upload` hold
 * that expires after 24 hours; a campaign created with it takes over the artifact. The size limit
 * of node uploads applies (the master answers 413 beyond it).
 */
export async function uploadArtifact(
  client: OperatorClient,
  content: Blob | ArrayBuffer | string,
  kind: UploadKind,
  contentType = "application/json",
  signal?: AbortSignal
): Promise<ArtifactRef> {
  // No timeout: a large file takes as long as the link needs; the signal ends it
  return (await client.request("POST", ARTIFACTS_PATH, artifactRefSchema, { query: { kind }, rawBody: content, contentType, signal, timeoutMs: null })).data;
}

function campaignPath(campaignId: string): string {
  return `${CAMPAIGNS_PATH}/${encodeURIComponent(campaignId)}`;
}
