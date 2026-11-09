import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { jobViewSchema, nodeViewSchema, type JobView, type NodeView } from "../../../domain/cluster/schemas";
import { sampleJob, sampleNode } from "../../../test/fixtures/clusterViews";
import { useNodeJobs } from "./useNodeJobs";

const { fetchNodeJobs } = vi.hoisted(() => ({ fetchNodeJobs: vi.fn() }));
vi.mock("../../../domain/cluster/observableInstances", () => ({ fetchNodeJobs }));

const URL_A = "http://127.0.0.1:5174";

function node(id: string, leases: string[]): NodeView {
  return nodeViewSchema.parse(sampleNode({ node_id: id, name: id, leases }));
}

function job(id: string): JobView {
  return jobViewSchema.parse(sampleJob({ job_id: id }));
}

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchNodeJobs.mockReset();
});

describe("useNodeJobs", () => {
  it("keeps the node's jobs shown while a lease change is read again, but not another node's", async () => {
    fetchNodeJobs.mockResolvedValueOnce([job("j1")]);
    const { result, rerender } = renderHook(({ shown }: { shown: NodeView }) => useNodeJobs(URL_A, shown), { wrapper, initialProps: { shown: node("a", ["j1"]) } });
    await waitFor(() => expect(result.current.data?.map((entry) => entry.job_id)).toEqual(["j1"]));

    fetchNodeJobs.mockReturnValue(new Promise(() => undefined)); // the next reads do not answer
    rerender({ shown: node("a", ["j1", "j2"]) });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.map((entry) => entry.job_id)).toEqual(["j1"]);

    rerender({ shown: node("b", ["j9"]) });
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPending).toBe(true);
  });
});
