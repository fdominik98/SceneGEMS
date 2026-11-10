import { describe, expect, it, vi } from "vitest";
import { sampleJob } from "../../test/fixtures/clusterViews";
import { monitoredFrame, monitoredFrames, RULE_16 } from "../../test/fixtures/monitoredFrames";
import {
  createFramesApi,
  framesPath,
  FramesParseError,
  framesRequestSchema,
  isFramesBusy,
  parseFrames,
  runFramesFlow,
  type FramesApi,
  type FramesPhase,
  type FramesRequestView,
} from "./framesApi";
import { createOperatorClient, OperatorApiError } from "./operatorApi";

const SHA = "a".repeat(64);
const REF = { sha256: SHA, size_bytes: 2048, kind: "frames", media_type: "application/json" };

function view(state: string, extra: Record<string, unknown> = {}, frames: unknown = null): FramesRequestView {
  return framesRequestSchema.parse({ run_record_id: 11, job: sampleJob({ job_type: "monitoring.post_hoc", state, ...extra }), frames });
}

function httpError(status: number, message: string): OperatorApiError {
  return new OperatorApiError("http", message, "/frames", status);
}

interface Script {
  submit?: () => Promise<FramesRequestView>;
  polls?: (FramesRequestView | Error)[];
  download?: () => Promise<unknown>;
}

function fakeApi(script: Script) {
  const polls = [...(script.polls ?? [])];
  const api: FramesApi = {
    submit: vi.fn(script.submit ?? (async () => view("queued"))),
    poll: vi.fn(async () => {
      const next = polls.shift();
      if (next === undefined) {
        throw new Error("no more scripted polls");
      }
      if (next instanceof Error) {
        throw next;
      }
      return next;
    }),
    download: vi.fn(script.download ?? (async () => monitoredFrames(3))),
  };
  return api;
}

async function run(api: FramesApi, options: Parameters<typeof runFramesFlow>[1] = {}) {
  const phases: FramesPhase[] = [];
  const final = await runFramesFlow(api, { pollMs: 0, sleep: async () => undefined, ...options, onUpdate: (phase) => phases.push(phase) });
  return { final, phases, names: phases.map((phase) => phase.phase) };
}

describe("frames request flow", () => {
  it("follows the job from submitted through running to the downloaded frames", async () => {
    const api = fakeApi({
      submit: async () => view("queued"),
      polls: [view("leased"), view("running", { progress: { lease_id: "l1", progress: 0.4, message: "monitored 20 of 50 scenes", at: "2026-10-26T09:00:00+00:00" } }), view("succeeded", {}, REF)],
    });
    const { final, names, phases } = await run(api);
    expect(names).toEqual(["submitting", "submitted", "submitted", "running", "downloading", "done"]);
    expect(final.phase).toBe("done");
    if (final.phase === "done") {
      expect(final.frames).toHaveLength(3);
      expect(final.frames[0].ruleResults[0].evaluations).toHaveLength(2);
    }
    expect(phases[4]).toMatchObject({ phase: "downloading", sizeBytes: 2048 });
    expect(api.download).toHaveBeenCalledWith(REF, undefined);
  });

  it("goes straight to the download when the request already succeeded", async () => {
    const api = fakeApi({ submit: async () => view("succeeded", {}, REF) });
    const { names } = await run(api);
    expect(names).toEqual(["submitting", "downloading", "done"]);
    expect(api.poll).not.toHaveBeenCalled();
  });

  it("is busy until it ends", () => {
    expect(isFramesBusy({ phase: "idle" })).toBe(false);
    expect(isFramesBusy({ phase: "submitting" })).toBe(true);
    expect(isFramesBusy({ phase: "running", job: view("running").job })).toBe(true);
    expect(isFramesBusy({ phase: "unavailable", message: "x" })).toBe(false);
    expect(isFramesBusy({ phase: "error", message: "x", unreachable: false })).toBe(false);
  });

  it("answers a 409 as unavailable with the control node's reason", async () => {
    const api = fakeApi({
      submit: async () => {
        throw httpError(409, "run record 11 has no state log: the campaign's retention removed it or the run kept none");
      },
    });
    const { final, names } = await run(api);
    expect(names).toEqual(["submitting", "unavailable"]);
    expect(final).toEqual({ phase: "unavailable", message: "run record 11 has no state log: the campaign's retention removed it or the run kept none" });
    expect(api.download).not.toHaveBeenCalled();
  });

  it("reports a failed job with its error and stops", async () => {
    const api = fakeApi({ submit: async () => view("queued"), polls: [view("running"), view("failed", { error: "image fingerprint mismatch" })] });
    const { final, names } = await run(api);
    expect(names).toEqual(["submitting", "submitted", "running", "failed"]);
    expect(final).toMatchObject({ phase: "failed", message: "image fingerprint mismatch" });
    expect(api.download).not.toHaveBeenCalled();
  });

  it("reports a cancelled job as failed", async () => {
    const api = fakeApi({ submit: async () => view("cancelled") });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "failed", message: "the monitoring job was cancelled" });
  });

  it("asks the control node to resubmit only when the flow is told to retry", async () => {
    const plain = fakeApi({ submit: async () => view("failed", { error: "boom" }) });
    await run(plain);
    expect(plain.submit).toHaveBeenCalledWith(undefined, undefined);

    const again = fakeApi({ submit: async () => view("queued"), polls: [view("succeeded", {}, REF)] });
    const { final, names } = await run(again, { retry: true });
    expect(again.submit).toHaveBeenCalledWith(undefined, { retry: true });
    expect(names).toEqual(["submitting", "submitted", "downloading", "done"]);
    expect(final).toMatchObject({ phase: "done" });
  });

  it("reports a job that succeeded without frames", async () => {
    const api = fakeApi({ submit: async () => view("succeeded") });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "error", message: expect.stringContaining("without a frames artifact") });
  });

  it("reports an unreachable control node as an error that says so", async () => {
    const api = fakeApi({
      submit: async () => view("queued"),
      polls: [new OperatorApiError("network", "cannot reach http://127.0.0.1:5174 (Failed to fetch)", "/frames")],
    });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "error", unreachable: true });
  });

  it("reports a missing campaign or run record", async () => {
    const api = fakeApi({
      submit: async () => {
        throw httpError(404, "no run record 11 in campaign c1");
      },
    });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "error", unreachable: false, message: expect.stringContaining("no run record 11") });
  });

  it("reports frames it cannot read, with the frame", async () => {
    const broken = monitoredFrames(3);
    delete broken[1].statesByActorId;
    const api = fakeApi({ submit: async () => view("succeeded", {}, REF), download: async () => broken });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "error", message: expect.stringContaining("frame 1") });
  });

  it("reports an artifact without frames", async () => {
    const api = fakeApi({ submit: async () => view("succeeded", {}, REF), download: async () => [] });
    const { final } = await run(api);
    expect(final).toMatchObject({ phase: "error", message: "the frames artifact holds no frames" });
  });

  it("gives up after the most polls and says the job keeps running", async () => {
    const api = fakeApi({ submit: async () => view("running"), polls: [view("running"), view("running"), view("running")] });
    const { final } = await run(api, { maxPolls: 2 });
    expect(final).toMatchObject({ phase: "error", message: expect.stringContaining("did not finish in time") });
    expect(api.poll).toHaveBeenCalledTimes(2);
  });

  it("stops quietly when the signal aborts while waiting", async () => {
    const controller = new AbortController();
    const api = fakeApi({ submit: async () => view("queued"), polls: [view("running")] });
    const { final, names } = await run(api, {
      signal: controller.signal,
      sleep: async () => controller.abort(),
    });
    expect(final).toEqual({ phase: "idle" });
    expect(names).toEqual(["submitting", "submitted"]);
    expect(api.poll).not.toHaveBeenCalled();
  });

  it("reports nothing after an abort that interrupts a request", async () => {
    const controller = new AbortController();
    const api = fakeApi({
      submit: async () => {
        controller.abort();
        throw new DOMException("aborted", "AbortError");
      },
    });
    const { final, names } = await run(api, { signal: controller.signal });
    expect(final).toEqual({ phase: "idle" });
    expect(names).toEqual(["submitting"]);
  });
});

describe("the frames API over the operator client", () => {
  function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }

  it("posts and gets the frames path of the run record and downloads the artifact", async () => {
    const seen: string[] = [];
    const operatorFetch = vi.fn(async (url: string, init?: RequestInit) => {
      seen.push(`${init?.method} ${url}`);
      return jsonResponse({ run_record_id: 11, job: sampleJob({ state: "succeeded" }), frames: REF }, init?.method === "POST" ? 201 : 200);
    });
    const artifactFetch = vi.fn(async (url: string) => {
      seen.push(`GET ${url}`);
      return jsonResponse(monitoredFrames(2));
    });
    const client = createOperatorClient("http://127.0.0.1:5174", { fetch: operatorFetch as unknown as typeof fetch });
    const api = createFramesApi(client, "camp 1", 11, artifactFetch as unknown as typeof fetch);
    const submitted = await api.submit();
    const polled = await api.poll();
    const raw = await api.download(submitted.frames!);
    expect(polled.job.state).toBe("succeeded");
    expect(parseFrames(raw)).toHaveLength(2);
    expect(framesPath("camp 1", 11)).toBe("/cluster/campaigns/camp%201/run-records/11/frames");
    expect(seen).toEqual([
      "POST http://127.0.0.1:5174/cluster/campaigns/camp%201/run-records/11/frames",
      "GET http://127.0.0.1:5174/cluster/campaigns/camp%201/run-records/11/frames",
      `GET http://127.0.0.1:5174/cluster/artifacts/${SHA}`,
    ]);
  });

  it("posts with ?retry=true only when asked to retry", async () => {
    const seen: string[] = [];
    const operatorFetch = vi.fn(async (url: string, init?: RequestInit) => {
      seen.push(`${init?.method} ${url}`);
      return jsonResponse({ run_record_id: 11, job: sampleJob({ state: "queued" }), frames: null }, 201);
    });
    const client = createOperatorClient("http://127.0.0.1:5174", { fetch: operatorFetch as unknown as typeof fetch });
    const api = createFramesApi(client, "camp 1", 11);
    await api.submit(undefined, { retry: false });
    await api.submit(undefined, { retry: true });
    await api.poll();
    const path = "http://127.0.0.1:5174/cluster/campaigns/camp%201/run-records/11/frames";
    expect(seen).toEqual([`POST ${path}`, `POST ${path}?retry=true`, `GET ${path}`]);
  });

  it("turns a 409 of the real client into the unavailable phase", async () => {
    const operatorFetch = vi.fn(async () => jsonResponse({ detail: "run record 11 has no state log: the campaign's retention removed it or the run kept none" }, 409));
    const client = createOperatorClient("http://127.0.0.1:5174", { fetch: operatorFetch as unknown as typeof fetch });
    const phases: FramesPhase[] = [];
    const final = await runFramesFlow(createFramesApi(client, "c1", 11), { onUpdate: (phase) => phases.push(phase) });
    expect(final).toMatchObject({ phase: "unavailable", message: expect.stringContaining("no state log") });
  });

  it("fails a download that answers an error status", async () => {
    const client = createOperatorClient("http://127.0.0.1:5174");
    const api = createFramesApi(client, "c1", 11, (async () => new Response("gone", { status: 404 })) as unknown as typeof fetch);
    await expect(api.download({ sha256: SHA })).rejects.toMatchObject({ kind: "http", status: 404 });
  });
});

describe("parseFrames", () => {
  it("parses frames built like serialize_monitored_frame into the workbench's frame type", () => {
    const [frame] = parseFrames([monitoredFrame({ timestamp: 4, failFrom: 3 })]);
    expect(frame.timestamp).toBe(4);
    expect(frame.actors.map((actor) => actor.name)).toEqual(["os", "ts1"]);
    expect(frame.statesByActorId["0"]).toMatchObject({ speed: 6.5, heading: 0 });
    // the backend's `rules`, `failedRuleNames` and `isFailed` become evaluations, failedRules and overallStatus
    const result = frame.ruleResults[0];
    expect(result).toMatchObject({ relationId: "0->1", overallStatus: "FAILED", failedRules: [RULE_16] });
    expect(result.evaluations.map((evaluation) => [evaluation.ruleNumber, evaluation.result, evaluation.subjectActorId])).toEqual([
      ["16", "FAILED", "0"],
      ["8", "PASSED", null],
    ]);
    // `giveWayByActorId` and the `actors...ById` states are renamed
    expect(frame.situationContexts[0].isGiveWayByActorId).toEqual({ "0": true, "1": false });
    expect(frame.colregsStates[0].rightOfStartStateByActorId).toEqual({ "0": false, "1": true });
    expect(frame.maneuverStates[0]).toMatchObject({ actorId: "0", headingChangeDirection: "NONE" });
    expect(frame.metrics?.distanceByRelationId?.["0->1"]).toBeCloseTo(372);
    expect(frame.metrics?.tcpaByRelationId?.["0->1"]).toBe(56);
  });

  it("marks a frame without a failure as not failed", () => {
    const [frame] = parseFrames([monitoredFrame({ timestamp: 1 })]);
    expect(frame.ruleResults[0]).toMatchObject({ overallStatus: "NOT_FAILED", failedRules: [] });
  });

  it("accepts an object with a frames list", () => {
    expect(parseFrames({ frames: monitoredFrames(2) })).toHaveLength(2);
  });

  it("orders frames that arrive out of order", () => {
    const frames = monitoredFrames(4);
    const shuffled = [frames[2], frames[0], frames[3], frames[1]];
    expect(parseFrames(shuffled).map((frame) => frame.timestamp)).toEqual([0, 1, 2, 3]);
  });

  it("names the first frame that does not parse", () => {
    const frames = monitoredFrames(3);
    (frames[2].actors as Record<string, unknown>[])[0].length = "long";
    expect(() => parseFrames(frames)).toThrowError(FramesParseError);
    try {
      parseFrames(frames);
    } catch (error) {
      expect(error).toMatchObject({ index: 2, message: expect.stringContaining("frame 2 actors.0.length") });
    }
  });

  it("refuses a document that is not a list of frames", () => {
    expect(() => parseFrames({ not: "frames" })).toThrowError(/not a list of frames/);
    expect(() => parseFrames("text")).toThrowError(FramesParseError);
  });
});
