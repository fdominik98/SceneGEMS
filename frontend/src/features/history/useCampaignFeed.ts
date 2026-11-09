import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { campaignTopic } from "../../domain/cluster/liveProtocol";
import { campaignReducer, type CampaignTopicState } from "../../domain/cluster/liveTopics";
import { useNodesFeed, useNodesStore } from "../../domain/cluster/nodesStore";
import { OperatorApiError, type CampaignControl, type OperatorClient } from "../../domain/cluster/operatorApi";
import type { CampaignConfig, CampaignDetail, CampaignSummary } from "../../domain/cluster/schemas";
import { useLiveTopic } from "../../domain/cluster/useLiveTopic";
import { planOfConfig, startBlocker } from "../campaigns/resourcePlan";
import { retryUnlessUnreachable, useOperatorClient } from "../campaigns/useCampaignData";
import { EMPTY_EVENT_FEED, EVENTS_KEPT, eventFeedReducer, mergeEvents, newerSummary } from "./campaignModel";

/** The live feed, events, config and controls of one entry of Campaign History. */

export const DETAIL_POLL_MS = 4_000;
const EVENTS_PAGE = 200;
const EVENTS_PAGES_MAX = 50;

// Detail

export interface CampaignFeed {
  detail: CampaignDetail | null;
  /** Where the numbers come from: the live channel, or polling while the channel is down. */
  source: "live" | "poll";
  liveStatus: ReturnType<typeof useLiveTopic>["status"];
  error: OperatorApiError | Error | null;
  loading: boolean;
  lastEventId: number | null;
  pushedEvents: CampaignTopicState["events"];
  /** Applies the answer of a control right away (the live update follows with the engine's next transaction). */
  applySummary: (summary: CampaignSummary) => void;
  refetch: () => void;
}

export function useCampaignFeed(campaignId: string): CampaignFeed {
  const client = useOperatorClient();
  const live = useLiveTopic(campaignTopic(campaignId), campaignReducer);
  const isLive = live.status === "live";
  const queryClient = useQueryClient();
  const queryKey = useMemo(() => ["campaigns", client?.baseUrl, "detail", campaignId], [client, campaignId]);
  const rest = useQuery({
    queryKey,
    queryFn: ({ signal }) => (client as OperatorClient).getCampaign(campaignId, signal),
    enabled: client !== null,
    refetchInterval: isLive ? false : DETAIL_POLL_MS,
    retry: retryUnlessUnreachable,
  });
  const [override, setOverride] = useState<CampaignSummary | null>(null);
  const applySummary = useCallback(
    (summary: CampaignSummary) => {
      setOverride(summary);
      queryClient.setQueryData<CampaignDetail>(queryKey, (current) => (current ? { ...current, ...summary } : current));
      void queryClient.invalidateQueries({ queryKey: ["history", client?.baseUrl, "list"] });
    },
    [queryClient, queryKey, client]
  );
  const liveDetail = live.data?.detail ?? null;
  const base = isLive && liveDetail ? liveDetail : (rest.data ?? liveDetail);
  const detail = useMemo(() => {
    if (!base) {
      return null;
    }
    if (!override || override.campaign_id !== base.campaign_id) {
      return base;
    }
    const newer = newerSummary(base, override);
    return newer === base ? base : { ...base, ...override };
  }, [base, override]);
  const error = !detail && rest.error ? (rest.error as Error) : live.status === "error" && !detail ? new Error(live.error ?? "the live channel refused the campaign") : null;
  return {
    detail,
    source: isLive ? "live" : "poll",
    liveStatus: live.status,
    error,
    loading: !detail && !error,
    lastEventId: live.data?.lastEventId ?? null,
    pushedEvents: live.data?.events ?? [],
    applySummary,
    refetch: () => void rest.refetch(),
  };
}

/** The campaign's events, oldest first: the history from the events route, then the ones the live channel pushes (or polling). */
export function useCampaignEvents(campaignId: string, lastEventId: number | null, pushed: CampaignTopicState["events"], polling: boolean) {
  const client = useOperatorClient();
  const [feed, dispatch] = useReducer(eventFeedReducer, EMPTY_EVENT_FEED);
  const lastIdRef = useRef(0);
  // The signal of the read in flight: a new trigger waits for it unless it was aborted (an effect's cleanup), then it reads anew
  const inFlight = useRef<AbortSignal | null>(null);

  useEffect(() => {
    lastIdRef.current = feed.lastId;
  }, [feed.lastId]);

  useEffect(() => {
    dispatch({ type: "reset" });
    lastIdRef.current = 0;
  }, [campaignId, client]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!client || signal.aborted || (inFlight.current !== null && !inFlight.current.aborted)) {
        return;
      }
      inFlight.current = signal;
      try {
        let after = lastIdRef.current;
        for (let page = 0; page < EVENTS_PAGES_MAX; page += 1) {
          // The first read takes the newest page (what the feed keeps); a master without `newest` ignores it and pages from event 0 as before.
          const first = after === 0 && page === 0;
          const { items } = await client.listEvents(campaignId, first ? { newest: EVENTS_KEPT, limit: EVENTS_PAGE } : { after, limit: EVENTS_PAGE }, signal);
          if (signal.aborted || items.length === 0) {
            break;
          }
          dispatch({ type: "merge", events: items });
          after = items[items.length - 1].event_id;
          lastIdRef.current = after;
          if (items.length < EVENTS_PAGE) {
            break;
          }
        }
      } catch {
        // The next trigger tries again; the feed keeps what it has
      } finally {
        if (inFlight.current === signal) {
          inFlight.current = null;
        }
      }
    },
    [client, campaignId]
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, lastEventId]);

  useEffect(() => {
    if (!polling) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = setInterval(() => void load(controller.signal), DETAIL_POLL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [polling, load]);

  return useMemo(() => mergeEvents(feed.events, pushed), [feed.events, pushed]);
}

export function useCampaignConfig(campaignId: string) {
  const client = useOperatorClient();
  return useQuery({
    queryKey: ["campaigns", client?.baseUrl, "config", campaignId],
    queryFn: ({ signal }) => (client as OperatorClient).getCampaignConfig(campaignId, signal),
    enabled: client !== null,
    staleTime: 30_000,
    retry: retryUnlessUnreachable,
  });
}

/** Why the campaign of a stored config cannot start on the selected cluster's machines, or null; follows the nodes while mounted. */
export function useStartBlocker(config: CampaignConfig | undefined): string | null {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const current = config?.versions.find((version) => version.version === config.current_version)?.config;
  // Only the answer is selected: a heartbeat that leaves it as it was does not render the entry page again
  return useNodesStore((state) => startBlocker(operatorUrl !== null && state.operatorUrl === operatorUrl && state.loaded && current ? planOfConfig(current, state.nodes) : null));
}

export function useCampaignControl(campaignId: string, onDone: (summary: CampaignSummary) => void) {
  const client = useOperatorClient();
  return useMutation({
    mutationFn: (control: CampaignControl) => (client as OperatorClient).controlCampaign(campaignId, control),
    onSuccess: onDone,
  });
}
