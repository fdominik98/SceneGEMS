import { afterEach, describe, expect, it, vi } from "vitest";
import { sampleJob } from "../../test/fixtures/clusterViews";
import { followJob, jobFailureMessage, readResultField, resolveJsonPointer } from "./clusterJobs";
import { OperatorApiError } from "./operatorApi";
import { jobDetailSchema, jobViewSchema } from "./schemas";

const SHA = "b".repeat(64);

function detail(state: string, extra: Record<string, unknown> = {}) {
  return jobDetailSchema.parse({ ...sampleJob({ state, ...extra }), payload: {}, events: [], log_lines: [] });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("following a job", () => {
  it("polls until the job ends and reports every view on the way", async () => {
    vi.useFakeTimers();
    const states = ["queued", "running", "succeeded"];
    const client = { getJob: vi.fn(async () => detail(states.shift() ?? "succeeded")) };
    const seen: string[] = [];
    const ended = followJob(client, "j1", { pollIntervalMs: 10, onProgress: ({ job }) => seen.push(job.state) });
    await vi.runAllTimersAsync();
    expect((await ended).state).toBe("succeeded");
    expect(seen).toEqual(["queued", "running", "succeeded"]);
  });

  it("waits out an unreachable control node", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const client = {
      getJob: vi.fn(async () => {
        calls += 1;
        if (calls === 1) {
          throw new OperatorApiError("network", "cannot reach", "/cluster/jobs/j1");
        }
        return detail("failed", { error: "boom" });
      }),
    };
    const ended = followJob(client, "j1", { pollIntervalMs: 10 });
    await vi.runAllTimersAsync();
    expect((await ended).state).toBe("failed");
  });

  it("rejects a job the control node does not know", async () => {
    const client = { getJob: vi.fn(async () => Promise.reject(new OperatorApiError("http", "no job", "/cluster/jobs/x", 404))) };
    await expect(followJob(client, "x")).rejects.toThrow("no job");
  });

  it("stops following when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(followJob({ getJob: vi.fn() }, "j1", { signal: controller.signal })).rejects.toThrow();
  });
});

describe("job results", () => {
  it("keeps an inline field and downloads a referenced one", async () => {
    const client = { artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` };
    expect(await readResultField(client, { inline: true })).toEqual({ inline: true });
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ trajectories: { scene_list: [1] } }), { status: 200 }));
    const value = await readResultField(client, { sha256: SHA, size_bytes: 10, kind: "trajectory_data", pointer: "/trajectories" }, { fetch: fetchImpl as unknown as typeof fetch });
    expect(value).toEqual({ scene_list: [1] });
    expect(fetchImpl).toHaveBeenCalledWith(`http://control-node/cluster/artifacts/${SHA}`, expect.anything());
  });

  it("reports a failed download", async () => {
    const client = { artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` };
    const fetchImpl = vi.fn(async () => new Response("gone", { status: 404 }));
    await expect(readResultField(client, { sha256: SHA }, { fetch: fetchImpl as unknown as typeof fetch })).rejects.toThrow("HTTP 404");
  });

  it("resolves JSON pointers with escapes", () => {
    expect(resolveJsonPointer({ "a/b": { "c~d": [5, 6] } }, "/a~1b/c~0d/1")).toBe(6);
    expect(resolveJsonPointer({ a: 1 }, "")).toEqual({ a: 1 });
    expect(resolveJsonPointer({ a: 1 }, "/a/b")).toBeUndefined();
  });

  it("explains how a job ended", () => {
    expect(jobFailureMessage(jobViewSchema.parse(sampleJob({ state: "failed", error: "pool down" })))).toBe("The job failed: pool down");
    expect(jobFailureMessage(jobViewSchema.parse(sampleJob({ state: "cancelled", error: null })))).toBe("The job was cancelled.");
  });
});
