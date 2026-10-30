import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
import { caseDetailSchema, type CaseView } from "../../../domain/cluster/schemas";
import { sampleCampaignSummary, sampleCase } from "../../../test/fixtures/clusterViews";
import { caseEndMessage, createCaseWaiter, EntryEndedError, isGone, stageJob, waitForCase, waitForStageJob, type EntryClient } from "./entryFollower";

const noSleep = async () => undefined;

function view(overrides: Partial<CaseView>): CaseView {
  return { ...(sampleCase as unknown as CaseView), campaign_id: "wb1", ...overrides };
}

function caseJob(stage: string, jobId: string | null) {
  return {
    stage,
    run_index: null,
    repeat_index: null,
    idempotency_key: `${stage}-${jobId}`,
    job_id: jobId,
    intent: true,
    created_at: "2026-10-28T09:00:00+00:00",
    submitted_at: null,
    job: null,
  };
}

function client(pages: CaseView[][], options: { finalAfter?: number; details?: Record<string, unknown>[]; gone?: boolean } = {}): EntryClient {
  let listed = 0;
  let detailed = 0;
  return {
    listCases: async () => {
      if (options.gone) {
        throw new OperatorApiError("http", "HTTP 404", "/cluster/campaigns/wb1/cases", 404);
      }
      const items = pages[Math.min(listed, pages.length - 1)];
      listed += 1;
      return { items, total: items.length };
    },
    getCampaign: async () => ({ ...sampleCampaignSummary, actual_state: options.finalAfter !== undefined && listed > options.finalAfter ? "completed" : "running" }),
    getCase: async () => {
      const detail = (options.details ?? [])[Math.min(detailed, (options.details ?? []).length - 1)];
      detailed += 1;
      return caseDetailSchema.parse({ ...sampleCase, campaign_id: "wb1", progress: {}, jobs: [], run_records: [], verdicts: [], ...detail });
    },
  } as unknown as EntryClient;
}

describe("following an entry", () => {
  it("waits for the entry's first case of a class", async () => {
    const found = await waitForCase(client([[], [view({ case_id: 4, fec_id: "item/0" }), view({ case_id: 2, fec_id: "item/0" })]]), "wb1", "item/0", { sleep: noSleep });
    expect(found.case_id).toBe(2);
  });

  it("rejects when the entry ends without a case, and as gone when it was deleted", async () => {
    const ended = await waitForCase(client([[]], { finalAfter: 0 }), "wb1", null, { sleep: noSleep }).catch((error: unknown) => error);
    expect(ended).toBeInstanceOf(EntryEndedError);
    expect(isGone(ended)).toBe(false);
    expect(isGone(await waitForCase(client([[]], { gone: true }), "wb1", null, { sleep: noSleep }).catch((error: unknown) => error))).toBe(true);
  });

  it("stops at once when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const failure = await waitForCase(client([[]]), "wb1", null, { signal: controller.signal, sleep: noSleep }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(DOMException);
  });

  it("waits for the cases of a batch with one list per poll", async () => {
    const waiter = createCaseWaiter(client([[view({ case_id: 1, fec_id: "scenario/a" })], [view({ case_id: 1, fec_id: "scenario/a" }), view({ case_id: 2, fec_id: "scenario/b" })]]), "wb1", { sleep: noSleep });
    const [a, b] = await Promise.all([waiter.waitFor("scenario/a"), waiter.waitFor("scenario/b")]);
    expect([a.case_id, b.case_id]).toEqual([1, 2]);
  });

  it("rejects the batch rows whose cases never came", async () => {
    const waiter = createCaseWaiter(client([[view({ case_id: 1, fec_id: "scenario/a" })]], { finalAfter: 1 }), "wb1", { sleep: noSleep });
    const [a, b] = await Promise.allSettled([waiter.waitFor("scenario/a"), waiter.waitFor("scenario/b")]);
    expect(a.status).toBe("fulfilled");
    expect(b.status).toBe("rejected");
  });

  it("waits for a stage's job, or the case's end without it", async () => {
    const withJob = client([], { details: [{ jobs: [], state: "active" }, { jobs: [caseJob("generate_scene", "j1")], state: "active" }] });
    expect((await waitForStageJob(withJob, "wb1", 5, "generate_scene", { sleep: noSleep })).jobId).toBe("j1");
    const dropped = client([], { details: [{ state: "dropped", reason: "no valid scene", jobs: [] }] });
    const result = await waitForStageJob(dropped, "wb1", 5, "generate_scene", { sleep: noSleep });
    expect(result.jobId).toBeNull();
    expect(caseEndMessage(result.detail)).toBe("The entry's case ended dropped: no valid scene");
  });

  it("takes the newest submitted job of a stage", () => {
    expect(stageJob({ jobs: [caseJob("monitor", "a"), caseJob("monitor", "b"), caseJob("monitor", null)] } as never, "monitor")?.job_id).toBe("b");
    expect(stageJob({ jobs: [] } as never, "monitor")).toBeNull();
  });
});
