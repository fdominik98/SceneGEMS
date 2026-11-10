import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parse } from "yaml";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import { caseDetailSchema, jobDetailSchema } from "../../../domain/cluster/schemas";
import { sampleCampaignDetail, sampleCampaignSummary, sampleCase } from "../../../test/fixtures/clusterViews";
import { useExplorationStore } from "../designSpace/explorationStore";
import { useExplorationPageStore } from "../pages/pageStore";
import { WorkbenchJobDriver, type ClusterAccess } from "./workbenchJobDriver";

/** The design space exploration as a workbench entry, against a master that explores two FECs. */

const FEC_SHA = "f".repeat(64);
const RESULT = {
  stop_reason: "exhausted",
  complete: true,
  models_found: 2,
  max_models: 1000,
  random_seed: 3,
  elapsed_s: 1.5,
  message: null,
  fecs: [
    { index: 0, vessel_count: 2, obstacle_count: 0 },
    { index: 1, vessel_count: 2, obstacle_count: 1 },
  ],
  functional_scenarios: [],
};

function jobView(jobId: string, state: string, result: Record<string, unknown> | null) {
  return jobDetailSchema.parse({
    job_id: jobId,
    job_type: "design_space_exploration",
    state,
    priority: 0,
    attempt: 1,
    failed_attempts: 0,
    max_attempts: 1,
    idempotency_key: jobId,
    requirements: { labels: {}, fingerprints: {}, min_memory_mb: 0, min_cpus: 0 },
    lease_owner: null,
    lease_expires_at: null,
    submitted_at: "2026-11-10T09:00:00+00:00",
    available_at: "2026-11-10T09:00:00+00:00",
    started_at: null,
    finished_at: null,
    result,
    error: state === "failed" ? "refinery crashed" : null,
    progress: null,
    payload: {},
    events: [],
    log_lines: [],
  });
}

function outputRow(index: number) {
  return {
    case_id: 1,
    case_index: index,
    fec_id: `explored/0000${index}`,
    state: "complete",
    reason: null,
    artifact: { sha256: FEC_SHA, size_bytes: 40, kind: "functional_scenario", media_type: "text/plain; charset=utf-8", pointer: null },
    valid: true,
    complete: null,
    run_index: null,
    repeat_index: null,
    run_record_id: null,
    verdict: null,
    input_source: null,
    vessel_count: 2,
    obstacle_count: index,
  };
}

function fakeMaster(jobState = "succeeded") {
  const created: Record<string, unknown>[] = [];
  const requests: string[] = [];
  let caseGets = 0;
  const client = {
    request: async (method: string, path: string, _schema: unknown, options: { body?: Record<string, unknown>; query?: Record<string, unknown> } = {}) => {
      requests.push(`${method} ${path}${options.query?.step ? `?step=${String(options.query.step)}` : ""}`);
      if (method === "POST" && path === "/cluster/campaigns") {
        created.push(options.body ?? {});
        return { data: { ...sampleCampaignDetail(), campaign_id: "wb1" }, total: null };
      }
      if (method === "GET" && path === "/cluster/campaigns/wb1/outputs") {
        return { data: [outputRow(0), outputRow(1)], total: 2 };
      }
      throw new Error(`unexpected ${method} ${path}`);
    },
    listCases: async () => ({ items: [{ ...sampleCase, campaign_id: "wb1", case_id: 1, case_index: 0, fec_id: "exploration", state: "active", stage: "explore_design_space" }], total: 1 }),
    getCampaign: async () => ({ ...sampleCampaignSummary, campaign_id: "wb1" }),
    getCase: async () => {
      caseGets += 1;
      const done = caseGets > 2;
      return caseDetailSchema.parse({
        ...sampleCase,
        campaign_id: "wb1",
        case_id: 1,
        case_index: 0,
        fec_id: "exploration",
        stage: done ? "verdict" : "explore_design_space",
        state: done ? "complete" : "active",
        scene_artifact: null,
        trajectories_artifact: null,
        progress: {},
        jobs: [
          {
            stage: "explore_design_space",
            run_index: null,
            repeat_index: null,
            idempotency_key: "explore-1",
            job_id: "x1",
            intent: true,
            created_at: "2026-11-10T09:00:00+00:00",
            submitted_at: "2026-11-10T09:00:00+00:00",
            job: null,
          },
        ],
        run_records: [],
        verdicts: [],
      });
    },
    getJob: async (jobId: string) => jobView(jobId, jobState, jobState === "succeeded" ? RESULT : null),
    cancelJob: async () => ({}),
    controlCampaign: vi.fn(async () => ({})),
    artifactUrl: (sha256: string) => `http://master/cluster/artifacts/${sha256}`,
  };
  return { client: client as unknown as OperatorClient & { controlCampaign: ReturnType<typeof vi.fn> }, created, requests };
}

function access(client: OperatorClient, blocker: string | null = null): ClusterAccess {
  return { cluster: { client, channel: null }, resources: (jobType, components = []) => ({ jobType, components: [...components], nodes: blocker ? 0 : 1, slots: 1, freeSlots: 1, blocker }) };
}

const REQUEST = { specification: "class OS.\n", label: "the master's default", scope: "TS = 2, StaticObstacle = 0", maxFecs: 100, timeoutSeconds: 600 };

describe("the design space exploration on the workbench", () => {
  beforeEach(() => {
    useExplorationPageStore.setState({ input: null, loaded: null, output: null, status: "idle", message: null, activeEntryId: null });
    useExplorationStore.getState().clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("explores as a one-step workbench entry and lists the explored FECs", async () => {
    const master = fakeMaster();
    const driver = new WorkbenchJobDriver(() => access(master.client));
    driver.pollMs = 1;
    driver.jobPollMs = 1;
    await driver.exploreDesignSpace(REQUEST);

    expect(master.created).toHaveLength(1);
    expect(master.created[0]).toMatchObject({ kind: "workbench", origin: "design_space_exploration", start: true });
    const config = parse(master.created[0].config as string);
    expect(config).toMatchObject({
      format: 3,
      steps: ["design_space_exploration"],
      design_space_exploration: { specification: "class OS.\n", scope: "TS = 2, StaticObstacle = 0", max_fecs: 100, timeout_s: 600 },
      policy: { keep_frames: true },
    });
    expect(config.input).toBeUndefined();
    expect(config.scope).toBeUndefined();
    // The findings of the step are never asked for: the master answers 422
    expect(master.requests.some((request) => request.includes("/findings"))).toBe(false);
    expect(master.requests).toContain("GET /cluster/campaigns/wb1/outputs?step=design_space_exploration");

    const shown = useExplorationStore.getState();
    expect(shown.running).toBeNull();
    expect(shown.result?.stop_reason).toBe("exhausted");
    expect(shown.fecs.map((fec) => [fec.fecId, fec.vesselCount, fec.obstacleCount])).toEqual([
      ["explored/00000", 2, 0],
      ["explored/00001", 2, 1],
    ]);
    expect(useExplorationPageStore.getState().loaded).toMatchObject({ page: "designSpaceExploration", campaignId: "wb1", caseId: 1, step: "design_space_exploration", caseIndex: 0 });
    expect(useExplorationPageStore.getState().status).toBe("shown");
  });

  it("does not create an entry when no machine offers the exploration, and says why", async () => {
    const master = fakeMaster();
    const driver = new WorkbenchJobDriver(() => access(master.client, "No machine of the active cluster offers design space exploration."));
    await driver.exploreDesignSpace(REQUEST);
    expect(master.created).toEqual([]);
    expect(useExplorationPageStore.getState()).toMatchObject({ status: "failed", message: "No machine of the active cluster offers design space exploration." });
  });

  it("says why a failed exploration failed", async () => {
    const master = fakeMaster("failed");
    const driver = new WorkbenchJobDriver(() => access(master.client));
    driver.pollMs = 1;
    driver.jobPollMs = 1;
    await driver.exploreDesignSpace(REQUEST);
    expect(useExplorationPageStore.getState().status).toBe("failed");
    expect(useExplorationPageStore.getState().message).toContain("The design space exploration on the cluster failed");
    expect(useExplorationStore.getState().running).toBeNull();
  });

  it("opens an entry of Campaign History with the FEC it names selected", async () => {
    const master = fakeMaster();
    const driver = new WorkbenchJobDriver(() => access(master.client));
    await driver.openTarget({ page: "designSpaceExploration", campaignId: "wb1", caseId: 1, step: "design_space_exploration", caseIndex: 0, fecId: "explored/00001" });
    expect(useExplorationStore.getState().selectedFecId).toBe("explored/00001");
    expect(useExplorationPageStore.getState().loaded?.fecId).toBeUndefined();
  });

  it("stops the entry it made on the user's Stop", async () => {
    const master = fakeMaster();
    const driver = new WorkbenchJobDriver(() => access(master.client));
    driver.pollMs = 1000;
    const run = driver.exploreDesignSpace(REQUEST);
    await vi.waitFor(() => expect(master.created).toHaveLength(1));
    driver.stopExploration(true);
    await run;
    expect(master.client.controlCampaign).toHaveBeenCalledWith("wb1", "stop");
    expect(useExplorationPageStore.getState().status).toBe("idle");
    expect(useExplorationStore.getState().running).toBeNull();
  });
});
