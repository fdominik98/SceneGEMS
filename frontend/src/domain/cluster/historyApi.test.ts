import { describe, expect, it, vi } from "vitest";
import {
  SAMPLE_HISTORY_TOTAL,
  SAMPLE_OUTPUTS_TOTAL,
  sampleDroppedOutput,
  sampleFindings,
  sampleHistoryRows,
  samplePreSixCampaignRow,
  sampleOutputRows,
  sampleSimulationOutput,
  sampleTrajectoryOutput,
  sampleUnmonitoredFindings,
  sampleUploadedRef,
} from "../../test/fixtures/historyViews";
import {
  deleteCampaign,
  findingsSchema,
  getFindings,
  listHistory,
  listOutputs,
  outputRowSchema,
  uploadArtifact,
} from "./historyApi";
import { createOperatorClient, OperatorApiError } from "./operatorApi";

const BASE = "http://127.0.0.1:5174";

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

function clientWith(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>) {
  const spy = vi.fn(fetchImpl);
  return { client: createOperatorClient(BASE, { fetch: spy as unknown as typeof fetch }), spy };
}

describe("listHistory", () => {
  it("reads the entries with the filters in the query and the total of the header", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleHistoryRows, { headers: { "X-Total-Count": String(SAMPLE_HISTORY_TOTAL) } }));
    const page = await listHistory(client, { kind: "workbench", origin: "simulation", q: "head", state: ["running", "completed"], limit: 25, offset: 50 });
    expect(page.total).toBe(SAMPLE_HISTORY_TOTAL);
    expect(page.items.map((row) => row.campaign_id)).toEqual(["wb2", "wb1", "c1"]);
    const url = new URL(spy.mock.calls[0][0]);
    expect(url.pathname).toBe("/cluster/campaigns");
    expect(url.searchParams.get("kind")).toBe("workbench");
    expect(url.searchParams.get("origin")).toBe("simulation");
    expect(url.searchParams.get("q")).toBe("head");
    expect(url.searchParams.getAll("state")).toEqual(["running", "completed"]);
    expect(url.searchParams.get("limit")).toBe("25");
    expect(url.searchParams.get("offset")).toBe("50");
  });

  it("carries the new row fields", async () => {
    const { client } = clientWith(async () => jsonResponse(sampleHistoryRows));
    const [running, workbench, campaign] = (await listHistory(client)).items;
    expect(running.actual_state).toBe("running");
    expect(workbench.kind).toBe("workbench");
    expect(workbench.origin).toBe("trajectory_generation");
    expect(workbench.made_from).toEqual(["c1"]);
    expect(workbench.input).toEqual({ first_step: "trajectory_generation", item_count: 1 });
    expect(campaign.steps).toEqual(["scene_generation", "trajectory_generation"]);
    expect(campaign.totals?.verdicts.trajectories).toEqual({ passed: 3, failed: 2 });
    expect(campaign.totals?.cases.complete).toBe(5);
  });

  it("still parses the rows of a master without Phase 6", async () => {
    const { client } = clientWith(async () => jsonResponse([samplePreSixCampaignRow]));
    const [row] = (await listHistory(client)).items;
    expect(row.campaign_id).toBe("c1");
    expect(row.kind).toBeUndefined();
    expect(row.steps).toBeUndefined();
    expect(row.totals).toBeUndefined();
  });

  it("rejects a kind it does not know", async () => {
    const { client } = clientWith(async () => jsonResponse([{ ...sampleHistoryRows[0], kind: "benchmark" }]));
    const error = await listHistory(client).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OperatorApiError);
    expect((error as OperatorApiError).kind).toBe("schema");
  });
});

describe("deleteCampaign", () => {
  it("sends DELETE and accepts the empty 204 answer", async () => {
    const { client, spy } = clientWith(async () => new Response(null, { status: 204 }));
    await expect(deleteCampaign(client, "wb 1")).resolves.toBeUndefined();
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/cluster/campaigns/wb%201`);
    expect(init?.method).toBe("DELETE");
  });

  it("surfaces 409 for an entry that is not final, and 404 for one that is gone", async () => {
    const busy = clientWith(async () => jsonResponse({ detail: "the campaign is running; stop it first" }, { status: 409 }));
    const conflict = await deleteCampaign(busy.client, "c1").catch((caught: unknown) => caught);
    expect(conflict).toBeInstanceOf(OperatorApiError);
    expect((conflict as OperatorApiError).status).toBe(409);
    expect((conflict as OperatorApiError).message).toMatch(/stop it first/);

    const gone = clientWith(async () => jsonResponse({ detail: "no such campaign" }, { status: 404 }));
    expect(((await deleteCampaign(gone.client, "c1").catch((caught: unknown) => caught)) as OperatorApiError).status).toBe(404);
  });
});

describe("outputs", () => {
  it("parses the output of every step", () => {
    for (const row of [...sampleOutputRows, sampleTrajectoryOutput(), sampleSimulationOutput()]) {
      expect(outputRowSchema.safeParse(row).success).toBe(true);
    }
    const trajectory = outputRowSchema.parse(sampleTrajectoryOutput());
    expect(trajectory.artifact?.pointer).toBe("/trajectories");
    expect(trajectory.complete).toBe(false);
    expect(trajectory.verdict).toEqual({ state: "failed", failed_rules: ["rule_15"] });
    expect(trajectory.input_source).toEqual({ campaign_id: "c1", case_id: 5, step: "scene_generation" });
    const run = outputRowSchema.parse(sampleSimulationOutput());
    expect(run.run_record_id).toBe(11);
    expect(run.input_source?.file).toBe("head_on.json");
    expect(outputRowSchema.parse(sampleDroppedOutput()).artifact).toBeNull();
  });

  it("pages with the step and filters and reads the total", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleOutputRows, { headers: { "X-Total-Count": String(SAMPLE_OUTPUTS_TOTAL) } }));
    const page = await listOutputs(client, "c 1", { step: "scene_generation", state: "complete", fec_id: "class-a", limit: 2, offset: 4 });
    expect(page.total).toBe(SAMPLE_OUTPUTS_TOTAL);
    expect(page.items).toHaveLength(2);
    const url = new URL(spy.mock.calls[0][0]);
    expect(url.pathname).toBe("/cluster/campaigns/c%201/outputs");
    expect(url.searchParams.get("step")).toBe("scene_generation");
    expect(url.searchParams.get("state")).toBe("complete");
    expect(url.searchParams.get("fec_id")).toBe("class-a");
    expect(url.searchParams.get("limit")).toBe("2");
    expect(url.searchParams.get("offset")).toBe("4");
  });

  it("rejects an output row without its case", async () => {
    const { client } = clientWith(async () => jsonResponse([{ ...sampleOutputRows[0], case_id: undefined }]));
    expect(((await listOutputs(client, "c1", { step: "simulation" }).catch((caught: unknown) => caught)) as OperatorApiError).kind).toBe("schema");
  });
});

describe("findings", () => {
  it("asks for one step and parses the summary", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleFindings()));
    const findings = await getFindings(client, "c1", "trajectory_generation");
    expect(findings.verdicts).toEqual({ passed: 3, failed: 2, unmonitored: 0 });
    expect(findings.failed_rules[0].first_failure_time_s).toEqual({ min: 12.5, median: 20.1 });
    expect(findings.fecs[0]).toEqual({ fec_id: "class-a", cases: 5, passed: 3, failed: 2 });
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/campaigns/c1/findings?step=trajectory_generation`);
  });

  it("parses an unmonitored step: empty verdicts and rules, no durations", () => {
    const findings = findingsSchema.parse(sampleUnmonitoredFindings);
    expect(findings.monitored).toBe(false);
    expect(findings.failed_rules).toEqual([]);
    expect(findings.durations_s).toEqual({ median: null, p90: null });
  });
});

describe("uploadArtifact", () => {
  it("posts the file as it is with its content type and the kind, and parses the reference", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleUploadedRef, { status: 201 }));
    const text = '{"scene": {}}';
    const ref = await uploadArtifact(client, text, "scene", "application/json");
    expect(ref.sha256).toBe("d".repeat(64));
    expect(ref.kind).toBe("scene");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/cluster/artifacts?kind=scene`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(text);
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("sends a blob unchanged", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleUploadedRef));
    const blob = new Blob(["{}"], { type: "application/json" });
    await uploadArtifact(client, blob, "functional_scenario");
    expect(spy.mock.calls[0][1]?.body).toBe(blob);
    expect(spy.mock.calls[0][0]).toContain("kind=functional_scenario");
  });

  it("surfaces a file that is too large", async () => {
    const { client } = clientWith(async () => jsonResponse({ detail: "the file is larger than 64 MiB" }, { status: 413 }));
    const error = (await uploadArtifact(client, "x", "trajectories").catch((caught: unknown) => caught)) as OperatorApiError;
    expect(error.status).toBe(413);
  });
});
