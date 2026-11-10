import {
  configureMessage,
  parseServerMessage,
  pingMessage,
  subscribeMessage,
  unsubscribeMessage,
  type ClientMessage,
  type ServerMessage,
  type SubscribeOptions,
} from "./liveProtocol";

/**
 * Browser client of the control node's live channel: one WebSocket, topic subscriptions shared
 * by reference count across components.
 *
 * - The first subscriber of a topic sends `subscribe`, the last one to leave `unsubscribe`.
 *   A later subscriber gets the topic's snapshot and the updates since, replayed from a
 *   bounded backlog; when the backlog overflowed, the topic is subscribed again, so every
 *   subscriber starts over from a fresh snapshot.
 * - Updates carry a per-topic `seq`. The first update after a snapshot sets the baseline;
 *   an older or repeated one is dropped, a gap subscribes the topic again.
 * - A lost connection is reopened with exponential backoff and jitter; every topic is
 *   subscribed again, so subscribers get new snapshots. A `ping` goes out regularly and a
 *   connection that stays silent past the pong timeout is treated as lost.
 * - The socket opens with the first subscription and closes after the last one has been
 *   gone for `idleCloseMs`.
 *
 * Subscribers must treat every snapshot as a reset of the topic's state.
 */

export type LiveChannelStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export type TopicEvent =
  | { type: "snapshot"; topic: string; snapshot: unknown }
  | { type: "update"; topic: string; seq: number; data: unknown }
  | { type: "error"; topic: string; message: string };

export type TopicListener = (event: TopicEvent) => void;

/** The part of the browser WebSocket the channel uses, so tests can pass a fake. */
export interface WebSocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

export interface LiveChannelOptions {
  createSocket?: WebSocketFactory;
  pingIntervalMs?: number;
  pongTimeoutMs?: number;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
  idleCloseMs?: number;
  /** Updates kept per topic to replay to a later subscriber. */
  backlogLimit?: number;
  /** In [0, 1); spreads reconnect delays between 0.8 and 1.2 of their nominal value. */
  random?: () => number;
}

const SOCKET_OPEN = 1;

interface Subscription {
  listener: TopicListener;
}

interface TopicEntry {
  subscriptions: Set<Subscription>;
  /** Pending: waits for an open socket; subscribing: sent, no snapshot yet; live: has a snapshot; failed: the server refused it. */
  phase: "pending" | "subscribing" | "live" | "failed";
  snapshot: unknown;
  lastSeq: number | null;
  backlog: { seq: number; data: unknown }[];
  backlogComplete: boolean;
  /** Sent with every `subscribe` of the topic: the first subscriber's, then the latest `configure`. */
  options: SubscribeOptions | undefined;
  /** Why the server refused the topic (phase failed), told to a later subscriber as well. */
  error: string | null;
}

export class LiveChannel {
  readonly url: string;
  private readonly createSocket: WebSocketFactory;
  private readonly pingIntervalMs: number;
  private readonly pongTimeoutMs: number;
  private readonly reconnectBaseMs: number;
  private readonly reconnectMaxMs: number;
  private readonly idleCloseMs: number;
  private readonly backlogLimit: number;
  private readonly random: () => number;

  private readonly topics = new Map<string, TopicEntry>();
  private readonly statusListeners = new Set<(status: LiveChannelStatus) => void>();
  private socket: WebSocketLike | null = null;
  private status: LiveChannelStatus = "idle";
  private lastError: string | null = null;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(url: string, options: LiveChannelOptions = {}) {
    this.url = url;
    this.createSocket = options.createSocket ?? ((target) => new WebSocket(target) as unknown as WebSocketLike);
    this.pingIntervalMs = options.pingIntervalMs ?? 15_000;
    this.pongTimeoutMs = options.pongTimeoutMs ?? 10_000;
    this.reconnectBaseMs = options.reconnectBaseMs ?? 500;
    this.reconnectMaxMs = options.reconnectMaxMs ?? 15_000;
    this.idleCloseMs = options.idleCloseMs ?? 5_000;
    this.backlogLimit = options.backlogLimit ?? 500;
    this.random = options.random ?? Math.random;
  }

  getStatus(): LiveChannelStatus {
    return this.status;
  }

  /** The last connection or protocol problem, cleared when a connection opens. */
  getLastError(): string | null {
    return this.lastError;
  }

  /** Number of subscriptions of a topic (0 when nobody subscribes). */
  subscriberCount(topic: string): number {
    return this.topics.get(topic)?.subscriptions.size ?? 0;
  }

  /** Topics with at least one subscriber. */
  activeTopics(): string[] {
    return [...this.topics.keys()];
  }

  onStatusChange(listener: (status: LiveChannelStatus) => void): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  /**
   * Subscribes to a topic; the returned function ends this subscription (once). `options`
   * go out with the topic's `subscribe` (the first subscriber's count; later ones share it).
   */
  subscribe(topic: string, listener: TopicListener, options?: SubscribeOptions): () => void {
    if (this.closed) {
      throw new Error("the live channel is closed");
    }
    this.cancelIdleClose();
    const subscription: Subscription = { listener };
    let entry = this.topics.get(topic);
    if (!entry) {
      entry = {
        subscriptions: new Set(),
        phase: "pending",
        snapshot: undefined,
        lastSeq: null,
        backlog: [],
        backlogComplete: true,
        options,
        error: null,
      };
      this.topics.set(topic, entry);
      entry.subscriptions.add(subscription);
      if (this.isOpen()) {
        this.sendSubscribe(topic, entry);
      } else {
        this.connect();
      }
    } else {
      entry.subscriptions.add(subscription);
      if (entry.phase === "live") {
        if (entry.backlogComplete) {
          this.replay(topic, entry, subscription);
        } else {
          this.resubscribe(topic, entry);
        }
      } else if (entry.phase === "failed") {
        // The server refused it already: tell this subscriber too rather than leave it waiting for a snapshot
        subscription.listener({ type: "error", topic, message: entry.error ?? `the live channel refused ${topic}` });
      }
    }
    let active = true;
    return () => {
      if (!active) {
        return;
      }
      active = false;
      this.release(topic, subscription);
    };
  }

  /**
   * Changes the options of a subscribed topic (a simulation's speed): sent as `configure`
   * while the topic is subscribed, and kept for the next `subscribe` after a reconnect.
   * A no-op for a topic nobody subscribes to.
   */
  configure(topic: string, options: SubscribeOptions): void {
    const entry = this.topics.get(topic);
    if (!entry) {
      return;
    }
    entry.options = { ...entry.options, ...options };
    if (this.isOpen() && (entry.phase === "subscribing" || entry.phase === "live")) {
      this.send(configureMessage(topic, options));
    }
  }

  /** Closes the channel for good. */
  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.topics.clear();
    this.clearTimers();
    this.dropSocket();
    this.setStatus("closed");
  }

  private release(topic: string, subscription: Subscription): void {
    const entry = this.topics.get(topic);
    if (!entry || !entry.subscriptions.delete(subscription)) {
      return;
    }
    if (entry.subscriptions.size > 0) {
      return;
    }
    this.topics.delete(topic);
    if (this.isOpen() && (entry.phase === "subscribing" || entry.phase === "live")) {
      this.send(unsubscribeMessage(topic));
    }
    if (this.topics.size === 0) {
      this.scheduleIdleClose();
    }
  }

  private replay(topic: string, entry: TopicEntry, subscription: Subscription): void {
    subscription.listener({ type: "snapshot", topic, snapshot: entry.snapshot });
    for (const update of entry.backlog) {
      if (!entry.subscriptions.has(subscription)) {
        return;
      }
      subscription.listener({ type: "update", topic, seq: update.seq, data: update.data });
    }
  }

  private resubscribe(topic: string, entry: TopicEntry): void {
    if (!this.isOpen()) {
      return;
    }
    this.send(unsubscribeMessage(topic));
    this.sendSubscribe(topic, entry);
  }

  private sendSubscribe(topic: string, entry: TopicEntry): void {
    entry.phase = "subscribing";
    entry.error = null;
    entry.snapshot = undefined;
    entry.lastSeq = null;
    entry.backlog = [];
    entry.backlogComplete = true;
    this.send(subscribeMessage(topic, entry.options));
  }

  private isOpen(): boolean {
    return this.status === "open" && this.socket !== null && this.socket.readyState === SOCKET_OPEN;
  }

  private send(message: ClientMessage): void {
    try {
      this.socket?.send(JSON.stringify(message));
    } catch {
      // The close handler reconnects; the topics are subscribed again then.
    }
  }

  private connect(): void {
    if (this.closed || this.socket !== null || this.reconnectTimer !== null) {
      return;
    }
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    let socket: WebSocketLike;
    try {
      socket = this.createSocket(this.url);
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) {
        return;
      }
      this.attempt = 0;
      this.lastError = null;
      this.setStatus("open");
      this.startPing();
      for (const [topic, entry] of this.topics) {
        this.sendSubscribe(topic, entry);
      }
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket) {
        return;
      }
      this.receive(event.data);
    };
    socket.onerror = () => {
      if (this.socket === socket) {
        this.lastError = `the live channel at ${this.url} failed`;
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) {
        return;
      }
      this.lost();
    };
  }

  /** The connection is gone: reconnect while anyone subscribes, otherwise rest. */
  private lost(): void {
    this.dropSocket();
    this.stopPing();
    for (const entry of this.topics.values()) {
      entry.phase = "pending";
      entry.snapshot = undefined;
      entry.lastSeq = null;
      entry.backlog = [];
      entry.backlogComplete = true;
    }
    if (this.closed) {
      return;
    }
    if (this.topics.size === 0) {
      this.attempt = 0;
      this.setStatus("idle");
      return;
    }
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    this.attempt += 1;
    const nominal = Math.min(this.reconnectMaxMs, this.reconnectBaseMs * 2 ** (this.attempt - 1));
    const delay = Math.round(nominal * (0.8 + 0.4 * this.random()));
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.topics.size === 0) {
        this.attempt = 0;
        this.setStatus("idle");
        return;
      }
      this.connect();
    }, delay);
  }

  private receive(raw: unknown): void {
    this.clearPongDeadline();
    if (typeof raw !== "string") {
      this.lastError = "a live channel frame is not text";
      return;
    }
    const parsed = parseServerMessage(raw);
    if (!parsed.ok) {
      this.lastError = parsed.error;
      return;
    }
    this.handle(parsed.message);
  }

  private handle(message: ServerMessage): void {
    switch (message.type) {
      case "subscribed": {
        const entry = this.topics.get(message.topic);
        if (!entry || entry.phase !== "subscribing") {
          return;
        }
        entry.phase = "live";
        entry.snapshot = message.snapshot;
        this.emit(message.topic, entry, { type: "snapshot", topic: message.topic, snapshot: message.snapshot });
        return;
      }
      case "update": {
        const entry = this.topics.get(message.topic);
        if (!entry || entry.phase !== "live") {
          return;
        }
        if (entry.lastSeq !== null) {
          if (message.seq <= entry.lastSeq) {
            return;
          }
          if (message.seq > entry.lastSeq + 1) {
            this.resubscribe(message.topic, entry);
            return;
          }
        }
        entry.lastSeq = message.seq;
        if (entry.backlogComplete) {
          if (entry.backlog.length >= this.backlogLimit) {
            entry.backlog = [];
            entry.backlogComplete = false;
          } else {
            entry.backlog.push({ seq: message.seq, data: message.data });
          }
        }
        this.emit(message.topic, entry, { type: "update", topic: message.topic, seq: message.seq, data: message.data });
        return;
      }
      case "unsubscribed":
        // Sent after our unsubscribe; a topic subscribed again meanwhile waits for its snapshot.
        return;
      case "error": {
        const topic = message.topic ?? null;
        const entry = topic === null ? undefined : this.topics.get(topic);
        if (topic === null || !entry) {
          this.lastError = message.message;
          this.notifyStatus();
          return;
        }
        if (entry.phase === "subscribing") {
          entry.phase = "failed";
          entry.error = message.message;
        }
        this.emit(topic, entry, { type: "error", topic, message: message.message });
        return;
      }
      case "pong":
        return;
    }
  }

  private emit(topic: string, entry: TopicEntry, event: TopicEvent): void {
    for (const subscription of [...entry.subscriptions]) {
      if (this.topics.get(topic) !== entry || !entry.subscriptions.has(subscription)) {
        continue;
      }
      try {
        subscription.listener(event);
      } catch (error) {
        console.error(`live topic ${topic} listener failed`, error);
      }
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      if (!this.isOpen()) {
        return;
      }
      this.send(pingMessage());
      if (this.pongTimer === null) {
        this.pongTimer = setTimeout(() => {
          this.pongTimer = null;
          this.lastError = `no answer from the live channel within ${Math.round(this.pongTimeoutMs / 1000)} s`;
          this.lost();
        }, this.pongTimeoutMs);
      }
    }, this.pingIntervalMs);
  }

  private stopPing(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    this.clearPongDeadline();
  }

  private clearPongDeadline(): void {
    if (this.pongTimer !== null) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private scheduleIdleClose(): void {
    this.cancelIdleClose();
    if (this.socket === null && this.reconnectTimer === null) {
      return;
    }
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.topics.size > 0) {
        return;
      }
      if (this.reconnectTimer !== null) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      this.stopPing();
      this.dropSocket();
      this.attempt = 0;
      this.setStatus("idle");
    }, this.idleCloseMs);
  }

  private cancelIdleClose(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  private clearTimers(): void {
    this.cancelIdleClose();
    this.stopPing();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /** Detaches and closes the socket without reacting to its close event. */
  private dropSocket(): void {
    const socket = this.socket;
    this.socket = null;
    if (!socket) {
      return;
    }
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try {
      socket.close(1000, "closed by the client");
    } catch {
      // Already closed.
    }
  }

  private setStatus(status: LiveChannelStatus): void {
    if (this.status === status) {
      return;
    }
    this.status = status;
    this.notifyStatus();
  }

  private notifyStatus(): void {
    for (const listener of [...this.statusListeners]) {
      listener(this.status);
    }
  }
}
