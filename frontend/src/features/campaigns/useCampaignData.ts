import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getCatalogStacks, listCatalogClasses } from "../../domain/cluster/campaignApi";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { getDesignSpaceDefault } from "../../domain/cluster/presetsApi";
import { createOperatorClient, OperatorApiError, type OperatorClient } from "../../domain/cluster/operatorApi";

/** The operator client and catalog queries of the Campaigns section (the wizard); entries are followed in Campaign History. */

/** Retries a failed query unless the control node is unreachable or refused it (a 4xx). */
export const retryUnlessUnreachable = (failureCount: number, error: unknown) => !(error instanceof OperatorApiError && (error.unreachable || (error.status !== null && error.status < 500))) && failureCount < 2;

/** The operator client of the selected cluster, or null without one. */
export function useOperatorClient(): OperatorClient | null {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  return useMemo(() => (operatorUrl ? createOperatorClient(operatorUrl) : null), [operatorUrl]);
}

// Catalog

export function useCatalogClasses() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "classes"],
    queryFn: ({ signal }) => listCatalogClasses(client as OperatorClient, {}, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}

export function useCatalogStacks() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "stacks"],
    queryFn: ({ signal }) => getCatalogStacks(client as OperatorClient, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}

/** The control node's default design space (specification and scope); null from a control node that has none (404). */
export function useDesignSpaceDefault() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "design-space"],
    queryFn: ({ signal }) => getDesignSpaceDefault(client as OperatorClient, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}
