import { abortableSleep } from "../../../domain/cluster/framesApi";
import { OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignActualState, CaseDetail, CaseJob, CaseView, PipelineStage } from "../../../domain/cluster/schemas";

/**
 * Following a workbench entry on the control node: the engine creates the entry's case, and the case's
 * jobs one stage after the other (`generate_scene`, `monitor_scene`, ...). The workbench polls
 * the case and, once a stage has its job, follows that job like one it submitted itself.
 */

export type EntryClient = Pick<OperatorClient, "listCases" | "getCase" | "getCampaign">;

export interface EntryFollowOptions {
  signal?: AbortSignal;
  /** Between two polls of the case. */
  pollMs?: number;
  /** Replaced by tests; resolves early when the signal aborts. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

/** The entry or its case no longer exists (deleted), or ended without what the page waits for. */
export class EntryEndedError extends Error {
  readonly gone: boolean;

  constructor(message: string, gone: boolean) {
    super(message);
    this.name = "EntryEndedError";
    this.gone = gone;
  }
}

const FINAL_CAMPAIGN_STATES: readonly CampaignActualState[] = ["stopped", "completed"];

export function isGone(error: unknown): boolean {
  return (error instanceof OperatorApiError && error.status === 404) || (error instanceof EntryEndedError && error.gone);
}

function abortError(): DOMException {
  return new DOMException("Following the entry was stopped.", "AbortError");
}

function checkAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw abortError();
  }
}

async function wrapGone<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof OperatorApiError && error.status === 404) {
      throw new EntryEndedError("The entry was deleted.", true);
    }
    throw error;
  }
}

/** The entry's cases in creation order (the first page; a workbench entry has one case per scenario). */
export async function entryCases(client: EntryClient, campaignId: string, signal?: AbortSignal): Promise<CaseView[]> {
  const page = await wrapGone(() => client.listCases(campaignId, { limit: 500 }, signal));
  return [...page.items].sort((a, b) => a.case_id - b.case_id);
}

/**
 * The entry's first case of a class (any class when none is given), once the engine made it. Rejects
 * when the entry ends without one or is deleted.
 */
export async function waitForCase(client: EntryClient, campaignId: string, classId: string | null, options: EntryFollowOptions = {}): Promise<CaseView> {
  const { signal, pollMs = 1000, sleep = abortableSleep } = options;
  for (;;) {
    checkAborted(signal);
    const found = (await entryCases(client, campaignId, signal)).find((item) => classId === null || item.fec_id === classId);
    if (found) {
      return found;
    }
    const campaign = await wrapGone(() => client.getCampaign(campaignId, signal));
    if (FINAL_CAMPAIGN_STATES.includes(campaign.actual_state)) {
      throw new EntryEndedError(`The entry ended (${campaign.actual_state}) before it made a case.`, false);
    }
    await sleep(pollMs, signal);
  }
}

/**
 * Waits for the cases of several classes of one entry with one poll of the case list (a batch
 * entry has a case per scenario). Every waiter rejects when the entry ends without its case.
 */
export function createCaseWaiter(client: EntryClient, campaignId: string, options: EntryFollowOptions = {}) {
  const { signal, pollMs = 1000, sleep = abortableSleep } = options;
  const waiters = new Map<string, { resolve: (view: CaseView) => void; reject: (error: unknown) => void }>();
  let running = false;

  const settle = (cases: CaseView[]) => {
    for (const [classId, waiter] of [...waiters]) {
      const found = cases.find((item) => item.fec_id === classId);
      if (found) {
        waiters.delete(classId);
        waiter.resolve(found);
      }
    }
  };
  const rejectAll = (error: unknown) => {
    for (const waiter of waiters.values()) {
      waiter.reject(error);
    }
    waiters.clear();
  };
  const loop = async () => {
    running = true;
    try {
      while (waiters.size > 0) {
        checkAborted(signal);
        settle(await entryCases(client, campaignId, signal));
        if (waiters.size === 0) {
          break;
        }
        const campaign = await wrapGone(() => client.getCampaign(campaignId, signal));
        if (FINAL_CAMPAIGN_STATES.includes(campaign.actual_state)) {
          throw new EntryEndedError(`The entry ended (${campaign.actual_state}) before it made this case.`, false);
        }
        await sleep(pollMs, signal);
      }
    } catch (error) {
      rejectAll(error);
    } finally {
      running = false;
    }
  };

  return {
    /** The first case of a class. */
    waitFor(classId: string): Promise<CaseView> {
      const promise = new Promise<CaseView>((resolve, reject) => waiters.set(classId, { resolve, reject }));
      if (!running) {
        void loop();
      }
      return promise;
    },
  };
}

/** The newest job of a stage in a case, null while the engine has not submitted one. */
export function stageJob(detail: Pick<CaseDetail, "jobs">, stage: PipelineStage): CaseJob | null {
  const jobs = detail.jobs.filter((job) => job.stage === stage && job.job_id !== null);
  return jobs.length === 0 ? null : jobs[jobs.length - 1];
}

/** Whether a case will not change any more. */
export function isCaseFinal(view: Pick<CaseView, "state">): boolean {
  return view.state !== "active";
}

/**
 * Polls a case until `ready` returns a value (a stage's job, a run record), or the case ends
 * without it (null). Each poll's detail goes to `onDetail`.
 */
export async function pollCase<T>(
  client: EntryClient,
  campaignId: string,
  caseId: number,
  ready: (detail: CaseDetail) => T | null,
  options: EntryFollowOptions & { onDetail?: (detail: CaseDetail) => void } = {}
): Promise<{ value: T | null; detail: CaseDetail }> {
  const { signal, pollMs = 1000, sleep = abortableSleep } = options;
  for (;;) {
    checkAborted(signal);
    const detail = await wrapGone(() => client.getCase(campaignId, caseId, signal));
    options.onDetail?.(detail);
    const value = ready(detail);
    if (value !== null || isCaseFinal(detail)) {
      return { value, detail };
    }
    await sleep(pollMs, signal);
  }
}

/** The job id of a stage once the engine submitted it, null when the case ended without one. */
export async function waitForStageJob(client: EntryClient, campaignId: string, caseId: number, stage: PipelineStage, options: EntryFollowOptions = {}) {
  const { value, detail } = await pollCase(client, campaignId, caseId, (current) => stageJob(current, stage)?.job_id ?? null, options);
  return { jobId: value, detail };
}

/** The case once it ended. */
export async function waitForCaseEnd(client: EntryClient, campaignId: string, caseId: number, options: EntryFollowOptions = {}): Promise<CaseDetail> {
  return (await pollCase(client, campaignId, caseId, () => null, options)).detail;
}

/** What the page says about a case that ended without the output it waited for. */
export function caseEndMessage(detail: Pick<CaseView, "state" | "reason">): string {
  return detail.reason ? `The entry's case ended ${detail.state}: ${detail.reason}` : `The entry's case ended ${detail.state}.`;
}
