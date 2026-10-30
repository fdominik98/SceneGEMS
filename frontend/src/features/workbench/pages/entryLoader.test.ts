import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
import { caseDetailSchema, jobDetailSchema, type CaseDetail } from "../../../domain/cluster/schemas";
import { sampleCase, sampleRunRecord } from "../../../test/fixtures/clusterViews";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import twoVesselCrossing from "../../encounter/fixtures/twoVesselCrossing.json";
import { EntryEndedError, isGone } from "./entryFollower";
import { loadEntryOutput, runSetupOf, trajectoryScenarioOf, type LoaderClient } from "./entryLoader";
import type { WorkbenchTarget } from "./workbenchTarget";

const SCENE = "a".repeat(64);
const TRAJECTORIES = "b".repeat(64);
const INPUT = "c".repeat(64);
const FRAMES = "f".repeat(64);

/** A scene as the backend writes it: actor tuples of static data and state. */
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
const scenario = { scenario_name: "head_on", best_scene: sceneOf(0) };
/** Monitored frames as `serialize_monitored_frame` writes them. */
const recorded = (twoVesselCrossing as { frames: Record<string, unknown>[] }).frames;

function job(stage: string, jobId: string, state = "succeeded") {
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

function caseDetail(overrides: Record<string, unknown>): CaseDetail {
  return caseDetailSchema.parse({ ...sampleCase, campaign_id: "wb1", case_id: 1, progress: {}, jobs: [], run_records: [], verdicts: [], ...overrides });
}

function jobDetail(result: Record<string, unknown>) {
  return jobDetailSchema.parse({
    job_id: "j",
    job_type: "monitoring.post_hoc",
    state: "succeeded",
    priority: 0,
    attempt: 1,
    failed_attempts: 0,
    max_attempts: 1,
    idempotency_key: "k",
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

function fakeClient(detail: CaseDetail | "gone", artifacts: Record<string, unknown>, jobResults: Record<string, Record<string, unknown>> = {}) {
  const client: LoaderClient = {
    getCase: async () => {
      if (detail === "gone") {
        throw new OperatorApiError("http", "HTTP 404", "/cluster/campaigns/wb1/cases/1", 404);
      }
      return detail;
    },
    getJob: async (jobId: string) => jobDetail(jobResults[jobId] ?? {}),
    artifactUrl: (sha256: string) => `http://master/cluster/artifacts/${sha256}`,
    request: async () => {
      throw new Error("not used");
    },
  } as LoaderClient;
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const sha = String(input).split("/").pop() as string;
    if (!(sha in artifacts)) {
      return new Response("missing", { status: 404 });
    }
    return new Response(JSON.stringify(artifacts[sha]), { status: 200 });
  }) as typeof fetch;
  return { client, fetch: fetchImpl };
}

const sceneTarget: WorkbenchTarget = { page: "sceneGeneration", campaignId: "wb1", caseId: 1, step: "scene_generation" };

describe("entry loader", () => {
  it("loads a scene with its monitor frame and the scene as the next page's input", async () => {
    const detail = caseDetail({ stage: "verdict", scene_artifact: SCENE, jobs: [job("generate_scene", "g1"), job("monitor_scene", "m1")] });
    const { client, fetch } = fakeClient(detail, { [SCENE]: scenario, [FRAMES]: recorded.slice(0, 1) }, { m1: { frames: { sha256: FRAMES, size_bytes: 10 } } });
    const loaded = await loadEntryOutput(client, sceneTarget, { fetch });
    expect(loaded.step).toBe("scene_generation");
    if (loaded.step !== "scene_generation") return;
    expect(loaded.valid).toBe(true);
    expect(loaded.scene.actors[0]?.id).toBe("0");
    expect(loaded.monitorFrame?.timestamp).toBe(0);
    expect(loaded.output).toMatchObject({
      ref: { sha256: SCENE, size_bytes: new TextEncoder().encode(JSON.stringify(scenario)).length, kind: "scene", pointer: null },
      source: { campaign_id: "wb1", case_id: 1, step: "scene_generation" },
    });
  });

  it("loads an unmonitored scene without a monitor frame", async () => {
    const detail = caseDetail({ stage: "verdict", scene_artifact: SCENE, jobs: [job("generate_scene", "g1")] });
    const { client, fetch } = fakeClient(detail, { [SCENE]: scenario });
    const loaded = await loadEntryOutput(client, sceneTarget, { fetch });
    expect(loaded.step === "scene_generation" && loaded.monitorFrame).toBeNull();
  });

  it("loads trajectories with the monitor's frames, flagged as the case is", async () => {
    const trajectoryData = { trajectories: { scene_list: [sceneOf(0), sceneOf(10)], time_step: 10 } };
    const detail = caseDetail({ stage: "verdict", trajectories_artifact: TRAJECTORIES, trajectories_complete: false, jobs: [job("monitor_trajectories", "m2")] });
    const { client, fetch } = fakeClient(detail, { [TRAJECTORIES]: trajectoryData, [FRAMES]: recorded.slice(0, 2) }, { m2: { frames: { sha256: FRAMES, size_bytes: 10 } } });
    const loaded = await loadEntryOutput(client, { ...sceneTarget, page: "trajectoryGeneration", step: "trajectory_generation" }, { fetch });
    if (loaded.step !== "trajectory_generation") throw new Error("wrong step");
    expect(loaded.frames.map((frame) => frame.timestamp)).toEqual([0, 10]);
    expect(loaded.frames[0]?.ruleResults).toBeDefined();
    expect(loaded.complete).toBe(false);
    expect(loaded.output.ref).toMatchObject({ sha256: TRAJECTORIES, kind: "trajectories", pointer: "/trajectories" });
  });

  it("loads a run's frames, its input trajectories and its setup", async () => {
    const record = { ...sampleRunRecord, run_record_id: 11, stack: { config: { simulation_layer: "kinematic", mode: "usv_navigation" } }, environment: { wind_vector: [1, 2, 0] }, artifacts: { trajectories: INPUT, state_log: "e".repeat(64) } };
    const detail = caseDetail({ stage: "verdict", run_records: [record] });
    const inputDoc = { scene_list: [sceneOf(0)], time_step: 1 };
    const { client, fetch } = fakeClient(detail, { [INPUT]: inputDoc });
    const loaded = await loadEntryOutput(client, { page: "simulation", campaignId: "wb1", caseId: 1, step: "simulation", runRecordId: 11 }, { fetch, runFrames: async () => sampleFrames.slice(0, 3) });
    if (loaded.step !== "simulation") throw new Error("wrong step");
    expect(loaded.frames).toHaveLength(3);
    expect(loaded.scenario).toEqual({ trajectories: inputDoc });
    expect(loaded.setup).toEqual({ simulationLayer: "kinematic", controlLayer: null, mode: "usv_navigation", speedup: null, windVector: [1, 2, 0], waves: null });
    expect(loaded.input?.ref).toMatchObject({ sha256: INPUT, kind: "trajectories", pointer: null });
  });

  it("rejects as gone when the entry was deleted (404)", async () => {
    const { client, fetch } = fakeClient("gone", {});
    const failure = await loadEntryOutput(client, sceneTarget, { fetch }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(EntryEndedError);
    expect(isGone(failure)).toBe(true);
  });

  it("rejects as gone when the output's artifact was freed", async () => {
    const detail = caseDetail({ stage: "verdict", scene_artifact: SCENE });
    const { client, fetch } = fakeClient(detail, {});
    expect(isGone(await loadEntryOutput(client, sceneTarget, { fetch }).catch((error: unknown) => error))).toBe(true);
  });

  it("does not call a case without its output gone", async () => {
    const detail = caseDetail({ stage: "generate_scene", state: "active", scene_artifact: null });
    const { client, fetch } = fakeClient(detail, {});
    const failure = await loadEntryOutput(client, sceneTarget, { fetch }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(EntryEndedError);
    expect(isGone(failure)).toBe(false);
  });
});

describe("loader helpers", () => {
  it("makes a full trajectory scenario of planned or recorded trajectories", () => {
    const trajectories = { scene_list: [{}] };
    expect(trajectoryScenarioOf({ trajectories })).toEqual({ trajectories });
    expect(trajectoryScenarioOf(trajectories)).toEqual({ trajectories });
    expect(trajectoryScenarioOf({ other: 1 })).toBeNull();
  });

  it("reads a run's stack and environment, with defaults for a record without them", () => {
    expect(runSetupOf({ stack: {}, environment: {} })).toEqual({ simulationLayer: "kinematic", controlLayer: null, mode: null, speedup: null, windVector: [0, 0, 0], waves: null });
    expect(runSetupOf({ stack: { config: { simulation_layer: "gazebo", control_layer: "custom", mode: "replay" } }, environment: { wind_vector: [0, 3, 0] } })).toMatchObject({
      simulationLayer: "gazebo",
      controlLayer: "custom",
      windVector: [0, 3, 0],
    });
    expect(runSetupOf({ stack: { config: { simulation_layer: "gazebo", mode: "replay", speedup: 4, geofence: {} } }, environment: {} })).toMatchObject({ simulationLayer: "gazebo", mode: "replay", speedup: 4 });
    expect(runSetupOf({ stack: { config: { mode: "replay" } }, environment: { waves: { amplitude: 1, period: 8, steepness: 0.1, direction: [1, 0] } } }).waves).toEqual({
      amplitude: 1,
      period: 8,
      steepness: 0.1,
      direction: [1, 0],
    });
  });
});
