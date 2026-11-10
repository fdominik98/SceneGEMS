import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import { deleteCampaignPreset, listCampaignPresets, saveCampaignPreset, type SavePresetRequest } from "../../../domain/cluster/presetsApi";
import { retryUnlessUnreachable, useOperatorClient } from "../useCampaignData";

/** The campaign presets of the active cluster's control node: the ones its image ships and the ones operators saved on it. */

function presetsKey(baseUrl: string | undefined) {
  return ["cluster-settings", baseUrl, "campaign-presets"] as const;
}

export function useCampaignPresets() {
  const client = useOperatorClient();
  return useQuery({
    queryKey: presetsKey(client?.baseUrl),
    queryFn: ({ signal }) => listCampaignPresets(client as OperatorClient, signal),
    enabled: client !== null,
    staleTime: 60_000,
    retry: retryUnlessUnreachable,
  });
}

function requireClient(client: OperatorClient | null): OperatorClient {
  if (client === null) {
    throw new Error("No cluster is selected.");
  }
  return client;
}

/** Saves a preset; the list is read again afterwards. */
export function useSaveCampaignPreset() {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (preset: SavePresetRequest) => saveCampaignPreset(requireClient(client), preset),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: presetsKey(client?.baseUrl) }),
  });
}

export function useDeleteCampaignPreset() {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (presetId: string) => deleteCampaignPreset(requireClient(client), presetId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: presetsKey(client?.baseUrl) }),
  });
}
