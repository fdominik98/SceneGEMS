import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getArchitecture } from "../../domain/cluster/architectureApi";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { createOperatorClient, OperatorApiError } from "../../domain/cluster/operatorApi";

/** Retry only what can recover: not an unreachable control node, not an answer the control node gave. */
const retryUnlessUnreachable = (failureCount: number, error: unknown) =>
  !(error instanceof OperatorApiError && (error.unreachable || (error.status !== null && error.status < 500))) && failureCount < 2;

/** The architecture documents of the selected cluster's control node. They change only when the control node restarts on new code. */
export function useArchitecture() {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  const client = useMemo(() => (operatorUrl ? createOperatorClient(operatorUrl) : null), [operatorUrl]);
  return useQuery({
    queryKey: ["architecture", operatorUrl],
    queryFn: ({ signal }) => getArchitecture(client as NonNullable<typeof client>, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}
