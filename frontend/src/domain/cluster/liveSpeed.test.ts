import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jobInstanceSnapshot } from "../../test/fixtures/observeViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { LiveChannel } from "./liveChannel";
import { configureMessage, subscribeMessage } from "./liveProtocol";
import { instanceReducer } from "./liveTopics";
import { LiveTopicWatcher } from "./liveTopicWatcher";

const TOPIC = "instance:worker-node-a1/job-job-1-1";

function makeChannel() {
  return new LiveChannel("ws://m/cluster/live", { createSocket: MockWebSocket.factory, reconnectBaseMs: 100, random: () => 0.5 });
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("speed messages", () => {
  it("builds subscribe with options and configure as the contract has them", () => {
    expect(subscribeMessage("job:1")).toEqual({ type: "subscribe", version: 1, topic: "job:1" });
    expect(subscribeMessage(TOPIC, { speed: 25 })).toEqual({ type: "subscribe", version: 1, topic: TOPIC, options: { speed: 25 } });
    expect(subscribeMessage(TOPIC, {})).toEqual({ type: "subscribe", version: 1, topic: TOPIC });
    expect(configureMessage(TOPIC, { speed: 5 })).toEqual({ type: "configure", version: 1, topic: TOPIC, options: { speed: 5 } });
  });

  it("sends the speed with the subscribe when opening the view", () => {
    const channel = makeChannel();
    channel.subscribe(TOPIC, () => {}, { speed: 10 });
    const socket = MockWebSocket.latest();
    socket.open();
    expect(socket.sentOfType("subscribe")).toEqual([{ type: "subscribe", version: 1, topic: TOPIC, options: { speed: 10 } }]);
  });

  it("sends configure for a changed speed once subscribed, and folds an earlier request into the subscribe", () => {
    const channel = makeChannel();
    channel.subscribe(TOPIC, () => {}, { speed: 10 });
    channel.configure(TOPIC, { speed: 2 });
    const socket = MockWebSocket.latest();
    socket.open();
    expect(socket.sentOfType("subscribe")[0]).toMatchObject({ options: { speed: 2 } });
    expect(socket.sentOfType("configure")).toEqual([]);

    socket.receive({ type: "subscribed", topic: TOPIC, snapshot: jobInstanceSnapshot() });
    channel.configure(TOPIC, { speed: 50 });
    expect(socket.sentOfType("configure")).toEqual([{ type: "configure", version: 1, topic: TOPIC, options: { speed: 50 } }]);
  });

  it("keeps the latest speed for the subscribe after a reconnect", () => {
    const channel = makeChannel();
    channel.subscribe(TOPIC, () => {}, { speed: 10 });
    const first = MockWebSocket.latest();
    first.open();
    first.receive({ type: "subscribed", topic: TOPIC, snapshot: jobInstanceSnapshot() });
    channel.configure(TOPIC, { speed: 100 });
    first.drop();
    vi.advanceTimersByTime(100);
    const second = MockWebSocket.latest();
    second.open();
    expect(second.sentOfType("subscribe")).toEqual([{ type: "subscribe", version: 1, topic: TOPIC, options: { speed: 100 } }]);
  });

  it("ignores configure for a topic nobody subscribes to", () => {
    const channel = makeChannel();
    channel.subscribe("worker_nodes", () => {});
    const socket = MockWebSocket.latest();
    socket.open();
    socket.clearSent();
    channel.configure(TOPIC, { speed: 5 });
    expect(socket.sent).toEqual([]);
  });

  it("goes through the watcher: options at subscribe, configure on demand", () => {
    const channel = makeChannel();
    const watcher = new LiveTopicWatcher(channel, TOPIC, instanceReducer, { speed: 10 });
    const off = watcher.subscribe(() => {});
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: TOPIC, snapshot: jobInstanceSnapshot() });
    expect(watcher.getState().data?.info.observed_speed).toBe(10);
    watcher.configure({ speed: 1 });
    expect(socket.sentOfType("configure")).toHaveLength(1);
    expect(socket.sentOfType("subscribe")[0]).toMatchObject({ options: { speed: 10 } });
    off();
  });

  it("shows the pace the control node reports: from the snapshot, then from a status update", () => {
    const state = instanceReducer.snapshot(jobInstanceSnapshot("job-1", 1, { observed_speed: 10 }));
    expect(state.info.observed_speed).toBe(10);
    const unreported = instanceReducer.snapshot({ ...jobInstanceSnapshot(), observed_speed: undefined });
    expect(unreported.info.observed_speed).toBeUndefined();
    const updated = instanceReducer.update(state, { kind: "status", state: "running", message: "step 4", progress: 0.2, observed_speed: 25 }, 1);
    expect(updated.info.observed_speed).toBe(25);
    const unchanged = instanceReducer.update(updated, { kind: "status", state: "running", message: "step 5", progress: 0.3 }, 2);
    expect(unchanged.info.observed_speed).toBe(25);
  });
});
