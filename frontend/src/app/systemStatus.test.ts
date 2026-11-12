import { describe, expect, it } from "vitest";
import type { ClusterSummary } from "../features/cluster/clusterFormat";
import { describeClusterStatus, describeRunningEntries, describeStep, NO_SYSTEM_STATUS, type ClusterStatusInput } from "./systemStatus";

const HEALTHY: ClusterSummary = { workerNodes: 2, online: 2, draining: 0, offline: 0, connected: 2, outOfDate: 0, slots: 10, slotsInUse: 3, leases: 3 };

function cluster(overrides: Partial<ClusterStatusInput> = {}): ClusterStatusInput {
  return { selected: true, loaded: true, unreachable: false, error: null, summary: HEALTHY, ...overrides };
}

describe("describeClusterStatus", () => {
  it("says that no cluster is selected", () => {
    expect(describeClusterStatus(cluster({ selected: false }))).toEqual(NO_SYSTEM_STATUS.cluster);
    expect(NO_SYSTEM_STATUS.cluster).toEqual({ tone: "idle", label: "No cluster selected", detail: null });
  });

  it("is connecting until the control node answered", () => {
    expect(describeClusterStatus(cluster({ loaded: false }))).toEqual({ tone: "busy", label: "Connecting", detail: null });
  });

  it("names a control node that cannot be reached, and that the numbers are old when it has some", () => {
    expect(describeClusterStatus(cluster({ loaded: false, unreachable: true, error: "no answer" }))).toEqual({
      tone: "bad",
      label: "Cannot reach the control node",
      detail: null,
    });
    expect(describeClusterStatus(cluster({ unreachable: true, error: "no answer" })).detail).toBe("showing what it last reported");
  });

  it("gives a control node's own error before it answered", () => {
    expect(describeClusterStatus(cluster({ loaded: false, error: "500: broken" }))).toEqual({ tone: "bad", label: "Control node error", detail: "500: broken" });
  });

  it("is connected with the worker nodes online and the slots in use", () => {
    expect(describeClusterStatus(cluster())).toEqual({ tone: "ok", label: "Connected", detail: "2 of 2 worker nodes online, 3 of 10 slots in use" });
  });

  it("writes one worker node and one slot in the singular", () => {
    const summary = { ...HEALTHY, workerNodes: 1, online: 1, slots: 1, slotsInUse: 0 };
    expect(describeClusterStatus(cluster({ summary })).detail).toBe("1 of 1 worker node online, 0 of 1 slot in use");
  });

  it("warns about worker nodes that are offline or out of date", () => {
    const summary = { ...HEALTHY, online: 1, offline: 1, outOfDate: 1 };
    expect(describeClusterStatus(cluster({ summary }))).toEqual({
      tone: "warn",
      label: "Connected, 1 offline, 1 out of date",
      detail: "1 of 2 worker nodes online, 3 of 10 slots in use",
    });
  });

  it("says when nothing can run", () => {
    const none = { ...HEALTHY, workerNodes: 0, online: 0, slots: 0, slotsInUse: 0 };
    expect(describeClusterStatus(cluster({ summary: none }))).toMatchObject({ tone: "warn", label: "No worker nodes" });
    const allOffline = { ...HEALTHY, online: 0, offline: 2 };
    expect(describeClusterStatus(cluster({ summary: allOffline }))).toMatchObject({ tone: "bad", label: "No worker node online" });
  });

  it("warns that the worker nodes may be stale when reading them failed after an answer", () => {
    expect(describeClusterStatus(cluster({ error: "timeout" }))).toMatchObject({ tone: "warn", label: "Worker nodes may be stale" });
  });
});

describe("describeStep", () => {
  it("marks a page that runs, follows or loads as busy", () => {
    expect(describeStep({ status: "running", hasOutput: false })).toEqual({ tone: "busy", label: "Running" });
    expect(describeStep({ status: "following", hasOutput: true })).toEqual({ tone: "busy", label: "Following a run" });
    expect(describeStep({ status: "loading", hasOutput: false })).toEqual({ tone: "busy", label: "Loading" });
  });

  it("marks a failure before a result that is still shown", () => {
    expect(describeStep({ status: "failed", hasOutput: true })).toEqual({ tone: "bad", label: "Failed" });
  });

  it("marks a page that shows a result, and leaves an empty idle page unmarked", () => {
    expect(describeStep({ status: "shown", hasOutput: true })).toEqual({ tone: "info", label: "Shows a result" });
    expect(describeStep({ status: "idle", hasOutput: true })).toEqual({ tone: "info", label: "Shows a result" });
    expect(describeStep({ status: "idle", hasOutput: false })).toBeNull();
  });
});

describe("describeRunningEntries", () => {
  it("counts entries in the singular and the plural", () => {
    expect(describeRunningEntries(1)).toBe("1 entry running");
    expect(describeRunningEntries(3)).toBe("3 entries running");
  });
});
