import { useEffect, useState, type ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import "./cluster.css";
import { Disclosure } from "../../components/Disclosure";
import { EmptyState } from "../../components/EmptyState";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useNodesFeed, useNodesStore } from "../../domain/cluster/nodesStore";
import { createOperatorClient, describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { MasterStatus, NodeView } from "../../domain/cluster/schemas";
import { useLiveChannelStatus } from "../../domain/cluster/useLiveTopic";
import { ClusterListPanel, SSH_TUNNEL_COMMAND } from "./ClusterListPanel";
import { shortHash, summarizeNodes } from "./clusterFormat";
import { NodeInstances } from "./instances/NodeInstances";
import { NodeCard } from "./NodeCard";
import { useMasterStatus } from "./useMasterStatus";

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

interface MasterDetailsProps {
  status: MasterStatus;
  liveStatus: keyof typeof LIVE_LABELS;
  nodesSource: string | null;
  connected: number;
  total: number;
}

/** The technical side of the master: its id, the live channel, how nodes update, and the release fingerprints. */
function MasterDetails({ status, liveStatus, nodesSource, connected, total }: MasterDetailsProps) {
  const images = Object.entries(status.expected_fingerprints.images).sort(([a], [b]) => a.localeCompare(b));
  const fingerprints = status.expected_fingerprints;
  return (
    <div className="master-status-panel">
      <dl className="master-facts">
        <div>
          <dt>Master</dt>
          <dd>{status.master_id}</dd>
        </div>
        <div>
          <dt>Nodes with a control link</dt>
          <dd>
            {connected} / {total}
          </dd>
        </div>
        <div>
          <dt>Live channel</dt>
          <dd>{LIVE_LABELS[liveStatus]}</dd>
        </div>
        <div>
          <dt>Node updates</dt>
          <dd>{nodesSource === "live" && liveStatus === "open" ? "pushed live" : "polled every 5 s"}</dd>
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
        <table className="master-images">
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
        <p className="meta">The master lists no expected images yet.</p>
      )}
    </div>
  );
}

/** Removes every offline node of the cluster, e.g. the old versions of nodes that came back under a new id. */
function ClearOfflineBar({ operatorUrl, offline }: { operatorUrl: string; offline: NodeView[] }) {
  const removeNode = useNodesStore((s) => s.removeNode);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clear = async () => {
    setPending(true);
    setError(null);
    const client = createOperatorClient(operatorUrl);
    const failures: string[] = [];
    for (const node of offline) {
      try {
        removeNode(await client.removeNode(node.node_id));
      } catch (failure) {
        failures.push(`${node.name}: ${describeOperatorError(failure)}`);
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
        className={`node-card-action${confirming ? " node-card-action--danger" : ""}`}
        disabled={pending}
        onClick={() => (confirming ? void clear() : setConfirming(true))}
        onBlur={() => setConfirming(false)}
        title="Forget every offline node. One that connects again reappears."
      >
        {pending ? "Clearing..." : confirming ? `Confirm: remove ${offline.length}` : `Clear ${offline.length} offline`}
      </button>
      {error && <p className="meta warning">{error}</p>}
    </div>
  );
}

/** The Cluster section: the selected cluster's master and its nodes as machine resources. */
export function ClusterSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  // What the page shows of the store, not its actions
  const nodesState = useNodesStore(
    useShallow((state) => ({ operatorUrl: state.operatorUrl, nodes: state.nodes, loaded: state.loaded, error: state.error, unreachable: state.unreachable, source: state.source }))
  );
  const liveStatus = useLiveChannelStatus(operatorUrl);
  const statusQuery = useMasterStatus(operatorUrl);
  const now = useNow(5_000);
  const [instancesNodeId, setInstancesNodeId] = useState<string | null>(null);

  const nodesOfCluster = nodesState.operatorUrl === operatorUrl;
  const nodes = nodesOfCluster ? nodesState.nodes : [];
  const loaded = nodesOfCluster && nodesState.loaded;
  const statusError = statusQuery.error;
  const unreachable =
    !loaded &&
    ((statusError instanceof OperatorApiError && statusError.unreachable) || (nodesOfCluster && nodesState.unreachable));
  const summary = summarizeNodes(nodes);
  const offlineNodes = nodes.filter((node) => node.status === "offline");
  const instancesNode = nodes.find((node) => node.node_id === instancesNodeId) ?? null;

  const apiBadge = cluster && (
    <div className="section-badges">
      <span className={`section-badge${statusQuery.isSuccess ? " section-badge--ok" : statusError ? " section-badge--bad" : ""}`}>
        {statusQuery.isSuccess ? "Connected to the master" : statusError ? "Cannot reach the master" : "Checking the master"}
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
    const error = statusError ?? nodesState.error;
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
            Check that the master runs and that its operator API is reachable at <code>{cluster.operatorUrl}</code>.
          </p>
          <Disclosure
            id="cluster:unreachable-tunnel"
            variant="link"
            headingLevel={null}
            title="It is a remote master"
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
            label="Nodes online"
            value={loaded ? `${summary.online} / ${summary.nodes}` : "..."}
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
            detail={summary.outOfDate > 0 ? "images differ from the master's release" : "every node matches the release"}
            tone={summary.outOfDate > 0 ? "bad" : loaded ? "ok" : undefined}
          />
        </div>
        {nodesOfCluster && nodesState.error && loaded && (
          <p className="meta warning">Nodes may be stale: {nodesState.error}</p>
        )}
        {offlineNodes.length > 0 && <ClearOfflineBar operatorUrl={cluster.operatorUrl} offline={offlineNodes} />}
        {loaded && nodes.length === 0 ? (
          <EmptyState title="No nodes yet">
            <p>The master has no paired nodes. Nodes appear here once they pair and connect.</p>
          </EmptyState>
        ) : (
          <div className="node-grid">
            {nodes.map((node) => (
              <NodeCard
                key={node.node_id}
                node={node}
                operatorUrl={cluster.operatorUrl}
                nowMs={now}
                instancesOpen={node.node_id === instancesNode?.node_id}
                onToggleInstances={() => setInstancesNodeId((current) => (current === node.node_id ? null : node.node_id))}
              />
            ))}
          </div>
        )}
        {instancesNode && (
          <div id="cluster-node-instances">
            <NodeInstances
              key={`${cluster.operatorUrl}/${instancesNode.node_id}`}
              node={instancesNode}
              operatorUrl={cluster.operatorUrl}
              onClose={() => setInstancesNodeId(null)}
            />
          </div>
        )}
        <Disclosure
          id="cluster:master-details"
          title="Master and connection details"
          hint={statusQuery.data ? `master ${statusQuery.data.master_id}` : undefined}
          headingLevel={3}
        >
          {statusQuery.data ? (
            <MasterDetails
              status={statusQuery.data}
              liveStatus={liveStatus}
              nodesSource={nodesState.source}
              connected={summary.connected}
              total={summary.nodes}
            />
          ) : statusError ? (
            <p className="meta warning">Master status: {describeOperatorError(statusError)}</p>
          ) : (
            <p className="meta">Checking the master...</p>
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
