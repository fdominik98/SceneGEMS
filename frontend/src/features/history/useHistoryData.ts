import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { deleteCampaign, listHistory, listOutputs } from "../../domain/cluster/historyApi";
import { CAMPAIGNS_TOPIC } from "../../domain/cluster/liveProtocol";
import { campaignsReducer, type CampaignsUpdate } from "../../domain/cluster/liveTopics";
import type { ListPage, OperatorClient } from "../../domain/cluster/operatorApi";
import type { CampaignRow, CampaignStep } from "../../domain/cluster/schemas";
import { useLiveTopic } from "../../domain/cluster/useLiveTopic";
import { retryUnlessUnreachable, useOperatorClient } from "../campaigns/useCampaignData";
import { listQuery, type ListViewState } from "./campaignModel";
import { liveNeedsRefetch, mergeLiveRows, OUTPUT_PAGE_SIZE } from "./historyModel";

/** Queries of Campaign History: the entry list kept live, the outputs of a step and deleting an entry. */

export const LIST_POLL_MS = 4_000;
export const OUTPUTS_POLL_MS = 4_000;

/**
 * The entries of a list view, newest first. The page comes from the list route; the `campaigns`
 * topic patches its rows as they change and has the page read again when an entry is added,
 * deleted or leaves the filter. While the topic is not live the page is polled.
 */
export function useHistoryList(view: ListViewState) {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  const live = useLiveTopic(CAMPAIGNS_TOPIC, campaignsReducer);
  const isLive = live.status === "live";
  const query = listQuery(view);
  const result = useQuery({
    queryKey: ["history", client?.baseUrl, "list", query],
    queryFn: ({ signal }) => listHistory(client as OperatorClient, query, signal),
    enabled: client !== null,
    refetchInterval: isLive ? false : LIST_POLL_MS,
    placeholderData: keepPreviousData,
    retry: retryUnlessUnreachable,
  });

  const page = result.data?.items;
  const rows = useMemo(() => mergeLiveRows(page ?? [], live.data, view), [page, live.data, view]);

  const pageIds = useMemo(() => (page ?? []).map((row) => row.campaign_id), [page]);
  const last = live.data?.last ?? null;
  const handled = useRef<CampaignsUpdate | null>(null);
  const baseUrl = client?.baseUrl;
  useEffect(() => {
    if (!last || handled.current === last) {
      return;
    }
    handled.current = last;
    if (liveNeedsRefetch(pageIds, view, last)) {
      void queryClient.invalidateQueries({ queryKey: ["history", baseUrl, "list"] });
    }
  }, [last, pageIds, view, queryClient, baseUrl]);

  // A later snapshot (a reconnect, or a resubscribe after a gap in seq) drops the pushed rows: read the page again.
  // The first one is not: the page was read as the section opened.
  const epoch = live.data?.epoch ?? null;
  const seenEpoch = useRef<object | null>(null);
  useEffect(() => {
    if (epoch === null || seenEpoch.current === epoch) {
      return;
    }
    const again = seenEpoch.current !== null;
    seenEpoch.current = epoch;
    if (again) {
      void queryClient.invalidateQueries({ queryKey: ["history", baseUrl, "list"] });
    }
  }, [epoch, queryClient, baseUrl]);

  return { result, rows, total: result.data?.total ?? null, liveStatus: live.status };
}

/** The names of the entries the list pages read so far, by id, for made-from links outside the list. */
export function useKnownEntryNames(): ReadonlyMap<string, string> {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const [, page] of queryClient.getQueriesData<ListPage<CampaignRow>>({ queryKey: ["history", client?.baseUrl, "list"] })) {
      for (const row of page?.items ?? []) {
        names.set(row.campaign_id, row.name);
      }
    }
    return names;
  }, [queryClient, client]);
}

/** One page of a step's outputs, polled while the entry is not final. */
export function useStepOutputs(campaignId: string, step: CampaignStep, page: number, running: boolean) {
  const client = useOperatorClient();
  const filters = { step, limit: OUTPUT_PAGE_SIZE, offset: page * OUTPUT_PAGE_SIZE };
  return useQuery({
    queryKey: ["history", client?.baseUrl, "outputs", campaignId, filters],
    queryFn: ({ signal }) => listOutputs(client as OperatorClient, campaignId, filters, signal),
    enabled: client !== null,
    refetchInterval: running ? OUTPUTS_POLL_MS : false,
    placeholderData: keepPreviousData,
    retry: retryUnlessUnreachable,
  });
}

/** Deletes a final entry; the list is read again and the entry's cached queries are dropped. */
export function useDeleteEntry(campaignId: string, onDeleted: () => void) {
  const client = useOperatorClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => deleteCampaign(client as OperatorClient, campaignId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["history", client?.baseUrl, "list"] });
      // The Results section's entry picker lists the entries too (`features/results/useResultsData.ts`)
      void queryClient.invalidateQueries({ queryKey: ["results", client?.baseUrl, "history"] });
      queryClient.removeQueries({ queryKey: ["history", client?.baseUrl, "outputs", campaignId] });
      queryClient.removeQueries({ queryKey: ["campaigns", client?.baseUrl, "detail", campaignId] });
      onDeleted();
    },
  });
}
