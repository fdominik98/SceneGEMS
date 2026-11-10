import { useEffect, useState, type ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import "./cluster.css";
import { Disclosure } from "../../components/Disclosure";
import { EmptyState } from "../../components/EmptyState";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useWorkerNodesFeed, useWorkerNodesStore } from "../../domain/cluster/workerNodesStore";
import { createOperatorClient, describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { ControlNodeStatus, WorkerNodeView } from "../../domain/cluster/schemas";
import { useLiveChannelStatus } from "../../domain/cluster/useLiveTopic";
import { ClusterListPanel, SSH_TUNNEL_COMMAND } from "./ClusterListPanel";
import { shortHash, summarizeWorkerNodes } from "./clusterFormat";
import { WorkerNodeInstances } from "./instances/WorkerNodeInstances";
import { WorkerNodeCard } from "./WorkerNodeCard";
import { useControlNodeStatus } from "./useControlNodeStatus";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

const LIVE_LABELS = {
  idle: "idle",
  connecting: "connecting",
  open: "open",
  reconnecting: "reconnecting",
  closed: "closed",
} as const;

function StatTile({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className={`stat-tile${tone ? ` stat-tile--${tone}` : ""}`}>
      <span className="stat-tile-label">{label}</span>
      <span className="stat-tile-value">{value}</span>
      {detail && <span className="stat-tile-detail">{detail}</span>}
    </div>
  );
}

interface ControlNodeDetailsProps {
  status: ControlNodeStatus;
  liveStatus: keyof typeof LIVE_LABELS;
  workerNodesSource: string | null;
  connected: number;
  total: number;
}

/** The technical side of the control node: its id, the live channel, how worker nodes update, and the release fingerprints. */
function ControlNodeDetails({ status, liveStatus, workerNodesSource, connected, total }: ControlNodeDetailsProps) {
  const images = Object.entries(status.expected_fingerprints.images).sort(([a], [b]) => a.localeCompare(b));
  const fingerprints = status.expected_fingerprints;
  return (
    <div className="control-node-status-panel">
      <dl className="control-node-facts">
        <div>
          <dt>Control node</dt>
          <dd>{status.control_node_id}</dd>
        </div>
        <div>
          <dt>Worker nodes with a control link</dt>
          <dd>
            {connected} / {total}
          </dd>
        </div>
        <div>
          <dt>Live channel</dt>
          <dd>{LIVE_LABELS[liveStatus]}</dd>
        </div>
        <div>
          <dt>Worker node updates</dt>
          <dd>{workerNodesSource === "live" && liveStatus === "open" ? "pushed live" : "polled every 5 s"}</dd>
        </div>
        <div>
          <dt>Release fingerprints</dt>
          <dd>
            {fingerprints.state}
            {images.length > 0 ? ` (${images.length} images)` : ""}
          </dd>
        </div>
      </dl>
      {fingerprints.error && <p className="meta warning">{fingerprints.error}</p>}
      {images.length > 0 ? (
        <table className="control-node-images">
          <thead>
            <tr>
              <th>Image</th>
              <th>Expected fingerprint</th>
            </tr>
          </thead>
          <tbody>
            {images.map(([image, fingerprint]) => (
              <tr key={image}>
                <td>
                  <code>{image}</code>
                </td>
                <td>
                  <code title={fingerprint}>{shortHash(fingerprint, 16)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="meta">The control node lists no expected images yet.</p>
      )}
    </div>
  );
}

/** Removes every offline worker node of the cluster, e.g. the old versions of worker nodes that came back under a new id. */
function ClearOfflineBar({ operatorUrl, offline }: { operatorUrl: string; offline: WorkerNodeView[] }) {
  const removeWorkerNode = useWorkerNodesStore((s) => s.removeWorkerNode);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clear = async () => {
    setPending(true);
    setError(null);
    const client = createOperatorClient(operatorUrl);
    const failures: string[] = [];
    for (const workerNode of offline) {
      try {
        removeWorkerNode(await client.removeWorkerNode(workerNode.worker_node_id));
      } catch (failure) {
        failures.push(`${workerNode.name}: ${describeOperatorError(failure)}`);
      }
    }
    setError(failures.length > 0 ? failures.join("; ") : null);
    setConfirming(false);
    setPending(false);
  };

  return (
    <div className="cluster-clear-offline">
      <button
        type="button"
        className={`worker-node-card-action${confirming ? " worker-node-card-action--danger" : ""}`}
        disabled={pending}
        onClick={() => (confirming ? void clear() : setConfirming(true))}
        onBlur={() => setConfirming(false)}
        title="Forget every offline worker node. One that connects again reappears."
      >
        {pending ? "Clearing..." : confirming ? `Confirm: remove ${offline.length}` : `Clear ${offline.length} offline`}
      </button>
      {error && <p className="meta warning">{error}</p>}
    </div>
  );
}

/** The Cluster section: the selected cluster's control node and its worker nodes as machine resources. */
export function ClusterSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  useWorkerNodesFeed(operatorUrl);
  // What the page shows of the store, not its actions
  const workerNodesState = useWorkerNodesStore(
    useShallow((state) => ({ operatorUrl: state.operatorUrl, workerNodes: state.workerNodes, loaded: state.loaded, error: state.error, unreachable: state.unreachable, source: state.source }))
  );
  const liveStatus = useLiveChannelStatus(operatorUrl);
  const statusQuery = useControlNodeStatus(operatorUrl);
  const now = useNow(5_000);
  const [instancesWorkerNodeId, setInstancesWorkerNodeId] = useState<string | null>(null);

  const workerNodesOfCluster = workerNodesState.operatorUrl === operatorUrl;
  const workerNodes = workerNodesOfCluster ? workerNodesState.workerNodes : [];
  const loaded = workerNodesOfCluster && workerNodesState.loaded;
  const statusError = statusQuery.error;
  const unreachable =
    !loaded &&
    ((statusError instanceof OperatorApiError && statusError.unreachable) || (workerNodesOfCluster && workerNodesState.unreachable));
  const summary = summarizeWorkerNodes(workerNodes);
  const offlineWorkerNodes = workerNodes.filter((workerNode) => workerNode.status === "offline");
  const instancesWorkerNode = workerNodes.find((workerNode) => workerNode.worker_node_id === instancesWorkerNodeId) ?? null;

  const apiBadge = cluster && (
    <div className="section-badges">
      <span className={`section-badge${statusQuery.isSuccess ? " section-badge--ok" : statusError ? " section-badge--bad" : ""}`}>
        {statusQuery.isSuccess ? "Connected to the control node" : statusError ? "Cannot reach the control node" : "Checking the control node"}
      </span>
    </div>
  );

  const manage = (
    <Disclosure
      id="cluster:manage"
      title="Manage clusters"
      hint={cluster ? cluster.name : "none selected"}
      headingLevel={3}
    >
      <ClusterListPanel />
    </Disclosure>
  );

  let content: ReactNode;
  if (!cluster) {
    content = (
      <>
        <EmptyState title="No cluster selected">
          <p>Add a cluster, or select one in the list below, to see its machines.</p>
        </EmptyState>
        <ClusterListPanel />
      </>
    );
  } else if (unreachable) {
    const error = statusError ?? workerNodesState.error;
    content = (
      <>
        <EmptyState
          title={`Cannot reach ${cluster.name}`}
          tone="error"
          action={
            <button type="button" className="primary-btn accent" onClick={() => void statusQuery.refetch()} disabled={statusQuery.isFetching}>
              {statusQuery.isFetching ? "Trying..." : "Try again"}
            </button>
          }
        >
          <p>{error ? describeOperatorError(error) : `No answer from ${cluster.operatorUrl}.`}</p>
          <p>
            Check that the control node runs and that its operator API is reachable at <code>{cluster.operatorUrl}</code>.
          </p>
          <Disclosure
            id="cluster:unreachable-tunnel"
            variant="link"
            headingLevel={null}
            title="It is a remote control node"
            openTitle="Hide the tunnel command"
          >
            <p>Open the tunnel first:</p>
            <code className="cluster-hint-command">{SSH_TUNNEL_COMMAND}</code>
          </Disclosure>
        </EmptyState>
        {manage}
      </>
    );
  } else {
    content = (
      <>
        {manage}
        <div className="stat-tiles">
          <StatTile
            label="Worker nodes online"
            value={loaded ? `${summary.online} / ${summary.workerNodes}` : "..."}
            detail={loaded ? `${summary.draining} draining, ${summary.offline} offline` : "loading"}
            tone={loaded && summary.offline > 0 ? "warn" : undefined}
          />
          <StatTile
            label="Slots in use"
            value={loaded ? `${summary.slotsInUse} / ${summary.slots}` : "..."}
            detail={loaded ? `${summary.leases} leases` : undefined}
          />
          <StatTile
            label="Out of date"
            value={loaded ? String(summary.outOfDate) : "..."}
            detail={summary.outOfDate > 0 ? "images differ from the control node's release" : "every worker node matches the release"}
            tone={summary.outOfDate > 0 ? "bad" : loaded ? "ok" : undefined}
          />
        </div>
        {workerNodesOfCluster && workerNodesState.error && loaded && (
          <p className="meta warning">Worker nodes may be stale: {workerNodesState.error}</p>
        )}
        {offlineWorkerNodes.length > 0 && <ClearOfflineBar operatorUrl={cluster.operatorUrl} offline={offlineWorkerNodes} />}
        {loaded && workerNodes.length === 0 ? (
          <EmptyState title="No worker nodes yet">
            <p>The control node has no paired worker nodes. Worker nodes appear here once they pair and connect.</p>
          </EmptyState>
        ) : (
          <div className="worker-node-grid">
            {workerNodes.map((workerNode) => (
              <WorkerNodeCard
                key={workerNode.worker_node_id}
                workerNode={workerNode}
                operatorUrl={cluster.operatorUrl}
                nowMs={now}
                instancesOpen={workerNode.worker_node_id === instancesWorkerNode?.worker_node_id}
                onToggleInstances={() => setInstancesWorkerNodeId((current) => (current === workerNode.worker_node_id ? null : workerNode.worker_node_id))}
              />
            ))}
          </div>
        )}
        {instancesWorkerNode && (
          <div id="cluster-worker-node-instances">
            <WorkerNodeInstances
              key={`${cluster.operatorUrl}/${instancesWorkerNode.worker_node_id}`}
              workerNode={instancesWorkerNode}
              operatorUrl={cluster.operatorUrl}
              onClose={() => setInstancesWorkerNodeId(null)}
            />
          </div>
        )}
        <Disclosure
          id="cluster:control-node-details"
          title="Control node and connection details"
          hint={statusQuery.data ? `control node ${statusQuery.data.control_node_id}` : undefined}
          headingLevel={3}
        >
          {statusQuery.data ? (
            <ControlNodeDetails
              status={statusQuery.data}
              liveStatus={liveStatus}
              workerNodesSource={workerNodesState.source}
              connected={summary.connected}
              total={summary.workerNodes}
            />
          ) : statusError ? (
            <p className="meta warning">Control node status: {describeOperatorError(statusError)}</p>
          ) : (
            <p className="meta">Checking the control node...</p>
          )}
        </Disclosure>
      </>
    );
  }

  return (
    <SectionFrame title="Cluster" subtitle="The machines that run your simulations, whether they are healthy, and what each one runs now." actions={apiBadge}>
      <div className="cluster-main">{content}</div>
    </SectionFrame>
  );
}
