import { useCallback, useMemo } from "react";
import { useSelectedCluster } from "../../../domain/cluster/clusterStore";
import { getLiveChannel } from "../../../domain/cluster/liveChannels";
import { useWorkerNodesFeed, useWorkerNodesStore } from "../../../domain/cluster/workerNodesStore";
import { createOperatorClient } from "../../../domain/cluster/operatorApi";
import { jobTypeResources, type JobTypeResources } from "./workbenchResources";
import type { WorkbenchCluster } from "./workbenchJobs";

export interface WorkbenchClusterView {
  /** The active cluster's operator URL, null when none is selected. */
  operatorUrl: string | null;
  /** Client and live channel of the active cluster, null when none is selected. */
  cluster: WorkbenchCluster | null;
  /** What the active cluster offers for a job type with these components (its subsystem's when left out), and why the workbench cannot run it when it cannot. */
  resources: (jobType: string, components?: readonly string[]) => JobTypeResources;
}

/** The active cluster the workbench runs its jobs on, with its worker nodes followed while mounted. */
export function useWorkbenchCluster(): WorkbenchClusterView {
  const selected = useSelectedCluster();
  const operatorUrl = selected?.operatorUrl ?? null;
  useWorkerNodesFeed(operatorUrl);
  const feedUrl = useWorkerNodesStore((s) => s.operatorUrl);
  const workerNodes = useWorkerNodesStore((s) => s.workerNodes);
  const loaded = useWorkerNodesStore((s) => s.loaded);
  const unreachable = useWorkerNodesStore((s) => s.unreachable);

  const cluster = useMemo<WorkbenchCluster | null>(
    () => (operatorUrl ? { client: createOperatorClient(operatorUrl), channel: getLiveChannel(operatorUrl) } : null),
    [operatorUrl]
  );
  const resources = useCallback(
    (jobType: string, components?: readonly string[]) => {
      // Worker nodes of another cluster, from a feed that has not switched yet, count as unknown.
      const current = feedUrl === operatorUrl;
      return jobTypeResources(
        { operatorUrl, workerNodes: current ? workerNodes : [], loaded: current && loaded, unreachable: current && unreachable },
        jobType,
        components
      );
    },
    [feedUrl, loaded, workerNodes, operatorUrl, unreachable]
  );
  return { operatorUrl, cluster, resources };
}
