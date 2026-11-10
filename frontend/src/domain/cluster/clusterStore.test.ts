import { describe, expect, it } from "vitest";
import { MemoryStorage } from "../../test/memoryStorage";
import {
  CLUSTERS_STORAGE_KEY,
  DEFAULT_OPERATOR_URL,
  createClusterStore,
  liveChannelUrl,
  normalizeOperatorUrl,
  selectSelectedCluster,
  validateClusterInput,
} from "./clusterStore";

describe("operator URLs", () => {
  it("normalizes http and https URLs and refuses others", () => {
    expect(normalizeOperatorUrl(" http://127.0.0.1:5174/ ")).toBe("http://127.0.0.1:5174");
    expect(normalizeOperatorUrl("https://control-node.example:8443/api//")).toBe("https://control-node.example:8443/api");
    expect(normalizeOperatorUrl("ws://127.0.0.1:5174")).toBeNull();
    expect(normalizeOperatorUrl("127.0.0.1:5174")).toBeNull();
    expect(normalizeOperatorUrl("http://host:5174/?x=1")).toBeNull();
    expect(normalizeOperatorUrl("")).toBeNull();
  });

  it("builds the live channel URL with the matching ws scheme", () => {
    expect(liveChannelUrl("http://127.0.0.1:5174")).toBe("ws://127.0.0.1:5174/cluster/live");
    expect(liveChannelUrl("https://control-node.example/api")).toBe("wss://control-node.example/api/cluster/live");
  });

  it("validates names and URLs", () => {
    const existing = [{ id: "a", name: "Lab", operatorUrl: DEFAULT_OPERATOR_URL }];
    expect(validateClusterInput({ name: " ", operatorUrl: DEFAULT_OPERATOR_URL }, existing).ok).toBe(false);
    expect(validateClusterInput({ name: "lab", operatorUrl: "http://other:5174" }, existing).ok).toBe(false);
    expect(validateClusterInput({ name: "lab", operatorUrl: "http://other:5174" }, existing, "a")).toEqual({
      ok: true,
      value: { name: "lab", operatorUrl: "http://other:5174" },
    });
    expect(validateClusterInput({ name: "Fleet", operatorUrl: "nope" }, existing).ok).toBe(false);
  });
});

describe("cluster list store", () => {
  it("starts with the local control node selected", () => {
    const store = createClusterStore(new MemoryStorage());
    const state = store.getState();
    expect(state.clusters).toHaveLength(1);
    expect(selectSelectedCluster(state)?.operatorUrl).toBe(DEFAULT_OPERATOR_URL);
  });

  it("adds, edits, selects and removes clusters", () => {
    const store = createClusterStore(new MemoryStorage());
    const added = store.getState().addCluster({ name: "Fleet", operatorUrl: "http://127.0.0.1:5175/" });
    expect(added.ok).toBe(true);
    if (!added.ok) return;
    expect(added.cluster.operatorUrl).toBe("http://127.0.0.1:5175");
    expect(store.getState().selectedClusterId).toBe("local");

    expect(store.getState().addCluster({ name: "fleet", operatorUrl: DEFAULT_OPERATOR_URL }).ok).toBe(false);

    store.getState().selectCluster(added.cluster.id);
    expect(selectSelectedCluster(store.getState())?.name).toBe("Fleet");

    expect(store.getState().updateCluster(added.cluster.id, { name: "Fleet 2", operatorUrl: "http://10.0.0.5:5174" })).toEqual({ ok: true });
    expect(selectSelectedCluster(store.getState())).toEqual({ id: added.cluster.id, name: "Fleet 2", operatorUrl: "http://10.0.0.5:5174" });
    expect(store.getState().updateCluster(added.cluster.id, { name: "Local control node", operatorUrl: DEFAULT_OPERATOR_URL }).ok).toBe(false);

    store.getState().removeCluster(added.cluster.id);
    expect(store.getState().selectedClusterId).toBe("local");
    store.getState().removeCluster("local");
    expect(store.getState().clusters).toEqual([]);
    expect(store.getState().selectedClusterId).toBeNull();

    const first = store.getState().addCluster({ name: "Only", operatorUrl: DEFAULT_OPERATOR_URL });
    expect(first.ok && store.getState().selectedClusterId === first.cluster.id).toBe(true);
  });

  it("ignores the selection of an unknown cluster", () => {
    const store = createClusterStore(new MemoryStorage());
    store.getState().selectCluster("missing");
    expect(store.getState().selectedClusterId).toBeNull();
  });

  it("keeps the list per browser", () => {
    const storage = new MemoryStorage();
    const first = createClusterStore(storage);
    const added = first.getState().addCluster({ name: "Fleet", operatorUrl: "http://127.0.0.1:5175" });
    if (!added.ok) throw new Error(added.error);
    first.getState().selectCluster(added.cluster.id);
    expect(JSON.parse(storage.getItem(CLUSTERS_STORAGE_KEY) ?? "{}").version).toBe(1);

    const second = createClusterStore(storage);
    expect(second.getState().clusters.map((cluster) => cluster.name)).toEqual(["Local control node", "Fleet"]);
    expect(second.getState().selectedClusterId).toBe(added.cluster.id);
  });
});
