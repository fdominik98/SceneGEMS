import { describe, expect, it } from "vitest";
import { nodeViewSchema } from "../../domain/cluster/schemas";
import { sampleNode } from "../../test/fixtures/clusterViews";
import { formatAge, formatMegabytes, jobTypeLabel, memoryUseFraction, nodeSlotTotals, shortHash, summarizeNodes } from "./clusterFormat";

describe("cluster formatting", () => {
  it("formats ages coarsely", () => {
    const now = Date.parse("2026-10-26T10:00:00Z");
    expect(formatAge("2026-10-26T09:59:50+00:00", now)).toBe("10 s ago");
    expect(formatAge("2026-10-26T09:55:00Z", now)).toBe("5 min ago");
    expect(formatAge("2026-10-26T07:00:00Z", now)).toBe("3 h ago");
    expect(formatAge("2026-10-22T10:00:00Z", now)).toBe("4 d ago");
    expect(formatAge("2026-10-26T10:00:05Z", now)).toBe("just now");
    expect(formatAge(null, now)).toBe("never");
    expect(formatAge("later", now)).toBe("later");
  });

  it("formats sizes, hashes and job types", () => {
    expect(formatMegabytes(512)).toBe("512 MB");
    expect(formatMegabytes(32000)).toBe("31.3 GB");
    expect(shortHash("sha256:0123456789abcdef")).toBe("0123456789ab");
    expect(shortHash("abc")).toBe("abc");
    expect(shortHash(null)).toBe("none");
    expect(jobTypeLabel("simulation")).toBe("Simulation");
    expect(jobTypeLabel("future.kind")).toBe("future.kind");
    expect(memoryUseFraction(1000, 250)).toBe(0.75);
    expect(memoryUseFraction(0, 0)).toBe(0);
  });

  it("sums slots and summarizes the nodes", () => {
    const a = nodeViewSchema.parse(sampleNode());
    const b = nodeViewSchema.parse(
      sampleNode({ node_id: "b", status: "draining", connected: false, out_of_date: true, leases: [], slots: { trajectory_generation: { slots: 2, slots_in_use: 0 } } })
    );
    expect(nodeSlotTotals(a)).toEqual({ slots: 12, inUse: 9 });
    expect(summarizeNodes([a, b])).toEqual({
      nodes: 2,
      online: 1,
      draining: 1,
      offline: 0,
      connected: 1,
      outOfDate: 1,
      slots: 14,
      slotsInUse: 9,
      leases: 1,
    });
  });
});
