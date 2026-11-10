import { z } from "zod";
import { parseFrame } from "../simulation/protocol";
import type { SimulationFrame } from "../simulation/types";
import type { OperatorClient } from "./operatorApi";
import { describeOperatorError, OperatorApiError } from "./operatorApi";
import { jobViewSchema, type JobView } from "./schemas";

/**
 * A recorded run's monitor frames on demand. The control node submits a `monitoring.post_hoc` job
 * with frames over the run's stored state log (`POST .../run-records/<id>/frames`, answered
 * 201 when submitted and 200 when one exists) and answers the newest job's state to `GET` on the
 * same path; once the job succeeded, `frames` references the frames artifact, a JSON array of
 * frames in the workbench's wire format (`serialize_monitored_frame`). A failed or cancelled job
 * is returned as it is until the request is made again with `?retry=true`, which submits a new job.
 */

export const artifactRefSchema = z
  .object({
    sha256: z.string(),
    size_bytes: z.number().int().optional(),
    kind: z.string().optional(),
    media_type: z.string().optional(),
  })
  .passthrough();

export const framesRequestSchema = z.object({
  run_record_id: z.number().int(),
  job: jobViewSchema,
  /** The frames artifact once the job succeeded, else null. */
  frames: artifactRefSchema.nullable(),
});

export type ArtifactRef = z.infer<typeof artifactRefSchema>;
export type FramesRequestView = z.infer<typeof framesRequestSchema>;

export type FramesPhase =
  | { phase: "idle" }
  | { phase: "submitting" }
  /** The job is queued or leased. */
  | { phase: "submitted"; job: JobView }
  | { phase: "running"; job: JobView }
  | { phase: "downloading"; job: JobView; sizeBytes: number | null }
  | { phase: "done"; job: JobView; frames: SimulationFrame[] }
  /** 409: the run's state log is not kept (retention, or the run stored none). */
  | { phase: "unavailable"; message: string }
  /** The post-hoc job failed or was cancelled. */
  | { phase: "failed"; job: JobView; message: string }
  /** The request, the download or the parsing went wrong. */
  | { phase: "error"; message: string; unreachable: boolean };

export const FRAMES_END_PHASES: readonly FramesPhase["phase"][] = ["done", "unavailable", "failed", "error"];

export function isFramesBusy(phase: FramesPhase): boolean {
  return phase.phase !== "idle" && !FRAMES_END_PHASES.includes(phase.phase);
}

/** What the flow needs of the control node; `createFramesApi` builds it, tests use a fake. */
export interface FramesApi {
  /** `POST`: the request, submitted or found. With `retry`, a failed or cancelled job is replaced by a new one (`?retry=true`). */
  submit(signal?: AbortSignal, options?: { retry?: boolean }): Promise<FramesRequestView>;
  /** `GET`: the request's state. */
  poll(signal?: AbortSignal): Promise<FramesRequestView>;
  /** The frames artifact's JSON. */
  download(ref: ArtifactRef, signal?: AbortSignal): Promise<unknown>;
}

export function framesPath(campaignId: string, runRecordId: number): string {
  return `/cluster/campaigns/${encodeURIComponent(campaignId)}/run-records/${runRecordId}/frames`;
}

type FramesClient = Pick<OperatorClient, "request" | "artifactUrl">;

export function createFramesApi(
  client: FramesClient,
  campaignId: string,
  runRecordId: number,
  fetchImpl: typeof fetch = (input, init) => globalThis.fetch(input, init)
): FramesApi {
  const path = framesPath(campaignId, runRecordId);
  return {
    submit: async (signal, options) => (await client.request("POST", path, framesRequestSchema, { signal, query: options?.retry ? { retry: "true" } : undefined })).data,
    poll: async (signal) => (await client.request("GET", path, framesRequestSchema, { signal })).data,
    download: async (ref, signal) => {
      let response: Response;
      try {
        response = await fetchImpl(client.artifactUrl(ref.sha256), { headers: { Accept: "application/json" }, signal });
      } catch (error) {
        if (signal?.aborted) {
          throw error;
        }
        throw new OperatorApiError("network", `cannot download the frames (${error instanceof Error ? error.message : String(error)})`, path);
      }
      if (!response.ok) {
        throw new OperatorApiError("http", `the frames artifact answered HTTP ${response.status}`, path, response.status);
      }
      try {
        return await response.json();
      } catch (error) {
        throw new OperatorApiError("schema", `the frames artifact is not JSON (${error instanceof Error ? error.message : String(error)})`, path, response.status);
      }
    },
  };
}

export class FramesParseError extends Error {
  /** Index of the first frame that does not parse, or -1 for the document itself. */
  readonly index: number;

  constructor(message: string, index: number) {
    super(message);
    this.name = "FramesParseError";
    this.index = index;
  }
}

/** The frames artifact (a JSON array, or an object with `frames`) as ordered `SimulationFrame`s. */
export function parseFrames(raw: unknown): SimulationFrame[] {
  const list = Array.isArray(raw) ? raw : raw && typeof raw === "object" && Array.isArray((raw as { frames?: unknown }).frames) ? (raw as { frames: unknown[] }).frames : null;
  if (list === null) {
    throw new FramesParseError("the frames artifact is not a list of frames", -1);
  }
  const frames: SimulationFrame[] = [];
  list.forEach((entry, index) => {
    try {
      frames.push(parseFrame(entry));
    } catch (error) {
      if (error instanceof z.ZodError) {
        const issue = error.issues[0];
        const where = issue ? `${issue.path.join(".") || "(frame)"}: ${issue.message}` : "does not match the frame format";
        throw new FramesParseError(`frame ${index} ${where}`, index);
      }
      throw new FramesParseError(`frame ${index} does not parse (${error instanceof Error ? error.message : String(error)})`, index);
    }
  });
  let ordered = true;
  for (let i = 1; i < frames.length; i += 1) {
    if (frames[i].timestamp < frames[i - 1].timestamp) {
      ordered = false;
      break;
    }
  }
  return ordered ? frames : [...frames].sort((a, b) => a.timestamp - b.timestamp);
}

export interface FramesFlowOptions {
  signal?: AbortSignal;
  onUpdate?: (phase: FramesPhase) => void;
  /** Time between two polls of a job that is not done. */
  pollMs?: number;
  /** Replaced by tests; resolves early when the signal aborts. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
  /** The most polls before the flow gives up (a job that never starts). */
  maxPolls?: number;
  /** Ask again after a failed or cancelled job: the control node submits a new one instead of returning the old. */
  retry?: boolean;
}

export function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    }
    signal?.addEventListener("abort", done, { once: true });
  });
}

function phaseOfJob(view: FramesRequestView): FramesPhase | null {
  const job = view.job;
  switch (job.state) {
    case "queued":
    case "leased":
      return { phase: "submitted", job };
    case "running":
      return { phase: "running", job };
    case "failed":
      return { phase: "failed", job, message: job.error ?? "the monitoring job failed without an error" };
    case "cancelled":
      return { phase: "failed", job, message: job.error ?? "the monitoring job was cancelled" };
    case "succeeded":
      return null;
  }
}

function errorPhase(error: unknown): FramesPhase {
  if (error instanceof OperatorApiError && error.kind === "http" && error.status === 409) {
    return { phase: "unavailable", message: describeOperatorError(error) };
  }
  if (error instanceof OperatorApiError && error.kind === "http" && error.status === 404) {
    return { phase: "error", message: `${describeOperatorError(error)} (the campaign or run record is gone)`, unreachable: false };
  }
  return { phase: "error", message: describeOperatorError(error), unreachable: error instanceof OperatorApiError && error.unreachable };
}

/**
 * Requests the frames, follows the job until it ends, downloads the artifact and parses it.
 * Every step is reported to `onUpdate`; the final phase is returned (`done`, `unavailable`,
 * `failed` or `error`), or `idle` when the signal aborted first.
 */
export async function runFramesFlow(api: FramesApi, options: FramesFlowOptions = {}): Promise<FramesPhase> {
  const { signal, pollMs = 1000, sleep = abortableSleep, maxPolls = 900, retry = false } = options;
  const report = (phase: FramesPhase): FramesPhase => {
    if (!signal?.aborted) {
      options.onUpdate?.(phase);
    }
    return phase;
  };
  const stopped = () => signal?.aborted === true;

  try {
    report({ phase: "submitting" });
    let view = await api.submit(signal, retry ? { retry } : undefined);
    for (let polls = 0; ; polls += 1) {
      if (stopped()) {
        return { phase: "idle" };
      }
      const phase = phaseOfJob(view);
      if (phase !== null) {
        report(phase);
        if (phase.phase === "failed") {
          return phase;
        }
      } else {
        break;
      }
      if (polls >= maxPolls) {
        return report({ phase: "error", message: "the monitoring job did not finish in time; it keeps running, ask again later", unreachable: false });
      }
      await sleep(pollMs, signal);
      if (stopped()) {
        return { phase: "idle" };
      }
      view = await api.poll(signal);
    }
    if (view.frames === null) {
      return report({ phase: "error", message: "the monitoring job succeeded without a frames artifact", unreachable: false });
    }
    report({ phase: "downloading", job: view.job, sizeBytes: view.frames.size_bytes ?? null });
    const raw = await api.download(view.frames, signal);
    if (stopped()) {
      return { phase: "idle" };
    }
    const frames = parseFrames(raw);
    if (frames.length === 0) {
      return report({ phase: "error", message: "the frames artifact holds no frames", unreachable: false });
    }
    return report({ phase: "done", job: view.job, frames });
  } catch (error) {
    if (stopped()) {
      return { phase: "idle" };
    }
    if (error instanceof FramesParseError) {
      return report({ phase: "error", message: `the frames cannot be read: ${error.message}`, unreachable: false });
    }
    return report(errorPhase(error));
  }
}
