import { useEffect } from "react";
import { create } from "zustand";
import type { LiveChannel } from "./liveChannel";
import { getLiveChannel } from "./liveChannels";
import { WORKER_NODES_TOPIC } from "./liveProtocol";
import { workerNodesReducer, upsertWorkerNode } from "./liveTopics";
import { LiveTopicWatcher } from "./liveTopicWatcher";
import { createOperatorClient, describeOperatorError, OperatorApiError, type OperatorClient } from "./operatorApi";
import type { WorkerNodeView } from "./schemas";

/**
 * The worker nodes of the selected cluster: fed by the live channel's `worker_nodes` topic, and by a
 * REST poll of `GET /cluster/worker-nodes` while the topic is not live (channel down, topic
 * refused, or a control node without the live channel).
 */

export type WorkerNodesSource = "live" | "poll";

export interface WorkerNodesState {
  /** The operator URL the worker nodes belong to, or null when no feed runs. */
  operatorUrl: string | null;
  workerNodes: WorkerNodeView[];
  /** Whether any answer arrived for this cluster yet. */
  loaded: boolean;
  source: WorkerNodesSource | null;
  /** The last problem of the poll, cleared by the next answer. */
  error: string | null;
  /** True when the last poll could not reach the control node at all. */
  unreachable: boolean;
  /** Wall time (ms) of the last change. */
  updatedAt: number | null;
  /** Puts a worker node view from another answer (drain, resume) into the list. */
  applyWorkerNode: (workerNode: WorkerNodeView) => void;
  /** Drops a worker node the control node forgot. */
  removeWorkerNode: (workerNodeId: string) => void;
}

const EMPTY = {
  workerNodes: [] as WorkerNodeView[],
  loaded: false,
  source: null,
  error: null,
  unreachable: false,
  updatedAt: null,
};

export const useWorkerNodesStore = create<WorkerNodesState>()((set) => ({
  operatorUrl: null,
  ...EMPTY,
  applyWorkerNode: (workerNode) => set((state) => ({ workerNodes: upsertWorkerNode(state.workerNodes, workerNode), updatedAt: Date.now() })),
  removeWorkerNode: (workerNodeId) => set((state) => ({ workerNodes: state.workerNodes.filter((workerNode) => workerNode.worker_node_id !== workerNodeId), updatedAt: Date.now() })),
}));

export interface WorkerNodesFeedOptions {
  channel?: LiveChannel;
  client?: OperatorClient;
  pollIntervalMs?: number;
  store?: typeof useWorkerNodesStore;
  now?: () => number;
}

export const WORKER_NODES_POLL_INTERVAL_MS = 5_000;

/** Starts feeding the store with the worker nodes of one cluster; returns the function that stops it. */
export function startWorkerNodesFeed(operatorUrl: string, options: WorkerNodesFeedOptions = {}): () => void {
  const store = options.store ?? useWorkerNodesStore;
  const client = options.client ?? createOperatorClient(operatorUrl);
  const channel = options.channel ?? getLiveChannel(operatorUrl);
  const pollIntervalMs = options.pollIntervalMs ?? WORKER_NODES_POLL_INTERVAL_MS;
  const now = options.now ?? Date.now;

  store.setState({ operatorUrl, ...EMPTY });

  let stopped = false;
  let live = false;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollAbort: AbortController | null = null;

  const poll = async () => {
    pollTimer = null;
    pollAbort = new AbortController();
    try {
      const { items } = await client.listWorkerNodes(pollAbort.signal);
      if (!stopped && !live) {
        store.setState({ workerNodes: [...items].sort((a, b) => a.name.localeCompare(b.name)), loaded: true, source: "poll", error: null, unreachable: false, updatedAt: now() });
      }
    } catch (error) {
      if (!stopped && !live) {
        store.setState({ error: describeOperatorError(error), unreachable: error instanceof OperatorApiError && error.unreachable });
      }
    } finally {
      pollAbort = null;
    }
    if (!stopped && !live) {
      pollTimer = setTimeout(() => void poll(), pollIntervalMs);
    }
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    pollAbort?.abort();
    pollAbort = null;
  };

  const watcher = new LiveTopicWatcher(channel, WORKER_NODES_TOPIC, workerNodesReducer);
  const onTopic = () => {
    const state = watcher.getState();
    if (state.status === "live" && state.data !== null) {
      live = true;
      stopPolling();
      store.setState({ workerNodes: state.data, loaded: true, source: "live", error: null, unreachable: false, updatedAt: now() });
      return;
    }
    if (live) {
      live = false;
      if (pollTimer === null && pollAbort === null) {
        void poll();
      }
    }
  };
  const offTopic = watcher.subscribe(onTopic);
  if (!live) {
    void poll();
  }

  return () => {
    stopped = true;
    stopPolling();
    offTopic();
    if (store.getState().operatorUrl === operatorUrl) {
      store.setState({ operatorUrl: null, ...EMPTY });
    }
  };
}

const feeds = new Map<string, { count: number; stop: () => void }>();

/** Shares one feed per cluster between components; returns the release function. */
export function acquireWorkerNodesFeed(operatorUrl: string): () => void {
  let feed = feeds.get(operatorUrl);
  if (!feed) {
    feed = { count: 0, stop: startWorkerNodesFeed(operatorUrl) };
    feeds.set(operatorUrl, feed);
  }
  feed.count += 1;
  let released = false;
  return () => {
    if (released) {
      return;
    }
    released = true;
    const current = feeds.get(operatorUrl);
    if (!current) {
      return;
    }
    current.count -= 1;
    if (current.count === 0) {
      feeds.delete(operatorUrl);
      current.stop();
    }
  };
}

/** Keeps the worker nodes feed of a cluster running while the calling component is mounted. */
export function useWorkerNodesFeed(operatorUrl: string | null): void {
  useEffect(() => (operatorUrl ? acquireWorkerNodesFeed(operatorUrl) : undefined), [operatorUrl]);
}
