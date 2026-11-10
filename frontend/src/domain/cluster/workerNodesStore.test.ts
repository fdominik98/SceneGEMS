import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleWorkerNode } from "../../test/fixtures/clusterViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { LiveChannel } from "./liveChannel";
import { acquireWorkerNodesFeed, startWorkerNodesFeed, useWorkerNodesStore } from "./workerNodesStore";
import { resetLiveChannels } from "./liveChannels";
import { workerNodeViewSchema, type WorkerNodeView } from "./schemas";
import { OperatorApiError, type OperatorClient } from "./operatorApi";

const URL = "http://127.0.0.1:5174";

function workerNode(overrides: Record<string, unknown> = {}): WorkerNodeView {
  return workerNodeViewSchema.parse(sampleWorkerNode(overrides));
}

function fakeClient(listWorkerNodes: () => Promise<{ items: WorkerNodeView[]; total: number | null }>) {
  const spy = vi.fn(listWorkerNodes);
  return { client: { listWorkerNodes: spy } as unknown as OperatorClient, spy };
}

function makeChannel() {
  return new LiveChannel("ws://127.0.0.1:5174/cluster/live", { createSocket: MockWebSocket.factory, reconnectBaseMs: 100, random: () => 0.5 });
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("worker nodes feed", () => {
  it("polls while the live channel is down, then follows the worker nodes topic", async () => {
    const { client, spy } = fakeClient(async () => ({ items: [workerNode({ worker_node_id: "b", name: "worker-b" }), workerNode()], total: null }));
    const stop = startWorkerNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(useWorkerNodesStore.getState()).toMatchObject({ operatorUrl: URL, loaded: true, source: "poll", error: null });
    expect(useWorkerNodesStore.getState().workerNodes.map((entry) => entry.name)).toEqual(["worker-a", "worker-b"]);

    await vi.advanceTimersByTimeAsync(1000);
    expect(spy).toHaveBeenCalledTimes(2);

    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "worker_nodes", snapshot: [sampleWorkerNode({ status: "draining" })] });
    expect(useWorkerNodesStore.getState().source).toBe("live");
    expect(useWorkerNodesStore.getState().workerNodes[0].status).toBe("draining");

    await vi.advanceTimersByTimeAsync(5000);
    expect(spy).toHaveBeenCalledTimes(2);

    socket.receive({ type: "update", topic: "worker_nodes", seq: 1, data: { removed: "worker-node-a1" } });
    expect(useWorkerNodesStore.getState().workerNodes).toEqual([]);

    socket.drop();
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(3);
    expect(useWorkerNodesStore.getState().source).toBe("poll");

    stop();
    expect(useWorkerNodesStore.getState().operatorUrl).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("marks an unreachable control node and keeps polling", async () => {
    const { client, spy } = fakeClient(async () => {
      throw new OperatorApiError("network", "cannot reach http://127.0.0.1:5174 (Failed to fetch)", "/cluster/worker-nodes");
    });
    const stop = startWorkerNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(useWorkerNodesStore.getState()).toMatchObject({ loaded: false, unreachable: true });
    expect(useWorkerNodesStore.getState().error).toContain("cannot reach");
    await vi.advanceTimersByTimeAsync(1000);
    expect(spy).toHaveBeenCalledTimes(2);
    stop();
  });

  it("applies a worker node from a drain or resume answer", async () => {
    const { client } = fakeClient(async () => ({ items: [workerNode()], total: null }));
    const stop = startWorkerNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    useWorkerNodesStore.getState().applyWorkerNode(workerNode({ status: "draining" }));
    expect(useWorkerNodesStore.getState().workerNodes).toHaveLength(1);
    expect(useWorkerNodesStore.getState().workerNodes[0].status).toBe("draining");
    stop();
  });

  it("drops a worker node the control node forgot", async () => {
    const { client } = fakeClient(async () => ({ items: [workerNode(), workerNode({ worker_node_id: "worker-node-b", name: "worker-b" })], total: null }));
    const stop = startWorkerNodesFeed(URL, { client, channel: makeChannel(), pollIntervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    useWorkerNodesStore.getState().removeWorkerNode("worker-node-b");
    expect(useWorkerNodesStore.getState().workerNodes.map((entry) => entry.worker_node_id)).not.toContain("worker-node-b");
    expect(useWorkerNodesStore.getState().workerNodes).toHaveLength(1);
    stop();
  });

  it("shares one feed per cluster between components", async () => {
    resetLiveChannels({ createSocket: MockWebSocket.factory });
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify([sampleWorkerNode()]), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const releaseA = acquireWorkerNodesFeed(URL);
    const releaseB = acquireWorkerNodesFeed(URL);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(1);

    releaseA();
    releaseA();
    expect(useWorkerNodesStore.getState().operatorUrl).toBe(URL);
    releaseB();
    expect(useWorkerNodesStore.getState().operatorUrl).toBeNull();
    resetLiveChannels();
  });
});
