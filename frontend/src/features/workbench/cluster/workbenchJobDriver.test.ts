import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parse } from "yaml";
import { OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import { caseDetailSchema, jobDetailSchema } from "../../../domain/cluster/schemas";
import { useScenePlaybackStore, useTrajectoryPlaybackStore } from "../../../domain/playback/playbackStore";
import type { ParsedServerMessage } from "../../../domain/simulation/protocol";
import { useTrajectoryGenerationStore } from "../../../domain/trajectoryGeneration/trajectoryGenerationStore";
import { sampleCampaignDetail, sampleCampaignSummary, sampleCase } from "../../../test/fixtures/clusterViews";
import { useScenePageStore, useTrajectoryPageStore } from "../pages/pageStore";
import { useClusterRunStore } from "./clusterRunStore";
import { attendedRunDetail, WorkbenchJobDriver, type ClusterAccess } from "./workbenchJobDriver";

const SCENE_SHA = "a".repeat(64);
const UPLOAD_SHA = "9".repeat(64);
const TRAJECTORY_SHA = "b".repeat(64);

function sceneOf(y: number) {
  return {
    _data: [
      [
        { id: 0, type: "OSPassengerShip", length: 30, breadth: 10.5, height: 4.5, draft: 1.8, mass: 346612, safety_radius: 120, _is_os: true, is_vessel: true },
        { x: 0, y, speed: 14.6, heading: 1.57 },
      ],
    ],
  };
}
const trajectoryData = { trajectories: { scene_list: [sceneOf(0), sceneOf(10)], time_step: 10 } };

function jobView(jobId: string, state: string, result: Record<string, unknown> | null = null) {
  return jobDetailSchema.parse({
    job_id: jobId,
    job_type: "trajectory_generation",
    state,
    priority: 0,
    attempt: 1,
    failed_attempts: 0,
    max_attempts: 1,
    idempotency_key: jobId,
    requirements: { labels: {}, fingerprints: {}, min_memory_mb: 0, min_cpus: 0 },
    lease_owner: null,
    lease_expires_at: null,
    submitted_at: "2026-10-28T09:00:00+00:00",
    available_at: "2026-10-28T09:00:00+00:00",
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

function caseJob(stage: string, jobId: string, state: string) {
  return {
    stage,
    run_index: null,
    repeat_index: null,
    idempotency_key: `${stage}-1`,
    job_id: jobId,
    intent: true,
    created_at: "2026-10-28T09:00:00+00:00",
    submitted_at: "2026-10-28T09:00:00+00:00",
    job: { job_type: "x", state, priority: 0, attempt: 1, failed_attempts: 0, max_attempts: 1, lease_owner: null, available_at: null, started_at: null, finished_at: null, error: null },
  };
}

/** A control node that runs a trajectory generation entry: one case, its job succeeds at once, the case completes. */
function fakeControlNode() {
  const created: { body: Record<string, unknown> }[] = [];
  const uploads: { kind: unknown }[] = [];
  let caseGets = 0;
  const client = {
    request: async (method: string, path: string, _schema: unknown, options: { body?: Record<string, unknown>; query?: Record<string, unknown> } = {}) => {
      if (method === "POST" && path === "/cluster/artifacts") {
        uploads.push({ kind: options.query?.kind });
        return { data: { sha256: UPLOAD_SHA, size_bytes: 321, kind: "scene", media_type: "application/json", pointer: null }, total: null };
      }
      if (method === "POST" && path === "/cluster/campaigns") {
        created.push({ body: options.body ?? {} });
        return { data: { ...sampleCampaignDetail(), campaign_id: "wb1" }, total: null };
      }
      throw new Error(`unexpected ${method} ${path}`);
    },
    listCases: async () => ({ items: [{ ...sampleCase, campaign_id: "wb1", case_id: 1, fec_id: "item/0", state: "active", stage: "generate_trajectories" }], total: 1 }),
    getCampaign: async () => ({ ...sampleCampaignSummary, campaign_id: "wb1" }),
    getCase: async () => {
      caseGets += 1;
      const done = caseGets > 2;
      return caseDetailSchema.parse({
        ...sampleCase,
        campaign_id: "wb1",
        case_id: 1,
        fec_id: "item/0",
        stage: done ? "verdict" : "generate_trajectories",
        state: done ? "complete" : "active",
        scene_artifact: null,
        trajectories_artifact: done ? TRAJECTORY_SHA : null,
        trajectories_complete: true,
        progress: {},
        jobs: [caseJob("generate_trajectories", "t1", "succeeded")],
        run_records: [],
        verdicts: [],
      });
    },
    getJob: async (jobId: string) => jobView(jobId, "succeeded", { trajectory_data: trajectoryData, valid: true, complete: true }),
    cancelJob: async () => ({}),
    controlCampaign: async () => ({}),
    artifactUrl: (sha256: string) => `http://control-node/cluster/artifacts/${sha256}`,
  };
  return { client: client as unknown as OperatorClient, created, uploads };
}

function access(client: OperatorClient): ClusterAccess {
  return { cluster: { client, channel: null }, resources: (jobType, components = []) => ({ jobType, components: [...components], workerNodes: 1, slots: 1, freeSlots: 1, blocker: null }) };
}

describe("workbench job driver", () => {
  beforeEach(() => {
    useTrajectoryPageStore.setState({ input: null, loaded: null, output: null, status: "idle", message: null, activeEntryId: null });
    useScenePageStore.setState({ input: null, loaded: null, output: null, status: "idle", message: null, activeEntryId: null });
    useTrajectoryGenerationStore.getState().reset();
    useTrajectoryPlaybackStore.getState().clearPreviewFrames();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const sha = String(input).split("/").pop();
        return sha === TRAJECTORY_SHA ? new Response(JSON.stringify(trajectoryData)) : new Response("missing", { status: 404 });
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("runs a trajectory generation as a workbench entry and loads its output on the page", async () => {
    const controlNode = fakeControlNode();
    const messages: ParsedServerMessage[] = [];
    const driver = new WorkbenchJobDriver(() => access(controlNode.client), (message) => messages.push(message));
    driver.pollMs = 1;
    driver.jobPollMs = 1;
    const input = { label: "head_on.json", origin: "file" as const, ref: null, source: { file: "head_on.json" } };
    await driver.generateTrajectories("r1", {
      input,
      scenarioContent: JSON.stringify({ best_scene: sceneOf(0) }),
      colregsConstraintsContent: "colregs: 1\n",
      params: { generator: "straight", timeStep: 10, timespan: 600 },
    });

    // The scene file was uploaded, and the entry made with kind and origin outside the config.
    expect(controlNode.uploads).toEqual([{ kind: "scene" }]);
    expect(controlNode.created).toHaveLength(1);
    const body = controlNode.created[0].body;
    expect(body).toMatchObject({ kind: "workbench", origin: "trajectory_generation", start: true });
    const config = parse(body.config as string);
    expect(config).toMatchObject({
      format: 3,
      steps: ["trajectory_generation"],
      input: { items: [{ name: "head_on.json", ref: { sha256: UPLOAD_SHA, kind: "scene" }, source: { file: "head_on.json" } }] },
      trajectories: { generator: "straight", timespan_s: 600 },
      policy: { keep_frames: true },
    });
    expect(Number.isInteger(config.policy.seed)).toBe(true);

    // The job's result reached the page, then the entry's output was loaded as the page's latest.
    expect(messages.some((message) => message.kind === "trajectory_generation_result")).toBe(true);
    expect(useTrajectoryPageStore.getState().loaded).toMatchObject({ page: "trajectoryGeneration", campaignId: "wb1", caseId: 1, step: "trajectory_generation" });
    expect(useTrajectoryPageStore.getState().output?.ref).toMatchObject({ sha256: TRAJECTORY_SHA, kind: "trajectories", pointer: "/trajectories" });
    expect(useTrajectoryPlaybackStore.getState().frames).toHaveLength(2);
    expect(useTrajectoryGenerationStore.getState().resultValid).toBe(true);
  });

  it("gives each entry a fresh seed", async () => {
    const controlNode = fakeControlNode();
    const driver = new WorkbenchJobDriver(() => access(controlNode.client));
    driver.pollMs = 1;
    driver.jobPollMs = 1;
    const request = {
      input: { label: "scene", origin: "history" as const, ref: { sha256: SCENE_SHA, size_bytes: 5, kind: "scene", media_type: "application/json", pointer: null }, source: { campaign_id: "c1", case_id: 5, step: "scene_generation" as const } },
      scenarioContent: null,
      colregsConstraintsContent: "",
      params: { generator: "straight" as const, timespan: 60 },
    };
    await driver.generateTrajectories("r1", request);
    await driver.generateTrajectories("r2", request);
    // A history output is used as it is: nothing is uploaded.
    expect(controlNode.uploads).toEqual([]);
    const seeds = controlNode.created.map(({ body }) => parse(body.config as string).policy.seed);
    expect(seeds[0]).not.toBe(seeds[1]);
  });

  it("runs an ArduPilot replay as a workbench entry with the ArduPilot stack and the Connections page's geofence", async () => {
    const created: Record<string, unknown>[] = [];
    const client = {
      request: async (method: string, path: string, _schema: unknown, options: { body?: Record<string, unknown> } = {}) => {
        if (method === "POST" && path === "/cluster/campaigns") {
          created.push(options.body ?? {});
          return { data: { ...sampleCampaignDetail(), campaign_id: "wb2" }, total: null };
        }
        throw new Error(`unexpected ${method} ${path}`);
      },
      listCases: async () => ({ items: [{ ...sampleCase, campaign_id: "wb2", case_id: 1, fec_id: "item/0", state: "active", stage: "simulate" }], total: 1 }),
      getCampaign: async () => ({ ...sampleCampaignSummary, campaign_id: "wb2" }),
      getCase: async () =>
        caseDetailSchema.parse({
          ...sampleCase,
          campaign_id: "wb2",
          case_id: 1,
          fec_id: "item/0",
          stage: "verdict",
          state: "complete",
          progress: {},
          jobs: [{ ...caseJob("simulate", "s1", "succeeded"), run_index: 0, repeat_index: 0 }],
          run_records: [],
          verdicts: [],
        }),
      getJob: async (jobId: string) => jobView(jobId, "succeeded", { trajectories: { scene_list: [] } }),
      cancelJob: async () => ({}),
      controlCampaign: async () => ({}),
      artifactUrl: (sha256: string) => sha256,
    } as unknown as OperatorClient;
    const requested: string[] = [];
    const driver = new WorkbenchJobDriver(() => ({
      cluster: { client, channel: null },
      resources: (jobType, components = []) => {
        requested.push(`${jobType} with ${components.join(", ")}`);
        return { jobType, components: [...components], workerNodes: 1, slots: 1, freeSlots: 1, blocker: null };
      },
    }));
    driver.pollMs = 1;
    driver.jobPollMs = 1;
    const ref = { sha256: TRAJECTORY_SHA, size_bytes: 9, kind: "trajectories", media_type: "application/json", pointer: null };
    await driver.runSimulationEntry(
      { where: "cluster", jobType: "simulation", runner: "ardupilot", simulationLayer: "gazebo", mode: "replay", ownShipId: null, speedup: 3, components: ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"], summary: "" },
      {
        input: { label: "planned", origin: "history", ref, source: { campaign_id: "c1", case_id: 5, step: "trajectory_generation" } },
        scenarioContent: null,
        colregsConstraintsContent: "colregs: 1\n",
        geofence: { latitude: 58.1, longitude: 15.2, radius_meters: 35 },
      }
    );

    expect(requested).toContain("simulation with asv_system/replay, control_layer/ardupilot, simulation_layer/gazebo");
    const [body] = created;
    expect(body).toMatchObject({ kind: "workbench", origin: "simulation", start: true });
    expect(parse(body.config as string)).toMatchObject({
      format: 3,
      steps: ["simulation"],
      input: { items: [{ name: "planned", ref: { sha256: TRAJECTORY_SHA }, source: { campaign_id: "c1", case_id: 5, step: "trajectory_generation" } }] },
      execution: { runs: [{ stack: { simulation_layer: "gazebo", mode: "replay", speedup: 3, geofence: { latitude: 58.1, longitude: 15.2, radius_meters: 35 } }, monitor: "live" }] },
      policy: { keep_frames: true },
    });
    expect(useClusterRunStore.getState()).toMatchObject({ status: "done", message: "Finished: 0 frames." });
  });

  it("stops a followed workbench entry on the page's Stop, and only leaves a followed campaign", async () => {
    const stopped: string[] = [];
    const following = (kind: string) =>
      ({
        getCampaign: async () => ({ ...sampleCampaignSummary, kind }),
        listCases: async () => ({ items: [], total: 0 }),
        // The case waits for its job until the follow is stopped.
        getCase: async () =>
          caseDetailSchema.parse({ ...sampleCase, campaign_id: "wb7", case_id: 1, state: "active", stage: "simulate", progress: {}, jobs: [], run_records: [], verdicts: [] }),
        controlCampaign: async (id: string) => {
          stopped.push(`${kind}:${id}`);
          return {};
        },
        artifactUrl: (sha256: string) => sha256,
      }) as unknown as OperatorClient;
    for (const kind of ["workbench", "campaign"]) {
      const driver = new WorkbenchJobDriver(() => access(following(kind)));
      driver.pollMs = 1;
      const follow = driver.openTarget({ page: "simulation", campaignId: "wb7", caseId: 1, step: "simulation", live: true });
      await new Promise((resolve) => setTimeout(resolve, 20));
      driver.stopSimulation(true);
      await follow;
    }
    expect(stopped).toEqual(["workbench:wb7"]);
  });

  it("clears a page whose loaded entry was deleted", async () => {
    const client = {
      getCase: async () => {
        throw new OperatorApiError("http", "HTTP 404", "/cluster/campaigns/wb9/cases/1", 404);
      },
      artifactUrl: (sha256: string) => sha256,
    } as unknown as OperatorClient;
    useScenePlaybackStore.getState().setVisualizedScenario({ scene: { timestamp: 0, actors: [] } as never, valid: true });
    useScenePageStore.getState().setLoaded({ page: "sceneGeneration", campaignId: "wb9", caseId: 1, step: "scene_generation" }, null);
    const driver = new WorkbenchJobDriver(() => access(client));
    await driver.loadTarget({ page: "sceneGeneration", campaignId: "wb9", caseId: 1, step: "scene_generation" }, { quiet: true });
    expect(useScenePageStore.getState().loaded).toBeNull();
    expect(useScenePageStore.getState().message).toMatch(/deleted/);
    expect(useScenePlaybackStore.getState().latestGeneratedScene).toBeNull();
  });

  it("keeps the page as it is when a quiet refresh fails for another reason", async () => {
    const client = {
      getCase: async () => {
        throw new OperatorApiError("network", "cannot reach the control node", "/x");
      },
      artifactUrl: (sha256: string) => sha256,
    } as unknown as OperatorClient;
    const target = { page: "sceneGeneration" as const, campaignId: "wb9", caseId: 1, step: "scene_generation" as const };
    useScenePageStore.getState().setLoaded(target, null);
    await new WorkbenchJobDriver(() => access(client)).loadTarget(target, { quiet: true });
    expect(useScenePageStore.getState().loaded).toMatchObject({ campaignId: "wb9" });
  });
});

describe("an attended run's status detail", () => {
  it("gives the run's phase and where Mission Planner connects", () => {
    expect(attendedRunDetail({ phase: "ready_to_start", ground_control: { "0": 49153, "1": "not a port" } })).toEqual({ phase: "ready_to_start", groundControlPorts: { "0": 49153 } });
    expect(attendedRunDetail({ phase: "running" })).toEqual({ phase: "running" });
  });

  it("changes nothing for a status without a detail, so the latest phase stays", () => {
    expect(attendedRunDetail(null)).toEqual({});
    expect(attendedRunDetail(undefined)).toEqual({});
    expect(attendedRunDetail({ phase: 3 })).toEqual({});
  });
});
