import { describe, expect, it, vi } from "vitest";
import { caseDetailSchema, jobDetailSchema } from "../../../domain/cluster/schemas";
import { sampleCase } from "../../../test/fixtures/clusterViews";
import { EntryEndedError } from "./entryFollower";
import { loadEntryOutput, type LoaderClient } from "./entryLoader";
import { sceneInputSpecification } from "./inputSpecification";

/** Loading an exploration for its page, and the specification of a scene of an explored FEC. */

const TARGET = { page: "designSpaceExploration", campaignId: "c1", caseId: 4, step: "design_space_exploration" } as const;

function detail(state: string, withJob = true) {
  return caseDetailSchema.parse({
    ...sampleCase,
    case_id: 4,
    case_index: 0,
    fec_id: "exploration",
    stage: state === "active" ? "explore_design_space" : "verdict",
    state,
    scene_artifact: null,
    trajectories_artifact: null,
    progress: {},
    jobs: withJob
      ? [{ stage: "explore_design_space", run_index: null, repeat_index: null, idempotency_key: "k", job_id: "x1", intent: true, created_at: "2026-11-10T09:00:00+00:00", submitted_at: null, job: null }]
      : [],
    run_records: [],
    verdicts: [],
  });
}

function job(result: Record<string, unknown> | null) {
  return jobDetailSchema.parse({
    job_id: "x1",
    job_type: "design_space_exploration",
    state: result ? "succeeded" : "running",
    priority: 0,
    attempt: 1,
    failed_attempts: 0,
    max_attempts: 1,
    idempotency_key: "x1",
    requirements: { labels: {}, fingerprints: {}, min_memory_mb: 0, min_cpus: 0 },
    lease_owner: null,
    lease_expires_at: null,
    submitted_at: "2026-11-10T09:00:00+00:00",
    available_at: "2026-11-10T09:00:00+00:00",
    started_at: null,
    finished_at: null,
    result,
    error: null,
    progress: null,
    payload: {},
    events: [],
    log_lines: [],
  });
}

const RESULT = {
  stop_reason: "unsatisfiable",
  complete: true,
  models_found: 0,
  max_models: 1000,
  fecs: [],
  functional_scenarios: [],
};

function client(state: string, result: Record<string, unknown> | null, rows: unknown[] = []) {
  const request = vi.fn(async () => ({ data: rows, total: rows.length }));
  const loader = {
    getCase: async () => detail(state),
    getJob: async () => job(result),
    artifactUrl: (sha: string) => `http://master/cluster/artifacts/${sha}`,
    request,
  };
  return { loader: loader as unknown as LoaderClient, request };
}

describe("loading an exploration", () => {
  it("reads the job's result and the outputs of the step, which are empty for a specification without a model", async () => {
    const { loader, request } = client("dropped", RESULT);
    const loaded = await loadEntryOutput(loader, TARGET);
    expect(loaded).toMatchObject({ step: "design_space_exploration", fecs: [], caseIndex: 0, result: { stop_reason: "unsatisfiable" } });
    expect(request).toHaveBeenCalledWith("GET", "/cluster/campaigns/c1/outputs", expect.anything(), expect.objectContaining({ query: expect.objectContaining({ step: "design_space_exploration" }) }));
  });

  it("lists the FECs a result names when the outputs have none", async () => {
    const result = { ...RESULT, stop_reason: "exhausted", models_found: 1, fecs: [{ index: 0, vessel_count: 1, obstacle_count: 0 }] };
    const loaded = await loadEntryOutput(client("complete", result).loader, TARGET);
    expect(loaded.step === "design_space_exploration" && loaded.fecs.map((fec) => fec.fecId)).toEqual(["explored/00000"]);
  });

  it("is not done while the exploration runs", async () => {
    await expect(loadEntryOutput(client("active", null).loader, TARGET)).rejects.toBeInstanceOf(EntryEndedError);
  });
});

describe("the specification of a scene of an explored FEC", () => {
  it("is the case's input artifact, named by the FEC", async () => {
    const fetchImpl = vi.fn(async () => new Response("declare os.\r\nOS(os).\r\n"));
    const specClient = {
      getCase: async () => ({ ...detail("complete"), fec_id: "explored/00003", input_artifact: "e".repeat(64) }),
      artifactUrl: (sha: string) => `http://master/cluster/artifacts/${sha}`,
      request: vi.fn(),
    };
    const spec = await sceneInputSpecification(specClient as never, { campaignId: "c1", caseId: 9 }, { fetch: fetchImpl as unknown as typeof fetch });
    expect(spec).toEqual({ label: "explored/00003", text: "declare os.\nOS(os).\n" });
    expect(specClient.request).not.toHaveBeenCalled();
  });
});
