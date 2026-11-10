import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveChannel } from "../../../domain/cluster/liveChannel";
import { instanceReducer } from "../../../domain/cluster/liveTopics";
import { LiveTopicWatcher } from "../../../domain/cluster/liveTopicWatcher";
import { poolSnapshot } from "../../../test/fixtures/observeViews";
import { MockWebSocket } from "../../../test/mockWebSocket";

/**
 * What `useObservedInstance` does for a mounted viewer: it watches its topic from mount to
 * unmount (the section keys the viewer by topic, so a changed instance is an unmount and a
 * mount). The project has no DOM test environment, so the lifecycle is driven here through
 * the same watcher and channel.
 */

const SCENE = "instance:worker-node-a1/scene_generation-0";
const TRAJ = "instance:worker-node-a1/trajectory_generation-0";

function makeChannel() {
  return new LiveChannel("ws://m/cluster/live", { createSocket: MockWebSocket.factory, idleCloseMs: 5_000 });
}

function view(channel: LiveChannel, topic: string) {
  return new LiveTopicWatcher(channel, topic, instanceReducer).subscribe(() => {});
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("observing one instance at a time", () => {
  it("subscribes only to the viewed instance and unsubscribes when the view closes", () => {
    const channel = makeChannel();
    const close = view(channel, SCENE);
    const socket = MockWebSocket.latest();
    socket.open();
    expect(socket.sentOfType("subscribe").map((message) => message.topic)).toEqual([SCENE]);

    close();
    expect(socket.sentOfType("unsubscribe").map((message) => message.topic)).toEqual([SCENE]);
    expect(channel.activeTopics()).toEqual([]);
  });

  it("moves the subscription when the viewed instance changes", () => {
    const channel = makeChannel();
    const closeScene = view(channel, SCENE);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: SCENE, snapshot: poolSnapshot("scene_generation-0") });

    closeScene();
    view(channel, TRAJ);
    expect(socket.sentOfType("subscribe").map((message) => message.topic)).toEqual([SCENE, TRAJ]);
    expect(socket.sentOfType("unsubscribe").map((message) => message.topic)).toEqual([SCENE]);
    expect(channel.activeTopics()).toEqual([TRAJ]);
    expect(channel.subscriberCount(SCENE)).toBe(0);
  });

  it("ends the control node's observation only when the last view of an instance leaves", () => {
    const channel = makeChannel();
    const first = view(channel, SCENE);
    const second = view(channel, SCENE);
    const socket = MockWebSocket.latest();
    socket.open();
    first();
    expect(socket.sentOfType("unsubscribe")).toEqual([]);
    second();
    expect(socket.sentOfType("unsubscribe").map((message) => message.topic)).toEqual([SCENE]);
  });

  it("keeps no subscription after leaving the section and closes the idle socket", () => {
    const channel = makeChannel();
    const close = view(channel, SCENE);
    const socket = MockWebSocket.latest();
    socket.open();
    close();
    vi.advanceTimersByTime(5_000);
    expect(channel.getStatus()).toBe("idle");
    expect(socket.closedByClient).toBe(true);
  });
});
