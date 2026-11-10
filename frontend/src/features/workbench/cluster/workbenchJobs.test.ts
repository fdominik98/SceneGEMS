import { describe, expect, it, vi } from "vitest";
import { jobViewSchema } from "../../../domain/cluster/schemas";
import { sampleJob } from "../../../test/fixtures/clusterViews";
import { monitoringSubmission, poolRequestId, poolTopic, runClusterJob, sceneJobResult, singleSceneTrajectories, trajectoryJobResult, type WorkbenchCluster } from "./workbenchJobs";

function job(overrides: Record<string, unknown> = {}) {
  return jobViewSchema.parse(sampleJob(overrides));
}

function fakeCluster(overrides: Record<string, unknown> = {}): WorkbenchCluster {
  const client = {
    submitJob: vi.fn(async () => job({ job_id: "j1", state: "queued" })),
    getJob: vi.fn(async () => job({ job_id: "j1", state: "succeeded" })),
    cancelJob: vi.fn(async () => ({ cancelled: true, job: job() })),
    artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}`,
    ...overrides,
  };
  return { client: client as unknown as WorkbenchCluster["client"], channel: null };
}

describe("job payloads", () => {

  it("monitors a scenario's first scene as a one-step state log", () => {
    expect(singleSceneTrajectories({ best_scene: { actors: 1 } })).toEqual({ scene_list: [{ actors: 1 }], time_step: 1 });
    expect(singleSceneTrajectories({ trajectories: { scene_list: [{ first: true }, { second: true }], time_step: 5 } })).toEqual({ scene_list: [{ first: true }], time_step: 1 });
    expect(singleSceneTrajectories({ nothing: true })).toBeNull();
  });

  it("asks the post-hoc monitor for frames, with the general defaults when no constants are given", () => {
    expect(monitoringSubmission({ scene_list: [] }, "  ", "s1").payload).toEqual({ trajectories: { scene_list: [] }, colregs_constraints_content: null, scenario_id: "s1", include_frames: true });
  });

  it("names the pool and request id a job's previews carry", () => {
    expect(poolTopic("worker-node-a", "scene_generation")).toBe("instance:worker-node-a/scene_generation-0");
    expect(poolRequestId({ job_id: "j9", attempt: 2 })).toBe("j9-2");
  });
});

describe("running a job", () => {
  it("submits, follows to the end and answers the final view", async () => {
    const cluster = fakeCluster();
    const ended = await runClusterJob(cluster, { job_type: "scene_generation", payload: {} });
    expect(ended.state).toBe("succeeded");
    expect(cluster.client.submitJob).toHaveBeenCalledOnce();
  });

  it("cancels the job on the cluster when stopped", async () => {
    const controller = new AbortController();
    const cluster = fakeCluster({
      getJob: vi.fn(async () => {
        controller.abort();
        return job({ job_id: "j1", state: "running" });
      }),
    });
    await expect(runClusterJob(cluster, { job_type: "scene_generation", payload: {} }, { signal: controller.signal })).rejects.toThrow();
    expect(cluster.client.cancelJob).toHaveBeenCalledWith("j1", "stopped in the workbench");
  });

  it("reads inline results as they are", async () => {
    const cluster = fakeCluster();
    const scene = await sceneJobResult(cluster, job({ state: "succeeded", result: { evaluation_data: { best_scene: {} }, valid: true } }));
    expect(scene).toEqual({ evaluationData: { best_scene: {} }, valid: true });
    const trajectories = await trajectoryJobResult(cluster, job({ state: "succeeded", result: { trajectory_data: null, valid: false, complete: false, error_message: "no path" } }));
    expect(trajectories).toEqual({ trajectoryData: null, valid: false, complete: false, errorMessage: "no path" });
  });

  it("refuses a scene job without a scene", async () => {
    await expect(sceneJobResult(fakeCluster(), job({ state: "succeeded", result: {} }))).rejects.toThrow("returned no scene");
  });
});
