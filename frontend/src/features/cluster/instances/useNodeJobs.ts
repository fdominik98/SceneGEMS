import { useQuery } from "@tanstack/react-query";
import { fetchNodeJobs } from "../../../domain/cluster/observableInstances";
import { createOperatorClient, OperatorApiError } from "../../../domain/cluster/operatorApi";
import type { NodeView } from "../../../domain/cluster/schemas";

export const NODE_JOBS_POLL_MS = 5_000;

/**
 * The jobs a node holds (leased or running, lease owner the node). A node view lists only
 * lease ids, so the jobs come from `GET /cluster/jobs`; the query runs again when the node's
 * leases change and every few seconds besides.
 */
export function useNodeJobs(operatorUrl: string | null, node: NodeView | null) {
  const nodeId = node?.node_id ?? null;
  const leaseKey = node ? node.leases.join(",") : "";
  return useQuery({
    queryKey: ["cluster", operatorUrl, nodeId, "jobs", leaseKey],
    queryFn: ({ signal }) => fetchNodeJobs(createOperatorClient(operatorUrl as string), nodeId as string, signal),
    enabled: operatorUrl !== null && nodeId !== null,
    refetchInterval: NODE_JOBS_POLL_MS,
    // A lease change keeps the node's jobs shown until the new read answers; another node starts empty
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === operatorUrl && previousQuery?.queryKey[2] === nodeId ? previous : undefined),
    retry: (failureCount, error) => !(error instanceof OperatorApiError && error.unreachable) && failureCount < 2,
  });
}
