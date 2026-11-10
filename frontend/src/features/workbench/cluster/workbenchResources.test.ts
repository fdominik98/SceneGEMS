import { describe, expect, it } from "vitest";
import { workerNodeViewSchema } from "../../../domain/cluster/schemas";
import { sampleWorkerNode } from "../../../test/fixtures/clusterViews";
import { describeResources, jobTypeResources, type WorkerNodesFeedState } from "./workbenchResources";

function feed(workerNodes: Record<string, unknown>[], extra: Partial<WorkerNodesFeedState> = {}): WorkerNodesFeedState {
  return { operatorUrl: "http://127.0.0.1:5174", workerNodes: workerNodes.map((workerNode) => workerNodeViewSchema.parse(workerNode)), loaded: true, unreachable: false, ...extra };
}

describe("workbench resources", () => {
  it("counts the slots of usable worker nodes that offer the job type", () => {
    const resources = jobTypeResources(
      feed([sampleWorkerNode(), sampleWorkerNode({ worker_node_id: "worker-node-b", name: "worker-b", slots: { scene_generation: { slots: 2, slots_in_use: 0 } } })]),
      "scene_generation"
    );
    expect(resources).toEqual({ jobType: "scene_generation", components: ["scene_generation"], workerNodes: 2, slots: 6, freeSlots: 5, blocker: null });
    expect(describeResources(resources)).toBe("6 slots on 2 machines, 5 free");
  });

  it("blocks a job type no machine offers", () => {
    const resources = jobTypeResources(feed([sampleWorkerNode()]), "trajectory_generation");
    expect(resources.blocker).toBe("No machine of the active cluster offers trajectory generation.");
    expect(describeResources(resources)).toBe("no machine");
  });

  it("leaves out offline, draining and out of date machines, and says so", () => {
    const stale = { worker_node_id: "n3", out_of_date: true, components: [{ component: "scene_generation", images: [], state: "out_of_date" }] };
    const workerNodes = [sampleWorkerNode({ status: "offline" }), sampleWorkerNode({ worker_node_id: "n2", status: "draining" }), sampleWorkerNode(stale)];
    const resources = jobTypeResources(feed(workerNodes), "scene_generation");
    expect(resources.workerNodes).toBe(0);
    expect(resources.blocker).toBe("The machines that offer scene generation are offline, draining or out of date.");
  });

  it("counts a simulation only on machines with every component of the plan", () => {
    const gazebo = ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"];
    const kinematic = jobTypeResources(feed([sampleWorkerNode()]), "simulation");
    expect([kinematic.components, kinematic.workerNodes, kinematic.slots, kinematic.blocker]).toEqual([["asv_system/replay", "control_layer/none", "simulation_layer/kinematic"], 1, 8, null]);
    const missing = jobTypeResources(feed([sampleWorkerNode()]), "simulation", gazebo);
    expect(missing.blocker).toBe("No machine of the active cluster offers simulation with Replay, ArduPilot and Gazebo.");
    const withGazebo = sampleWorkerNode({ worker_node_id: "g", components: gazebo.map((component) => ({ component, images: [], state: "usable" })) });
    expect(jobTypeResources(feed([sampleWorkerNode(), withGazebo]), "simulation", gazebo).workerNodes).toBe(1);
  });

  it("explains a missing cluster, an unreachable one and one still loading", () => {
    expect(jobTypeResources(feed([], { operatorUrl: null }), "scene_generation").blocker).toMatch(/^No cluster is selected/);
    expect(jobTypeResources(feed([], { unreachable: true }), "scene_generation").blocker).toBe("The active cluster cannot be reached, so nothing can run on it.");
    expect(jobTypeResources(feed([], { loaded: false }), "scene_generation").blocker).toBe("Looking for the active cluster's machines...");
  });
});
