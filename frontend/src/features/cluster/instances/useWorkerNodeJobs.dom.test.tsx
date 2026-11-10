import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { jobViewSchema, workerNodeViewSchema, type JobView, type WorkerNodeView } from "../../../domain/cluster/schemas";
import { sampleJob, sampleWorkerNode } from "../../../test/fixtures/clusterViews";
import { useWorkerNodeJobs } from "./useWorkerNodeJobs";

const { fetchWorkerNodeJobs } = vi.hoisted(() => ({ fetchWorkerNodeJobs: vi.fn() }));
vi.mock("../../../domain/cluster/observableInstances", () => ({ fetchWorkerNodeJobs }));

const URL_A = "http://127.0.0.1:5174";

function workerNode(id: string, leases: string[]): WorkerNodeView {
  return workerNodeViewSchema.parse(sampleWorkerNode({ worker_node_id: id, name: id, leases }));
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
  fetchWorkerNodeJobs.mockReset();
});

describe("useWorkerNodeJobs", () => {
  it("keeps the worker node's jobs shown while a lease change is read again, but not another worker node's", async () => {
    fetchWorkerNodeJobs.mockResolvedValueOnce([job("j1")]);
    const { result, rerender } = renderHook(({ shown }: { shown: WorkerNodeView }) => useWorkerNodeJobs(URL_A, shown), { wrapper, initialProps: { shown: workerNode("a", ["j1"]) } });
    await waitFor(() => expect(result.current.data?.map((entry) => entry.job_id)).toEqual(["j1"]));

    fetchWorkerNodeJobs.mockReturnValue(new Promise(() => undefined)); // the next reads do not answer
    rerender({ shown: workerNode("a", ["j1", "j2"]) });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.map((entry) => entry.job_id)).toEqual(["j1"]);

    rerender({ shown: workerNode("b", ["j9"]) });
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPending).toBe(true);
  });
});
