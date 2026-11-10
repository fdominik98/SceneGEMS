import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

/** A cluster the UI knows: a control node's operator API, reached directly or over an SSH tunnel. */
export interface ClusterEntry {
  id: string;
  name: string;
  /** Base URL of the control node's operator listener, without a trailing slash. */
  operatorUrl: string;
}

export interface ClusterInput {
  name: string;
  operatorUrl: string;
}

export const DEFAULT_OPERATOR_URL = "http://127.0.0.1:5174";
export const LIVE_CHANNEL_PATH = "/cluster/live";
export const CLUSTERS_STORAGE_KEY = "scenegems:clusters";

const DEFAULT_CLUSTER: ClusterEntry = {
  id: "local",
  name: "Local control node",
  operatorUrl: DEFAULT_OPERATOR_URL,
};

/** The operator URL as stored (http or https, no trailing slash, no query), or null when it is not one. */
export function normalizeOperatorUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || url.search || url.hash) {
    return null;
  }
  return `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}`;
}

/** The live channel's WebSocket URL for an operator URL: ws for http, wss for https. */
export function liveChannelUrl(operatorUrl: string): string {
  return operatorUrl.replace(/^http(s?):\/\//i, (_match, secure: string) => `ws${secure}://`) + LIVE_CHANNEL_PATH;
}

/** The input with a trimmed name and a normalized URL, or the reason it is refused. */
export function validateClusterInput(
  input: ClusterInput,
  existing: readonly ClusterEntry[],
  editingId: string | null = null
): { ok: true; value: ClusterInput } | { ok: false; error: string } {
  const name = input.name.trim();
  if (name.length === 0) {
    return { ok: false, error: "Give the cluster a name." };
  }
  const taken = existing.some(
    (cluster) => cluster.id !== editingId && cluster.name.toLowerCase() === name.toLowerCase()
  );
  if (taken) {
    return { ok: false, error: `A cluster named "${name}" exists already.` };
  }
  const operatorUrl = normalizeOperatorUrl(input.operatorUrl);
  if (operatorUrl === null) {
    return { ok: false, error: "The operator URL must be an http or https URL, such as http://127.0.0.1:5174." };
  }
  return { ok: true, value: { name, operatorUrl } };
}

let idCounter = 0;

function newClusterId(): string {
  idCounter += 1;
  return `cluster-${Date.now().toString(36)}-${idCounter}`;
}

export interface ClusterListState {
  clusters: ClusterEntry[];
  selectedClusterId: string | null;
  /** Adds a cluster (selected when none is) and returns it, or the reason it is refused. */
  addCluster: (input: ClusterInput) => { ok: true; cluster: ClusterEntry } | { ok: false; error: string };
  updateCluster: (id: string, input: ClusterInput) => { ok: true } | { ok: false; error: string };
  /** Removes a cluster; when it was selected, the first remaining one is selected. */
  removeCluster: (id: string) => void;
  selectCluster: (id: string | null) => void;
}

export function selectSelectedCluster(state: Pick<ClusterListState, "clusters" | "selectedClusterId">): ClusterEntry | null {
  return state.clusters.find((cluster) => cluster.id === state.selectedClusterId) ?? null;
}

/** The cluster list store, kept per browser. Tests pass an in-memory storage. */
export function createClusterStore(storage?: StateStorage) {
  return create<ClusterListState>()(
    persist(
      (set, get) => ({
        clusters: [DEFAULT_CLUSTER],
        selectedClusterId: DEFAULT_CLUSTER.id,
        addCluster: (input) => {
          const checked = validateClusterInput(input, get().clusters);
          if (!checked.ok) {
            return checked;
          }
          const cluster: ClusterEntry = { id: newClusterId(), ...checked.value };
          set((state) => ({
            clusters: [...state.clusters, cluster],
            selectedClusterId: selectSelectedCluster(state) ? state.selectedClusterId : cluster.id,
          }));
          return { ok: true, cluster };
        },
        updateCluster: (id, input) => {
          const checked = validateClusterInput(input, get().clusters, id);
          if (!checked.ok) {
            return checked;
          }
          set((state) => ({
            clusters: state.clusters.map((cluster) => (cluster.id === id ? { ...cluster, ...checked.value } : cluster)),
          }));
          return { ok: true };
        },
        removeCluster: (id) =>
          set((state) => {
            const clusters = state.clusters.filter((cluster) => cluster.id !== id);
            const selectedClusterId =
              state.selectedClusterId === id ? (clusters[0]?.id ?? null) : state.selectedClusterId;
            return { clusters, selectedClusterId };
          }),
        selectCluster: (id) =>
          set((state) => ({
            selectedClusterId: id !== null && state.clusters.some((cluster) => cluster.id === id) ? id : null,
          })),
      }),
      {
        name: CLUSTERS_STORAGE_KEY,
        version: 1,
        storage: createJSONStorage(() => storage ?? localStorage),
        partialize: (state) => ({ clusters: state.clusters, selectedClusterId: state.selectedClusterId }),
      }
    )
  );
}

export const useClusterStore = createClusterStore();

/** The selected cluster, or null when none is selected. */
export function useSelectedCluster(): ClusterEntry | null {
  return useClusterStore(selectSelectedCluster);
}
