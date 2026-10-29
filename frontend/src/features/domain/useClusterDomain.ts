import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getClusterDomain, getDomainPresets, saveClusterDomain, type ClusterDomain, type DomainTexts } from "../../domain/cluster/presetsApi";
import type { OperatorClient } from "../../domain/cluster/operatorApi";
import { retryUnlessUnreachable, useOperatorClient } from "../campaigns/useCampaignData";

/**
 * The active cluster's domain configuration and the master's domain presets. The configuration is
 * global for the cluster: the Domain Configuration section edits it, and the workbench and the
 * campaign wizard read it from here, so every page uses the texts the master holds.
 */

export function domainQueryKey(baseUrl: string | undefined) {
  return ["cluster-settings", baseUrl, "domain"] as const;
}

export function useClusterDomain() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: domainQueryKey(client?.baseUrl),
    queryFn: ({ signal }) => getClusterDomain(client as OperatorClient, signal),
    enabled: client !== null,
    // Another operator may change it: read it again when the page is shown again or after half a minute.
    staleTime: 30_000,
    retry: retryUnlessUnreachable,
  });
}

export function useDomainPresets() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["catalog", client?.baseUrl, "domain-presets"],
    queryFn: ({ signal }) => getDomainPresets(client as OperatorClient, signal),
    enabled: client !== null,
    staleTime: 5 * 60_000,
    retry: retryUnlessUnreachable,
  });
}

/** Saves the texts as the cluster's domain configuration; the saved answer replaces the cached one. */
export function useSaveClusterDomain() {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (texts: DomainTexts) => {
      if (client === null) {
        throw new Error("No cluster is selected.");
      }
      return saveClusterDomain(client, texts);
    },
    onSuccess: (saved: ClusterDomain) => queryClient.setQueryData(domainQueryKey(client?.baseUrl), saved),
  });
}

/** The three texts of a domain configuration, without its status fields. */
export function textsOf(domain: ClusterDomain): DomainTexts {
  return { colregs_constants: domain.colregs_constants, vessel_types: domain.vessel_types, obstacle_types: domain.obstacle_types };
}
