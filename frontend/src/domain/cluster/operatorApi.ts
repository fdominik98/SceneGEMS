import type { z } from "zod";
import {
  campaignConfigSchema,
  campaignDetailSchema,
  campaignEventSchema,
  campaignSummarySchema,
  cancelJobResultSchema,
  caseDetailSchema,
  caseViewSchema,
  classViewSchema,
  jobDetailSchema,
  jobViewSchema,
  masterStatusSchema,
  nodeRemovedSchema,
  nodeViewSchema,
  runRecordSchema,
  verdictSchema,
  type CampaignActualState,
  type CaseState,
  type JobState,
  type PipelineStage,
  type VerdictState,
  type VerdictStep,
} from "./schemas";

/** A request to run one job (`JobSubmission` of `cluster/protocol/jobs.py`); the master checks the payload against its job type. */
export interface JobSubmission {
  job_type: string;
  payload: Record<string, unknown>;
  priority?: number;
  max_attempts?: number;
  idempotency_key?: string;
  /** Node ids that may run the job; empty or left out for any node. */
  allowed_nodes?: string[];
}

/**
 * Client of a master's operator API (`backend/.../cluster/master/api/operator_routes.py` and
 * `campaign_routes.py`). Every answer is checked against the schemas in `schemas.ts`; errors
 * carry the server's reasons. List calls return the `X-Total-Count` header when the server
 * sends it (and exposes it to the browser).
 */

export type OperatorErrorKind = "network" | "timeout" | "http" | "schema";

export class OperatorApiError extends Error {
  readonly kind: OperatorErrorKind;
  /** HTTP status, or null when no answer arrived. */
  readonly status: number | null;
  /** The server's reasons (a refused campaign config, a payload's validation errors). */
  readonly reasons: string[];
  readonly path: string;

  constructor(kind: OperatorErrorKind, message: string, path: string, status: number | null = null, reasons: string[] = []) {
    super(message);
    this.name = "OperatorApiError";
    this.kind = kind;
    this.status = status;
    this.reasons = reasons;
    this.path = path;
  }

  /** True when the master could not be reached at all (no tunnel, wrong URL, no CORS). */
  get unreachable(): boolean {
    return this.kind === "network" || this.kind === "timeout";
  }
}

export interface ListPage<T> {
  items: T[];
  /** `X-Total-Count`, or null when the server does not send it. */
  total: number | null;
}

type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];
export type Query = Record<string, QueryValue>;

export interface RequestOptions {
  query?: Query;
  /** Sent as JSON. */
  body?: unknown;
  /** Sent as it is with `contentType` (a file upload); instead of `body`. */
  rawBody?: Blob | ArrayBuffer | string;
  contentType?: string;
  signal?: AbortSignal;
}

export interface OperatorClientOptions {
  fetch?: typeof fetch;
  /** Abort a request that has no answer after this long. */
  timeoutMs?: number;
}

export type CampaignControl = "start" | "resume" | "pause" | "drain" | "stop";

export interface CaseFilters {
  fec_id?: string;
  state?: CaseState;
  stage?: PipelineStage;
  limit?: number;
  offset?: number;
}

/** The orders the master sorts verdicts in (Phase 7); `fec_id` is FEC, case, step and run. */
export const VERDICT_SORTS = ["fec_id", "state", "first_failure_time_s", "step", "run_index", "case_index", "created_at"] as const;
export type VerdictSort = (typeof VERDICT_SORTS)[number];

export interface VerdictFilters {
  fec_id?: string;
  state?: VerdictState;
  run_index?: number;
  sensitive?: boolean;
  /** Phase 6: the verdicts of one monitored step; without it, every step. */
  step?: VerdictStep;
  /** Phase 7: the order (`fec_id` is the default FEC, case, step, run order); an older master ignores it. */
  sort?: VerdictSort;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export interface RunRecordFilters {
  fec_id?: string;
  run_index?: number;
  limit?: number;
  offset?: number;
}

const DEFAULT_TIMEOUT_MS = 10_000;

export function buildQueryString(query: Query | undefined): string {
  if (!query) {
    return "";
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, String(item));
      }
    } else {
      params.append(key, String(value));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

function describeValidationItem(item: unknown): string {
  if (item && typeof item === "object") {
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    const where = Array.isArray(loc) ? loc.join(".") : "";
    const what = typeof msg === "string" ? msg : JSON.stringify(item);
    return where ? `${where}: ${what}` : what;
  }
  return String(item);
}

/** The message and reasons of an error answer, from FastAPI's `detail` in its three shapes. */
export function describeErrorBody(status: number, statusText: string, body: unknown): { message: string; reasons: string[] } {
  const fallback = `HTTP ${status}${statusText ? ` ${statusText}` : ""}`;
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") {
    return { message: detail, reasons: [] };
  }
  if (Array.isArray(detail)) {
    return { message: "the request is not valid", reasons: detail.map(describeValidationItem) };
  }
  if (detail && typeof detail === "object") {
    const { message, reasons, errors } = detail as { message?: unknown; reasons?: unknown; errors?: unknown };
    const list = Array.isArray(reasons) ? reasons : Array.isArray(errors) ? errors : [];
    return {
      message: typeof message === "string" ? message : fallback,
      reasons: list.map((reason) => (typeof reason === "string" ? reason : describeValidationItem(reason))),
    };
  }
  return { message: fallback, reasons: [] };
}

function readTotal(headers: Headers): number | null {
  const raw = headers.get("X-Total-Count");
  if (raw === null) {
    return null;
  }
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

export class OperatorClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(baseUrl: string, options: OperatorClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  url(path: string, query?: Query): string {
    return `${this.baseUrl}${path}${buildQueryString(query)}`;
  }

  /** One call, its answer checked against `schema`. */
  async request<S extends z.ZodType>(
    method: string,
    path: string,
    schema: S,
    options: RequestOptions = {}
  ): Promise<{ data: z.infer<S>; total: number | null }> {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, this.timeoutMs);
    const onAbort = () => controller.abort();
    options.signal?.addEventListener("abort", onAbort, { once: true });
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.rawBody !== undefined) {
      headers["Content-Type"] = options.contentType ?? "application/octet-stream";
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path, options.query), {
        method,
        headers,
        body: options.rawBody !== undefined ? options.rawBody : options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      if (timedOut) {
        throw new OperatorApiError("timeout", `${this.baseUrl} did not answer within ${Math.round(this.timeoutMs / 1000)} s`, path);
      }
      if (options.signal?.aborted) {
        throw error;
      }
      const reason = error instanceof Error ? error.message : String(error);
      throw new OperatorApiError("network", `cannot reach ${this.baseUrl} (${reason})`, path);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
    const text = await response.text();
    let body: unknown = null;
    if (text.length > 0) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!response.ok) {
      const { message, reasons } = describeErrorBody(response.status, response.statusText, body);
      throw new OperatorApiError("http", message, path, response.status, reasons);
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      const reasons = parsed.error.issues.map((issue) => `${issue.path.join(".") || "(answer)"}: ${issue.message}`);
      throw new OperatorApiError("schema", `unexpected answer from ${path}`, path, response.status, reasons);
    }
    return { data: parsed.data, total: readTotal(response.headers) };
  }

  private async get<S extends z.ZodType>(path: string, schema: S, query?: Query, signal?: AbortSignal): Promise<z.infer<S>> {
    return (await this.request("GET", path, schema, { query, signal })).data;
  }

  private async list<S extends z.ZodType>(path: string, schema: S, query?: Query, signal?: AbortSignal): Promise<ListPage<z.infer<S>>> {
    const { data, total } = await this.request("GET", path, schema.array(), { query, signal });
    return { items: data as z.infer<S>[], total };
  }

  // Master and nodes

  getStatus(signal?: AbortSignal) {
    return this.get("/cluster/status", masterStatusSchema, undefined, signal);
  }

  listNodes(signal?: AbortSignal) {
    return this.list("/cluster/nodes", nodeViewSchema, undefined, signal);
  }

  getNode(nodeId: string, signal?: AbortSignal) {
    return this.get(`/cluster/nodes/${encodeURIComponent(nodeId)}`, nodeViewSchema, undefined, signal);
  }

  /** No new jobs for the node; running ones finish. Answers the node. */
  async drainNode(nodeId: string, reason?: string) {
    const body = reason === undefined ? undefined : { reason };
    return (await this.request("POST", `/cluster/nodes/${encodeURIComponent(nodeId)}/drain`, nodeViewSchema, { body })).data;
  }

  async resumeNode(nodeId: string) {
    return (await this.request("POST", `/cluster/nodes/${encodeURIComponent(nodeId)}/resume`, nodeViewSchema)).data;
  }

  /** Forgets an offline node (the master refuses one that is not offline). Answers the removed node's id. */
  async removeNode(nodeId: string) {
    return (await this.request("POST", `/cluster/nodes/${encodeURIComponent(nodeId)}/remove`, nodeRemovedSchema)).data.removed;
  }

  // Jobs

  listJobs(filters: { state?: JobState; limit?: number } = {}, signal?: AbortSignal) {
    return this.list("/cluster/jobs", jobViewSchema, { ...filters }, signal);
  }

  getJob(jobId: string, signal?: AbortSignal) {
    return this.get(`/cluster/jobs/${encodeURIComponent(jobId)}`, jobDetailSchema, undefined, signal);
  }

  /** Submits a job (`JobSubmission` of `cluster/protocol/jobs.py`); answers the new job, or the one its idempotency key names. */
  async submitJob(submission: JobSubmission, signal?: AbortSignal) {
    return (await this.request("POST", "/cluster/jobs", jobViewSchema, { body: submission, signal })).data;
  }

  async cancelJob(jobId: string, reason?: string) {
    const body = reason === undefined ? undefined : { reason };
    return (await this.request("POST", `/cluster/jobs/${encodeURIComponent(jobId)}/cancel`, cancelJobResultSchema, { body })).data;
  }

  // Campaigns

  listCampaigns(filters: { state?: CampaignActualState[]; limit?: number; offset?: number } = {}, signal?: AbortSignal) {
    return this.list("/cluster/campaigns", campaignSummarySchema, { ...filters }, signal);
  }

  getCampaign(campaignId: string, signal?: AbortSignal) {
    return this.get(this.campaignPath(campaignId), campaignDetailSchema, undefined, signal);
  }

  listClasses(campaignId: string, signal?: AbortSignal) {
    return this.list(`${this.campaignPath(campaignId)}/fecs`, classViewSchema, undefined, signal);
  }

  listCases(campaignId: string, filters: CaseFilters = {}, signal?: AbortSignal) {
    return this.list(`${this.campaignPath(campaignId)}/cases`, caseViewSchema, { ...filters }, signal);
  }

  getCase(campaignId: string, caseId: number, signal?: AbortSignal) {
    return this.get(`${this.campaignPath(campaignId)}/cases/${caseId}`, caseDetailSchema, undefined, signal);
  }

  listVerdicts(campaignId: string, filters: VerdictFilters = {}, signal?: AbortSignal) {
    return this.list(`${this.campaignPath(campaignId)}/verdicts`, verdictSchema, { ...filters }, signal);
  }

  /** The verdicts as a CSV download link (the same filters). */
  verdictsCsvUrl(campaignId: string, filters: VerdictFilters = {}): string {
    return this.url(`${this.campaignPath(campaignId)}/verdicts`, { ...filters, format: "csv" });
  }

  listRunRecords(campaignId: string, filters: RunRecordFilters = {}, signal?: AbortSignal) {
    return this.list(`${this.campaignPath(campaignId)}/run-records`, runRecordSchema, { ...filters }, signal);
  }

  /** The audit trail after an event id, oldest first; `newest` (1 to 1000, Phase 7) answers that many of the newest events instead, still oldest first. */
  listEvents(campaignId: string, filters: { after?: number; limit?: number; newest?: number } = {}, signal?: AbortSignal) {
    return this.list(`${this.campaignPath(campaignId)}/events`, campaignEventSchema, { ...filters }, signal);
  }

  getCampaignConfig(campaignId: string, signal?: AbortSignal) {
    return this.get(`${this.campaignPath(campaignId)}/config`, campaignConfigSchema, undefined, signal);
  }

  /** Sets the desired state; answers the campaign (its actual state follows when the engine converges). */
  async controlCampaign(campaignId: string, control: CampaignControl) {
    return (await this.request("POST", `${this.campaignPath(campaignId)}/${control}`, campaignSummarySchema)).data;
  }

  // Artifacts

  /** Download link of an artifact (GET on the operator API). */
  artifactUrl(sha256: string): string {
    return this.url(`/cluster/artifacts/${encodeURIComponent(sha256)}`);
  }

  private campaignPath(campaignId: string): string {
    return `/cluster/campaigns/${encodeURIComponent(campaignId)}`;
  }
}

export function createOperatorClient(baseUrl: string, options?: OperatorClientOptions): OperatorClient {
  return new OperatorClient(baseUrl, options);
}

/** A short, readable message for an error from the client. */
export function describeOperatorError(error: unknown): string {
  if (error instanceof OperatorApiError) {
    return error.reasons.length > 0 ? `${error.message}: ${error.reasons.join("; ")}` : error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
