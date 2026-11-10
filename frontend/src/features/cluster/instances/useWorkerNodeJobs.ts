import { useQuery } from "@tanstack/react-query";
import { fetchWorkerNodeJobs } from "../../../domain/cluster/observableInstances";
import { createOperatorClient, OperatorApiError } from "../../../domain/cluster/operatorApi";
import type { WorkerNodeView } from "../../../domain/cluster/schemas";

export const WORKER_NODE_JOBS_POLL_MS = 5_000;

/**
 * The jobs a worker node holds (leased or running, lease owner the worker node). A worker node view lists only
 * lease ids, so the jobs come from `GET /cluster/jobs`; the query runs again when the worker node's
 * leases change and every few seconds besides.
 */
export function useWorkerNodeJobs(operatorUrl: string | null, workerNode: WorkerNodeView | null) {
  const workerNodeId = workerNode?.worker_node_id ?? null;
  const leaseKey = workerNode ? workerNode.leases.join(",") : "";
  return useQuery({
    queryKey: ["cluster", operatorUrl, workerNodeId, "jobs", leaseKey],
    queryFn: ({ signal }) => fetchWorkerNodeJobs(createOperatorClient(operatorUrl as string), workerNodeId as string, signal),
    enabled: operatorUrl !== null && workerNodeId !== null,
    refetchInterval: WORKER_NODE_JOBS_POLL_MS,
    // A lease change keeps the worker node's jobs shown until the new read answers; another worker node starts empty
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === operatorUrl && previousQuery?.queryKey[2] === workerNodeId ? previous : undefined),
    retry: (failureCount, error) => !(error instanceof OperatorApiError && error.unreachable) && failureCount < 2,
  });
}
