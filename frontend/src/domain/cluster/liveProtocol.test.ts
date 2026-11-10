import { describe, expect, it } from "vitest";
import {
  campaignTopic,
  instanceTopic,
  jobInstanceName,
  jobTopic,
  WORKER_NODES_TOPIC,
  parseServerMessage,
  parseTopic,
  pingMessage,
  subscribeMessage,
  unsubscribeMessage,
} from "./liveProtocol";

describe("live channel protocol", () => {
  it("names and parses topics", () => {
    expect(parseTopic(WORKER_NODES_TOPIC)).toEqual({ kind: "worker_nodes" });
    expect(parseTopic(campaignTopic("c1"))).toEqual({ kind: "campaign", campaignId: "c1" });
    expect(parseTopic(jobTopic("j:1"))).toEqual({ kind: "job", jobId: "j:1" });
    const instance = instanceTopic("worker-node-a", jobInstanceName("job-9", 2));
    expect(instance).toBe("instance:worker-node-a/job-job-9-2");
    expect(parseTopic(instance)).toEqual({ kind: "instance", workerNodeId: "worker-node-a", instance: "job-job-9-2" });
    expect(parseTopic("instance:worker-node-a")).toBeNull();
    expect(parseTopic("campaign:")).toBeNull();
    expect(parseTopic("weather:today")).toBeNull();
  });

  it("builds client messages with the version", () => {
    expect(subscribeMessage("worker_nodes")).toEqual({ type: "subscribe", version: 1, topic: "worker_nodes" });
    expect(unsubscribeMessage("worker_nodes")).toEqual({ type: "unsubscribe", version: 1, topic: "worker_nodes" });
    expect(pingMessage()).toEqual({ type: "ping", version: 1 });
  });

  it("parses every server message", () => {
    const frames = [
      { type: "subscribed", version: 1, topic: "worker_nodes", snapshot: [] },
      { type: "update", version: 1, topic: "worker_nodes", seq: 1, data: { removed: "n" } },
      { type: "unsubscribed", version: 1, topic: "worker_nodes" },
      { type: "error", version: 1, message: "unknown topic", topic: "job:x" },
      { type: "error", version: 1, message: "bad frame" },
      { type: "pong", version: 1 },
    ];
    for (const frame of frames) {
      const parsed = parseServerMessage(JSON.stringify(frame));
      expect(parsed.ok).toBe(true);
    }
  });

  it("refuses frames of another version, unknown types and bad seq", () => {
    expect(parseServerMessage(JSON.stringify({ type: "pong", version: 2 })).ok).toBe(false);
    expect(parseServerMessage(JSON.stringify({ type: "hello", version: 1 })).ok).toBe(false);
    expect(parseServerMessage(JSON.stringify({ type: "update", version: 1, topic: "worker_nodes", seq: 0, data: {} })).ok).toBe(false);
    expect(parseServerMessage("not json").ok).toBe(false);
  });
});
