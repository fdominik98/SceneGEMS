import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MockWebSocket } from "../../test/mockWebSocket";
import { LiveChannel, type LiveChannelOptions, type TopicEvent } from "./liveChannel";

const URL = "ws://127.0.0.1:5174/cluster/live";

function makeChannel(options: LiveChannelOptions = {}) {
  return new LiveChannel(URL, {
    createSocket: MockWebSocket.factory,
    reconnectBaseMs: 100,
    reconnectMaxMs: 1000,
    pingIntervalMs: 1000,
    pongTimeoutMs: 500,
    idleCloseMs: 300,
    random: () => 0.5,
    ...options,
  });
}

function recorder() {
  const events: TopicEvent[] = [];
  return { events, listener: (event: TopicEvent) => events.push(event) };
}

/** A channel with an open socket. */
function openChannel(options: LiveChannelOptions = {}) {
  const channel = makeChannel(options);
  return { channel };
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LiveChannel subscriptions", () => {
  it("connects on the first subscription and subscribes once the socket opens", () => {
    const { channel } = openChannel();
    expect(MockWebSocket.instances).toHaveLength(0);
    const a = recorder();
    channel.subscribe("worker_nodes", a.listener);
    expect(channel.getStatus()).toBe("connecting");
    const socket = MockWebSocket.latest();
    expect(socket.url).toBe(URL);
    expect(socket.sent).toEqual([]);

    socket.open();
    expect(channel.getStatus()).toBe("open");
    expect(socket.sent).toEqual([{ type: "subscribe", version: 1, topic: "worker_nodes" }]);

    socket.receive({ type: "subscribed", topic: "worker_nodes", snapshot: [1] });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 1, data: "a" });
    expect(a.events).toEqual([
      { type: "snapshot", topic: "worker_nodes", snapshot: [1] },
      { type: "update", topic: "worker_nodes", seq: 1, data: "a" },
    ]);
  });

  it("shares a topic by reference count", () => {
    const { channel } = openChannel();
    const first = channel.subscribe("job:1", () => {});
    const socket = MockWebSocket.latest();
    socket.open();
    const second = channel.subscribe("job:1", () => {});
    expect(socket.sentOfType("subscribe")).toHaveLength(1);
    expect(channel.subscriberCount("job:1")).toBe(2);

    first();
    first();
    expect(channel.subscriberCount("job:1")).toBe(1);
    expect(socket.sentOfType("unsubscribe")).toHaveLength(0);

    second();
    expect(channel.subscriberCount("job:1")).toBe(0);
    expect(socket.sentOfType("unsubscribe")).toEqual([{ type: "unsubscribe", version: 1, topic: "job:1" }]);
  });

  it("replays the snapshot and the updates since to a later subscriber", () => {
    const { channel } = openChannel();
    channel.subscribe("campaign:c1", () => {});
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "campaign:c1", snapshot: { n: 0 } });
    socket.receive({ type: "update", topic: "campaign:c1", seq: 1, data: "x" });
    socket.receive({ type: "update", topic: "campaign:c1", seq: 2, data: "y" });

    const late = recorder();
    channel.subscribe("campaign:c1", late.listener);
    expect(late.events).toEqual([
      { type: "snapshot", topic: "campaign:c1", snapshot: { n: 0 } },
      { type: "update", topic: "campaign:c1", seq: 1, data: "x" },
      { type: "update", topic: "campaign:c1", seq: 2, data: "y" },
    ]);
    expect(socket.sentOfType("subscribe")).toHaveLength(1);
  });

  it("subscribes again for a later subscriber when the backlog overflowed", () => {
    const { channel } = openChannel({ backlogLimit: 2 });
    const early = recorder();
    channel.subscribe("instance:n/i", early.listener);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "instance:n/i", snapshot: "s1" });
    for (let seq = 1; seq <= 3; seq += 1) {
      socket.receive({ type: "update", topic: "instance:n/i", seq, data: seq });
    }
    socket.clearSent();

    const late = recorder();
    channel.subscribe("instance:n/i", late.listener);
    expect(late.events).toEqual([]);
    expect(socket.sent).toEqual([
      { type: "unsubscribe", version: 1, topic: "instance:n/i" },
      { type: "subscribe", version: 1, topic: "instance:n/i" },
    ]);

    socket.receive({ type: "unsubscribed", topic: "instance:n/i" });
    socket.receive({ type: "subscribed", topic: "instance:n/i", snapshot: "s2" });
    expect(late.events).toEqual([{ type: "snapshot", topic: "instance:n/i", snapshot: "s2" }]);
    expect(early.events.at(-1)).toEqual({ type: "snapshot", topic: "instance:n/i", snapshot: "s2" });
  });

  it("ignores updates before the snapshot and for topics nobody subscribes", () => {
    const { channel } = openChannel();
    const a = recorder();
    channel.subscribe("worker_nodes", a.listener);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "update", topic: "worker_nodes", seq: 1, data: "early" });
    socket.receive({ type: "update", topic: "job:9", seq: 1, data: "other" });
    socket.receive({ type: "subscribed", topic: "job:9", snapshot: {} });
    expect(a.events).toEqual([]);
  });

  it("passes a topic error to its subscribers", () => {
    const { channel } = openChannel();
    const a = recorder();
    channel.subscribe("job:missing", a.listener);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "error", topic: "job:missing", message: "unknown job missing" });
    expect(a.events).toEqual([{ type: "error", topic: "job:missing", message: "unknown job missing" }]);

    socket.receive({ type: "error", message: "malformed frame" });
    expect(channel.getLastError()).toBe("malformed frame");
  });

  it("tells a later subscriber of a refused topic the error instead of leaving it waiting", () => {
    const { channel } = openChannel();
    const a = recorder();
    channel.subscribe("campaign:gone", a.listener);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "error", topic: "campaign:gone", message: "unknown campaign gone" });
    const b = recorder();
    channel.subscribe("campaign:gone", b.listener);
    expect(b.events).toEqual([{ type: "error", topic: "campaign:gone", message: "unknown campaign gone" }]);
    // no second subscribe: the server's answer stands until the topic is subscribed anew
    expect(socket.sent.filter((message) => message.type === "subscribe")).toHaveLength(1);
  });
});

describe("LiveChannel sequence numbers", () => {
  function liveTopic() {
    const { channel } = openChannel();
    const a = recorder();
    channel.subscribe("worker_nodes", a.listener);
    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({ type: "subscribed", topic: "worker_nodes", snapshot: [] });
    socket.clearSent();
    return { channel, socket, a };
  }

  it("takes the first update after a snapshot as the baseline and drops repeated or older ones", () => {
    const { socket, a } = liveTopic();
    socket.receive({ type: "update", topic: "worker_nodes", seq: 5, data: "five" });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 5, data: "five again" });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 4, data: "four" });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 6, data: "six" });
    expect(a.events.filter((event) => event.type === "update").map((event) => (event as { data: unknown }).data)).toEqual(["five", "six"]);
    expect(socket.sent).toEqual([]);
  });

  it("subscribes again on a gap and resumes from the new snapshot", () => {
    const { socket, a } = liveTopic();
    socket.receive({ type: "update", topic: "worker_nodes", seq: 1, data: "one" });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 3, data: "three" });
    expect(socket.sent).toEqual([
      { type: "unsubscribe", version: 1, topic: "worker_nodes" },
      { type: "subscribe", version: 1, topic: "worker_nodes" },
    ]);
    socket.receive({ type: "update", topic: "worker_nodes", seq: 4, data: "stale" });
    socket.receive({ type: "subscribed", topic: "worker_nodes", snapshot: ["fresh"] });
    socket.receive({ type: "update", topic: "worker_nodes", seq: 1, data: "new one" });
    expect(a.events.map((event) => (event.type === "update" ? event.data : event.type === "snapshot" ? event.snapshot : null))).toEqual([
      [],
      "one",
      ["fresh"],
      "new one",
    ]);
  });
});

describe("LiveChannel connection", () => {
  it("reconnects with backoff and subscribes every topic again", () => {
    const { channel } = openChannel();
    const workerNodes = recorder();
    const job = recorder();
    channel.subscribe("worker_nodes", workerNodes.listener);
    channel.subscribe("job:1", job.listener);
    const first = MockWebSocket.latest();
    first.open();
    first.receive({ type: "subscribed", topic: "worker_nodes", snapshot: ["before"] });

    first.drop();
    expect(channel.getStatus()).toBe("reconnecting");
    vi.advanceTimersByTime(99);
    expect(MockWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2);

    // The second attempt fails before opening: the next delay doubles.
    MockWebSocket.latest().drop();
    vi.advanceTimersByTime(199);
    expect(MockWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    const third = MockWebSocket.latest();
    expect(MockWebSocket.instances).toHaveLength(3);

    third.open();
    expect(channel.getStatus()).toBe("open");
    expect(third.sentOfType("subscribe").map((message) => message.topic).sort()).toEqual(["job:1", "worker_nodes"]);
    third.receive({ type: "subscribed", topic: "worker_nodes", snapshot: ["after"] });
    expect(workerNodes.events.map((event) => (event.type === "snapshot" ? event.snapshot : null))).toEqual([["before"], ["after"]]);

    // A successful connection resets the backoff.
    third.drop();
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it("caps the backoff", () => {
    const { channel } = openChannel();
    channel.subscribe("worker_nodes", () => {});
    for (let attempt = 0; attempt < 6; attempt += 1) {
      MockWebSocket.latest().drop();
      vi.advanceTimersByTime(1000);
    }
    const count = MockWebSocket.instances.length;
    MockWebSocket.latest().drop();
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(count);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(count + 1);
  });

  it("pings and treats a silent connection as lost", () => {
    const { channel } = openChannel();
    channel.subscribe("worker_nodes", () => {});
    const socket = MockWebSocket.latest();
    socket.open();

    vi.advanceTimersByTime(1000);
    expect(socket.sentOfType("ping")).toEqual([{ type: "ping", version: 1 }]);
    socket.receive({ type: "pong" });
    vi.advanceTimersByTime(600);
    expect(channel.getStatus()).toBe("open");

    vi.advanceTimersByTime(400);
    expect(socket.sentOfType("ping")).toHaveLength(2);
    vi.advanceTimersByTime(500);
    expect(socket.closedByClient).toBe(true);
    expect(channel.getStatus()).toBe("reconnecting");
    expect(channel.getLastError()).toContain("no answer");
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("closes the socket after the last subscription has been gone for a while", () => {
    const { channel } = openChannel();
    const off = channel.subscribe("worker_nodes", () => {});
    const socket = MockWebSocket.latest();
    socket.open();
    off();
    vi.advanceTimersByTime(200);
    const again = channel.subscribe("worker_nodes", () => {});
    expect(socket.sentOfType("subscribe")).toHaveLength(2);
    vi.advanceTimersByTime(500);
    expect(socket.closedByClient).toBe(false);

    again();
    vi.advanceTimersByTime(300);
    expect(socket.closedByClient).toBe(true);
    expect(channel.getStatus()).toBe("idle");

    channel.subscribe("worker_nodes", () => {});
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("stops reconnecting when nobody subscribes", () => {
    const { channel } = openChannel();
    const off = channel.subscribe("worker_nodes", () => {});
    MockWebSocket.latest().drop();
    off();
    vi.advanceTimersByTime(5000);
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(channel.getStatus()).toBe("idle");
  });

  it("reports status changes and closes for good", () => {
    const { channel } = openChannel();
    const statuses: string[] = [];
    channel.onStatusChange((status) => statuses.push(status));
    channel.subscribe("worker_nodes", () => {});
    MockWebSocket.latest().open();
    channel.close();
    expect(statuses).toEqual(["connecting", "open", "closed"]);
    expect(() => channel.subscribe("worker_nodes", () => {})).toThrow();
  });
});
