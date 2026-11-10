import { z } from "zod";

/**
 * Wire format of the control node's live channel (`/cluster/live` on the operator listener),
 * version 1 of the contract in design doc section 5.3, which the server implements in
 * `backend/src/scenegems_tool/cluster/protocol/live.py`. JSON text frames; every message
 * carries `"version": 1`.
 */

export const LIVE_PROTOCOL_VERSION = 1;

export const WORKER_NODES_TOPIC = "worker_nodes";

/** Every entry of Campaign History (design doc 6.5): the snapshot is `{}`, updates carry a changed list row or a deleted id. */
export const CAMPAIGNS_TOPIC = "campaigns";

export function campaignTopic(campaignId: string): string {
  return `campaign:${campaignId}`;
}

export function jobTopic(jobId: string): string {
  return `job:${jobId}`;
}

export function instanceTopic(workerNodeId: string, instance: string): string {
  return `instance:${workerNodeId}/${instance}`;
}

/** The instance name of a job's attempt, as the worker node runs it. */
export function jobInstanceName(jobId: string, attempt: number): string {
  return `job-${jobId}-${attempt}`;
}

export type ParsedTopic =
  | { kind: "worker_nodes" }
  | { kind: "campaign"; campaignId: string }
  | { kind: "job"; jobId: string }
  | { kind: "instance"; workerNodeId: string; instance: string };

export function parseTopic(topic: string): ParsedTopic | null {
  if (topic === WORKER_NODES_TOPIC) {
    return { kind: "worker_nodes" };
  }
  const colon = topic.indexOf(":");
  if (colon <= 0) {
    return null;
  }
  const prefix = topic.slice(0, colon);
  const rest = topic.slice(colon + 1);
  if (rest.length === 0) {
    return null;
  }
  if (prefix === "campaign") {
    return { kind: "campaign", campaignId: rest };
  }
  if (prefix === "job") {
    return { kind: "job", jobId: rest };
  }
  if (prefix === "instance") {
    const slash = rest.indexOf("/");
    if (slash <= 0 || slash === rest.length - 1) {
      return null;
    }
    return { kind: "instance", workerNodeId: rest.slice(0, slash), instance: rest.slice(slash + 1) };
  }
  return null;
}

// Client to server

/**
 * Options of an observed job instance topic (live simulations, design doc 5.3 "Wave 2 contracts"):
 * `speed` is the multiple of real time an observed run is paced to (the control node's default is 10).
 */
export interface SubscribeOptions {
  speed?: number;
}

export type ClientMessage =
  | { type: "subscribe"; version: 1; topic: string; options?: SubscribeOptions }
  | { type: "unsubscribe"; version: 1; topic: string }
  | { type: "configure"; version: 1; topic: string; options: SubscribeOptions }
  | { type: "ping"; version: 1 };

export function subscribeMessage(topic: string, options?: SubscribeOptions): ClientMessage {
  return options && Object.keys(options).length > 0
    ? { type: "subscribe", version: LIVE_PROTOCOL_VERSION, topic, options }
    : { type: "subscribe", version: LIVE_PROTOCOL_VERSION, topic };
}

/** Changes the options of a subscribed topic; the latest request wins for every observer of the job. */
export function configureMessage(topic: string, options: SubscribeOptions): ClientMessage {
  return { type: "configure", version: LIVE_PROTOCOL_VERSION, topic, options };
}

export function unsubscribeMessage(topic: string): ClientMessage {
  return { type: "unsubscribe", version: LIVE_PROTOCOL_VERSION, topic };
}

export function pingMessage(): ClientMessage {
  return { type: "ping", version: LIVE_PROTOCOL_VERSION };
}

// Server to client

const version = z.literal(LIVE_PROTOCOL_VERSION);

export const subscribedMessageSchema = z.object({
  type: z.literal("subscribed"),
  version,
  topic: z.string(),
  /** The topic's current state; its shape depends on the topic (`liveTopics.ts`). */
  snapshot: z.unknown(),
});

export const updateMessageSchema = z.object({
  type: z.literal("update"),
  version,
  topic: z.string(),
  /** Per topic, from 1. */
  seq: z.number().int().min(1),
  data: z.unknown(),
});

export const unsubscribedMessageSchema = z.object({
  type: z.literal("unsubscribed"),
  version,
  topic: z.string(),
});

export const errorMessageSchema = z.object({
  type: z.literal("error"),
  version,
  message: z.string(),
  topic: z.string().nullable().optional(),
});

export const pongMessageSchema = z.object({
  type: z.literal("pong"),
  version,
});

export const serverMessageSchema = z.discriminatedUnion("type", [
  subscribedMessageSchema,
  updateMessageSchema,
  unsubscribedMessageSchema,
  errorMessageSchema,
  pongMessageSchema,
]);

export type ServerMessage = z.infer<typeof serverMessageSchema>;

/** A server frame parsed and checked, or the reason it is not one. */
export function parseServerMessage(text: string): { ok: true; message: ServerMessage } | { ok: false; error: string } {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: "a live channel frame is not JSON" };
  }
  const parsed = serverMessageSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    return { ok: false, error: `unexpected live channel frame (${issue ? `${issue.path.join(".")}: ${issue.message}` : "unknown"})` };
  }
  return { ok: true, message: parsed.data };
}
