import { artifactRefSchema } from "./framesApi";
import type { LiveChannel } from "./liveChannel";
import { jobTopic } from "./liveProtocol";
import { jobReducer, type LiveJobStatus } from "./liveTopics";
import { LiveTopicWatcher } from "./liveTopicWatcher";
import { OperatorApiError, type OperatorClient } from "./operatorApi";
import type { JobState, JobView } from "./schemas";

/**
 * Jobs one browser runs on a cluster, outside a campaign (the workbench): follow a submitted
 * job until it ends, on the live channel's `job:<id>` topic with a REST poll beside it, and
 * read its result, whose large fields a worker node stores as artifacts (`ArtifactRef` of
 * `cluster/protocol/artifacts.py`) and the browser downloads from the operator API.
 */

export const TERMINAL_JOB_STATES: readonly JobState[] = ["succeeded", "failed", "cancelled"];

export function isTerminalJobState(state: JobState): boolean {
  return TERMINAL_JOB_STATES.includes(state);
}

/** Poll interval while the job's topic is not live, and while it is (the poll is then only a safety net). */
export const JOB_POLL_INTERVAL_MS = 2_000;
export const JOB_POLL_INTERVAL_LIVE_MS = 10_000;

export interface JobProgressEvent {
  job: JobView;
  /** The latest status message and progress the worker node reported, if any. */
  status: LiveJobStatus | null;
}

export interface FollowJobOptions {
  /** The cluster's live channel for pushed updates; the poll alone when null. */
  channel?: LiveChannel | null;
  pollIntervalMs?: number;
  livePollIntervalMs?: number;
  signal?: AbortSignal;
  /** Every view of the job seen on the way, the last one included. */
  onProgress?: (event: JobProgressEvent) => void;
}

function abortError(): Error {
  return new DOMException("The job is no longer followed.", "AbortError");
}

function statusOf(job: JobView): LiveJobStatus | null {
  return job.progress ? { progress: job.progress.progress, message: job.progress.message, at: job.progress.at } : null;
}

/**
 * Resolves with the job once it ended (succeeded, failed or cancelled). A control node that cannot
 * be reached for a while is waited out; a job the control node does not know (404) rejects.
 */
export function followJob(client: Pick<OperatorClient, "getJob">, jobId: string, options: FollowJobOptions = {}): Promise<JobView> {
  const pollIntervalMs = options.pollIntervalMs ?? JOB_POLL_INTERVAL_MS;
  const livePollIntervalMs = options.livePollIntervalMs ?? JOB_POLL_INTERVAL_LIVE_MS;
  return new Promise<JobView>((resolve, reject) => {
    let done = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let live = false;
    let unwatch: () => void = () => {};
    const poller = new AbortController();

    const finish = (settle: () => void) => {
      if (done) {
        return;
      }
      done = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      poller.abort();
      unwatch();
      options.signal?.removeEventListener("abort", onAbort);
      settle();
    };
    const consider = (job: JobView, status: LiveJobStatus | null) => {
      if (done) {
        return;
      }
      options.onProgress?.({ job, status });
      if (isTerminalJobState(job.state)) {
        finish(() => resolve(job));
      }
    };
    const onAbort = () => finish(() => reject(abortError()));

    const poll = async () => {
      timer = null;
      try {
        const job = await client.getJob(jobId, poller.signal);
        consider(job, statusOf(job));
      } catch (error) {
        if (done) {
          return;
        }
        if (error instanceof OperatorApiError && error.kind === "http" && error.status === 404) {
          finish(() => reject(error));
          return;
        }
        // The control node may be restarting or the tunnel down for a moment: keep asking.
      }
      if (!done) {
        timer = setTimeout(() => void poll(), live ? livePollIntervalMs : pollIntervalMs);
      }
    };

    if (options.signal?.aborted) {
      reject(abortError());
      return;
    }
    options.signal?.addEventListener("abort", onAbort, { once: true });
    if (options.channel) {
      const watcher = new LiveTopicWatcher(options.channel, jobTopic(jobId), jobReducer);
      unwatch = watcher.subscribe(() => {
        const state = watcher.getState();
        live = state.status === "live";
        if (state.status === "live" && state.data) {
          consider(state.data.job, state.data.status);
        }
      });
    }
    void poll();
  });
}

/** The job's reason to fail, for the user. */
export function jobFailureMessage(job: JobView): string {
  if (job.state === "cancelled") {
    return job.error ? `The job was cancelled: ${job.error}` : "The job was cancelled.";
  }
  return job.error ? `The job failed: ${job.error}` : `The job ended ${job.state}.`;
}

/** The artifact a result field references, or null for a field the worker node kept inline. */
export function artifactRefOf(value: unknown) {
  const parsed = artifactRefSchema.safeParse(value);
  if (!parsed.success || !/^[0-9a-f]{64}$/.test(parsed.data.sha256)) {
    return null;
  }
  return parsed.data;
}

/** The value at a JSON pointer ("" or none for the whole document). */
export function resolveJsonPointer(document: unknown, pointer: string | null | undefined): unknown {
  if (!pointer) {
    return document;
  }
  let current: unknown = document;
  for (const raw of pointer.slice(1).split("/")) {
    const key = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    if (Array.isArray(current)) {
      current = current[Number(key)];
    } else if (current !== null && typeof current === "object") {
      current = (current as Record<string, unknown>)[key];
    } else {
      return undefined;
    }
  }
  return current;
}

export interface ResultFieldOptions {
  fetch?: typeof fetch;
  signal?: AbortSignal;
}

/** A result field's content: inline as it is, or downloaded from the artifact it references. */
export async function readResultField(client: Pick<OperatorClient, "artifactUrl">, value: unknown, options: ResultFieldOptions = {}): Promise<unknown> {
  const ref = artifactRefOf(value);
  if (ref === null) {
    return value;
  }
  const fetchImpl = options.fetch ?? ((input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init));
  const path = `/cluster/artifacts/${ref.sha256}`;
  let response: Response;
  try {
    response = await fetchImpl(client.artifactUrl(ref.sha256), { headers: { Accept: "application/json" }, signal: options.signal });
  } catch (error) {
    if (options.signal?.aborted) {
      throw error;
    }
    throw new OperatorApiError("network", `cannot download the result (${error instanceof Error ? error.message : String(error)})`, path);
  }
  if (!response.ok) {
    throw new OperatorApiError("http", `the result artifact answered HTTP ${response.status}`, path, response.status);
  }
  let document: unknown;
  try {
    document = await response.json();
  } catch (error) {
    throw new OperatorApiError("schema", `the result artifact is not JSON (${error instanceof Error ? error.message : String(error)})`, path, response.status);
  }
  return resolveJsonPointer(document, typeof ref.pointer === "string" ? ref.pointer : null);
}
