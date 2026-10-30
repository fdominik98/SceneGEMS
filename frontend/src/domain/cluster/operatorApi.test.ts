import { z } from "zod";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sampleCampaignSummary, sampleMasterStatus, sampleNode } from "../../test/fixtures/clusterViews";
import { buildQueryString, createOperatorClient, describeErrorBody, describeOperatorError, OperatorApiError } from "./operatorApi";

const BASE = "http://127.0.0.1:5174";

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

function clientWith(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>, timeoutMs?: number) {
  const spy = vi.fn(fetchImpl);
  return { client: createOperatorClient(`${BASE}/`, { fetch: spy as unknown as typeof fetch, timeoutMs }), spy };
}

async function rejection(promise: Promise<unknown>): Promise<OperatorApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof OperatorApiError) {
      return error;
    }
    throw error;
  }
  throw new Error("the call did not fail");
}

afterEach(() => {
  vi.useRealTimers();
});

describe("operator API client", () => {
  it("lists nodes with X-Total-Count", async () => {
    const { client, spy } = clientWith(async () => jsonResponse([sampleNode()], { headers: { "X-Total-Count": "17" } }));
    const page = await client.listNodes();
    expect(page.total).toBe(17);
    expect(page.items[0].name).toBe("worker-a");
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/nodes`);
  });

  it("answers a null total without the header", async () => {
    const { client } = clientWith(async () => jsonResponse([sampleCampaignSummary]));
    expect((await client.listCampaigns()).total).toBeNull();
  });

  it("builds query strings with repeated keys and skips empty values", async () => {
    expect(buildQueryString({ state: ["running", "paused"], limit: 10, fec_id: undefined, sensitive: false })).toBe(
      "?state=running&state=paused&limit=10&sensitive=false"
    );
    expect(buildQueryString({})).toBe("");
    const { client, spy } = clientWith(async () => jsonResponse([]));
    await client.listVerdicts("c 1", { fec_id: "a", run_index: 0 });
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/campaigns/c%201/verdicts?fec_id=a&run_index=0`);
    expect(client.verdictsCsvUrl("c1", { state: "failed" })).toBe(`${BASE}/cluster/campaigns/c1/verdicts?state=failed&format=csv`);
  });

  it("drains and resumes a node with POST", async () => {
    const { client, spy } = clientWith(async (url) =>
      jsonResponse(sampleNode({ status: url.endsWith("/drain") ? "draining" : "online" }))
    );
    expect((await client.drainNode("node-a1", "maintenance")).status).toBe("draining");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/cluster/nodes/node-a1/drain`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ reason: "maintenance" }));
    expect((await client.resumeNode("node-a1")).status).toBe("online");
    expect(spy.mock.calls[1][1]?.body).toBeUndefined();
  });

  it("removes an offline node with POST and reports a refusal", async () => {
    const { client, spy } = clientWith(async () => jsonResponse({ removed: "node-a1" }));
    expect(await client.removeNode("node-a1")).toBe("node-a1");
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/nodes/node-a1/remove`);
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    const refused = clientWith(async () => jsonResponse({ detail: "node node-a1 is not offline; only an offline node can be removed" }, { status: 409 }));
    const error = await rejection(refused.client.removeNode("node-a1"));
    expect(error.status).toBe(409);
    expect(describeOperatorError(error)).toContain("not offline");
  });

  it("carries the server's message and reasons", async () => {
    const { client } = clientWith(async () =>
      jsonResponse({ detail: { message: "the campaign config is not valid", reasons: ["quota must be positive", "unknown stack"] } }, { status: 422 })
    );
    const error = await rejection(client.getCampaign("c1"));
    expect(error.kind).toBe("http");
    expect(error.status).toBe(422);
    expect(error.reasons).toEqual(["quota must be positive", "unknown stack"]);
    expect(describeOperatorError(error)).toBe("the campaign config is not valid: quota must be positive; unknown stack");
  });

  it("reads every shape of FastAPI's detail", () => {
    expect(describeErrorBody(404, "Not Found", { detail: "no node x" })).toEqual({ message: "no node x", reasons: [] });
    expect(describeErrorBody(422, "", { detail: [{ loc: ["query", "limit"], msg: "not an integer" }] })).toEqual({
      message: "the request is not valid",
      reasons: ["query.limit: not an integer"],
    });
    expect(describeErrorBody(422, "", { detail: { message: "bad payload", job_type: "x", errors: [{ loc: ["a"], msg: "missing" }] } })).toEqual({
      message: "bad payload",
      reasons: ["a: missing"],
    });
    expect(describeErrorBody(502, "Bad Gateway", "<html>")).toEqual({ message: "HTTP 502 Bad Gateway", reasons: [] });
  });

  it("reports an unreachable master", async () => {
    const { client } = clientWith(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await rejection(client.getStatus());
    expect(error.kind).toBe("network");
    expect(error.unreachable).toBe(true);
    expect(error.message).toContain(BASE);
  });

  it("gives up after the timeout", async () => {
    vi.useFakeTimers();
    const { client } = clientWith(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
      2000
    );
    const pending = rejection(client.getStatus());
    await vi.advanceTimersByTimeAsync(2000);
    const error = await pending;
    expect(error.kind).toBe("timeout");
    expect(error.unreachable).toBe(true);
  });

  it("refuses an answer that does not match the schema", async () => {
    const { client } = clientWith(async () => jsonResponse({ ...sampleMasterStatus, connected_nodes: "all" }));
    const error = await rejection(client.getStatus());
    expect(error.kind).toBe("schema");
    expect(error.reasons[0]).toContain("connected_nodes");
  });

  it("builds artifact links", () => {
    const client = createOperatorClient(BASE);
    expect(client.artifactUrl("abc")).toBe(`${BASE}/cluster/artifacts/abc`);
  });

  it("sends the step filter of the verdicts", async () => {
    const { client, spy } = clientWith(async () => jsonResponse([]));
    await client.listVerdicts("c1", { step: "trajectories", state: "failed" });
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/campaigns/c1/verdicts?step=trajectories&state=failed`);
  });

  it("sends a raw body with its content type instead of JSON", async () => {
    const { client, spy } = clientWith(async () => jsonResponse({ ok: true }));
    await client.request("POST", "/x", z.object({ ok: z.boolean() }), { rawBody: "a,b", contentType: "text/csv" });
    const init = spy.mock.calls[0][1];
    expect(init?.body).toBe("a,b");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("text/csv");
    await client.request("POST", "/x", z.object({ ok: z.boolean() }), { body: { a: 1 } });
    expect(spy.mock.calls[1][1]?.body).toBe('{"a":1}');
  });
});
