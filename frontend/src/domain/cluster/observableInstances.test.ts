import { describe, expect, it, vi } from "vitest";
import { sampleJob, sampleWorkerNode } from "../../test/fixtures/clusterViews";
import { fetchWorkerNodeJobs, jobInstanceKind, jobInstances, workerNodeInstances, poolInstances, viewerFor } from "./observableInstances";
import type { OperatorClient } from "./operatorApi";
import { jobViewSchema, workerNodeViewSchema } from "./schemas";

const workerNode = workerNodeViewSchema.parse(
  sampleWorkerNode({
    slots: {
      scene_generation: { slots: 3, slots_in_use: 1 },
      trajectory_generation: { slots: 2, slots_in_use: 0 },
      simulation: { slots: 8, slots_in_use: 2 },
    },
  })
);

function job(overrides: Record<string, unknown>) {
  return jobViewSchema.parse(sampleJob(overrides));
}

describe("poolInstances", () => {
  it("gives one instance per slot of the pooled subsystems and none for other capabilities", () => {
    const pools = poolInstances(workerNode);
    expect(pools.map((entry) => entry.instance)).toEqual([
      "scene_generation-0",
      "scene_generation-1",
      "scene_generation-2",
      "trajectory_generation-0",
      "trajectory_generation-1",
    ]);
    expect(pools[0]).toMatchObject({
      workerNodeId: "worker-node-a1",
      topic: "instance:worker-node-a1/scene_generation-0",
      kind: "scene_generation",
      origin: "pool",
      job: null,
      state: "online",
    });
  });

  it("gives nothing for a worker node without pooled capabilities", () => {
    const simulationOnly = workerNodeViewSchema.parse(sampleWorkerNode({ slots: { simulation: { slots: 4, slots_in_use: 0 } } }));
    expect(poolInstances(simulationOnly)).toEqual([]);
  });
});

describe("jobInstances", () => {
  it("names the leased and running jobs this worker node owns by job id and attempt", () => {
    const jobs = [
      job({ job_id: "aaaa1111bbbb2222", job_type: "simulation", state: "running", attempt: 2 }),
      job({ job_id: "cccc3333dddd4444", job_type: "monitoring.post_hoc", state: "leased", attempt: 1 }),
      job({ job_id: "other", job_type: "simulation", state: "running", lease_owner: "worker-node-b2" }),
      job({ job_id: "done", job_type: "simulation", state: "succeeded" }),
      job({ job_id: "waiting", job_type: "simulation", state: "queued", lease_owner: null }),
    ];
    const instances = jobInstances(workerNode, jobs);
    expect(instances.map((entry) => entry.instance)).toEqual(["job-aaaa1111bbbb2222-2", "job-cccc3333dddd4444-1"]);
    expect(instances[0]).toMatchObject({
      topic: "instance:worker-node-a1/job-aaaa1111bbbb2222-2",
      kind: "simulation",
      origin: "job",
      state: "running",
    });
    expect(instances[0].job?.job_id).toBe("aaaa1111bbbb2222");
    expect(instances[1].kind).toBe("monitoring");
  });

  it("lists a job once even when two lists both carry it", () => {
    const same = job({ job_id: "x1", state: "running" });
    expect(jobInstances(workerNode, [same, same])).toHaveLength(1);
  });

  it("puts the pools before the jobs", () => {
    const all = workerNodeInstances(workerNode, [job({ job_id: "x1", job_type: "simulation" })]);
    expect(all.map((entry) => entry.origin)).toEqual(["pool", "pool", "pool", "pool", "pool", "job"]);
  });
});

describe("kinds and viewers", () => {
  it("maps job types to the kinds the control node reports", () => {
    expect(jobInstanceKind("scene_generation")).toBe("scene_generation");
    expect(jobInstanceKind("trajectory_generation")).toBe("trajectory_generation");
    expect(jobInstanceKind("simulation")).toBe("simulation");
    expect(jobInstanceKind("calibration.deviation")).toBe("simulation");
    expect(jobInstanceKind("monitoring.post_hoc")).toBe("monitoring");
  });

  it("picks the viewer by origin and kind", () => {
    expect(viewerFor({ origin: "pool", kind: "scene_generation" })).toBe("scene_generation");
    expect(viewerFor({ origin: "pool", kind: "trajectory_generation" })).toBe("trajectory_search");
    expect(viewerFor({ origin: "job", kind: "simulation" })).toBe("simulation");
    expect(viewerFor({ origin: "job", kind: "monitoring" })).toBe("job");
    // A job of a pooled subsystem has status and logs only: its previews belong to the pool instance.
    expect(viewerFor({ origin: "job", kind: "scene_generation" })).toBe("job");
  });
});

describe("fetchWorkerNodeJobs", () => {
  it("asks for leased and running jobs and keeps those owned by the worker node", async () => {
    const listJobs = vi.fn(async (filters: { state?: string }) => ({
      items:
        filters.state === "leased"
          ? [job({ job_id: "l1", state: "leased" }), job({ job_id: "l2", state: "leased", lease_owner: "worker-node-b2" })]
          : [job({ job_id: "r1", state: "running" })],
      total: null,
    }));
    const jobs = await fetchWorkerNodeJobs({ listJobs } as unknown as OperatorClient, "worker-node-a1");
    expect(listJobs.mock.calls.map(([filters]) => filters.state)).toEqual(["leased", "running"]);
    expect(jobs.map((entry) => entry.job_id).sort()).toEqual(["l1", "r1"]);
  });
});
