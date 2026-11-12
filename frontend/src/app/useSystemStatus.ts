import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { useShallow } from "zustand/react/shallow";
import { useSelectedCluster } from "../domain/cluster/clusterStore";
import { listHistory } from "../domain/cluster/historyApi";
import { CAMPAIGNS_TOPIC } from "../domain/cluster/liveProtocol";
import { campaignsReducer } from "../domain/cluster/liveTopics";
import { createOperatorClient, OperatorApiError } from "../domain/cluster/operatorApi";
import type { CampaignActualState } from "../domain/cluster/schemas";
import { useLiveTopic } from "../domain/cluster/useLiveTopic";
import { useWorkerNodesFeed, useWorkerNodesStore } from "../domain/cluster/workerNodesStore";
import { summarizeWorkerNodes } from "../features/cluster/clusterFormat";
import { PAGE_STORES, type PageState } from "../features/workbench/pages/pageStore";
import { describeClusterStatus, describeStep, type StepIndicator, type SystemStatus } from "./systemStatus";

/** The states of an entry that still has work on the cluster. */
export const RUNNING_ENTRY_STATES: CampaignActualState[] = ["running", "draining"];
export const RUNNING_ENTRIES_POLL_MS = 10_000;

const stepInput = (state: PageState) => ({ status: state.status, hasOutput: state.output !== null || state.loaded !== null });

function useStep(page: keyof typeof PAGE_STORES): StepIndicator | null {
  const input = PAGE_STORES[page](useShallow(stepInput));
  return useMemo(() => describeStep(input), [input]);
}

/**
 * How many entries of the selected cluster run now. The count is the total of a one-row read of
 * the history; the `campaigns` topic says when an entry appeared, went or changed its state, and
 * only then is it read again. While the topic is not live it is polled.
 */
function useRunningEntries(operatorUrl: string | null): number | null {
  const client = useMemo(() => (operatorUrl ? createOperatorClient(operatorUrl) : null), [operatorUrl]);
  const live = useLiveTopic(CAMPAIGNS_TOPIC, campaignsReducer);
  const query = useQuery({
    queryKey: ["system-status", operatorUrl, "running-entries"],
    queryFn: async ({ signal }) => (await listHistory(client!, { state: RUNNING_ENTRY_STATES, limit: 1 }, signal)).total,
    enabled: client !== null,
    refetchInterval: live.status === "live" ? false : RUNNING_ENTRIES_POLL_MS,
    retry: (failureCount, error) => !(error instanceof OperatorApiError && error.unreachable) && failureCount < 2,
  });

  const { refetch } = query;
  const last = live.data?.last ?? null;
  const epoch = live.data?.epoch ?? null;
  const known = useRef<{ epoch: object | null; states: Map<string, string> }>({ epoch: null, states: new Map() });
  useEffect(() => {
    if (epoch !== known.current.epoch) {
      // A new snapshot: what changed meanwhile is only in a fresh read.
      const again = known.current.epoch !== null;
      known.current = { epoch, states: new Map() };
      if (again) {
        void refetch();
      }
    }
    if (!last) {
      return;
    }
    const states = known.current.states;
    if ("deleted" in last) {
      states.delete(last.deleted);
      void refetch();
      return;
    }
    const { campaign_id: id, actual_state: state } = last.campaign;
    if (states.get(id) !== state) {
      states.set(id, state);
      void refetch();
    }
  }, [last, epoch, refetch]);

  return query.data ?? null;
}

/** What the left pane shows of the system on every page. Keeps the selected cluster's worker nodes feed running. */
export function useSystemStatus(): SystemStatus {
  const selectedCluster = useSelectedCluster();
  const operatorUrl = selectedCluster?.operatorUrl ?? null;
  useWorkerNodesFeed(operatorUrl);
  const nodes = useWorkerNodesStore(
    useShallow((state) => ({ operatorUrl: state.operatorUrl, workerNodes: state.workerNodes, loaded: state.loaded, unreachable: state.unreachable, error: state.error }))
  );
  const ofCluster = nodes.operatorUrl === operatorUrl;
  const cluster = useMemo(
    () =>
      describeClusterStatus({
        selected: operatorUrl !== null,
        loaded: ofCluster && nodes.loaded,
        unreachable: ofCluster && nodes.unreachable,
        error: ofCluster ? nodes.error : null,
        summary: summarizeWorkerNodes(ofCluster ? nodes.workerNodes : []),
      }),
    [operatorUrl, ofCluster, nodes.loaded, nodes.unreachable, nodes.error, nodes.workerNodes]
  );

  const designSpaceExploration = useStep("designSpaceExploration");
  const sceneGeneration = useStep("sceneGeneration");
  const trajectoryGeneration = useStep("trajectoryGeneration");
  const simulation = useStep("simulation");
  const steps = useMemo(() => {
    const marks: SystemStatus["steps"] = {};
    if (designSpaceExploration) marks.designSpaceExploration = designSpaceExploration;
    if (sceneGeneration) marks.sceneGeneration = sceneGeneration;
    if (trajectoryGeneration) marks.trajectoryGeneration = trajectoryGeneration;
    if (simulation) marks.simulation = simulation;
    return marks;
  }, [designSpaceExploration, sceneGeneration, trajectoryGeneration, simulation]);

  const runningEntries = useRunningEntries(operatorUrl);
  return useMemo(() => ({ cluster, steps, runningEntries }), [cluster, steps, runningEntries]);
}
