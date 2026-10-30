import { useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { componentLabel, isWhollyOutOfDate, staleComponents } from "../../domain/cluster/components";
import { createOperatorClient, describeOperatorError } from "../../domain/cluster/operatorApi";
import { useNodesStore } from "../../domain/cluster/nodesStore";
import type { NodeView } from "../../domain/cluster/schemas";
import {
  formatAge,
  formatMegabytes,
  jobTypeLabel,
  memoryUseFraction,
  nodeSlotTotals,
  shortHash,
} from "./clusterFormat";

interface MeterProps {
  value: number;
  max: number;
  label: string;
}

function Meter({ value, max, label }: MeterProps) {
  const fraction = max > 0 ? Math.min(1, value / max) : 0;
  const level = fraction >= 1 ? "full" : fraction >= 0.75 ? "high" : fraction > 0 ? "used" : "empty";
  return (
    <span className={`node-meter node-meter--${level}`} role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <span className="node-meter-fill" style={{ width: `${Math.round(fraction * 100)}%` }} />
    </span>
  );
}

interface NodeCardProps {
  node: NodeView;
  operatorUrl: string;
  nowMs: number;
  /** The node's instances are shown below the cards. */
  instancesOpen: boolean;
  onToggleInstances: () => void;
}

/** One node of the cluster as a machine resource: state, components, slots, resources, leases and release; it opens the node's instances. */
export function NodeCard({ node, operatorUrl, nowMs, instancesOpen, onToggleInstances }: NodeCardProps) {
  const applyNode = useNodesStore((s) => s.applyNode);
  const removeNode = useNodesStore((s) => s.removeNode);
  const [pending, setPending] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const totals = nodeSlotTotals(node);
  const slots = Object.entries(node.slots).sort(([a], [b]) => a.localeCompare(b));
  const stale = staleComponents(node);
  const labels = Object.entries(node.labels).sort(([a], [b]) => a.localeCompare(b));
  const { resources } = node;
  const memoryUsed = resources.memory_mb - resources.free_memory_mb;
  const draining = node.status === "draining";
  const memoryLow = memoryUseFraction(resources.memory_mb, resources.free_memory_mb) >= 0.9;

  const toggleDrain = async () => {
    setPending(true);
    setActionError(null);
    try {
      const client = createOperatorClient(operatorUrl);
      applyNode(draining ? await client.resumeNode(node.node_id) : await client.drainNode(node.node_id));
    } catch (error) {
      setActionError(describeOperatorError(error));
    } finally {
      setPending(false);
    }
  };

  const remove = async () => {
    setPending(true);
    setActionError(null);
    try {
      removeNode(await createOperatorClient(operatorUrl).removeNode(node.node_id));
    } catch (error) {
      setActionError(describeOperatorError(error));
      setConfirmingRemove(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <article className={`node-card node-card--${node.status}${node.out_of_date ? " node-card--stale" : ""}`}>
      <header className="node-card-head">
        <span
          className={`node-dot${node.connected ? " node-dot--connected" : ""}`}
          title={node.connected ? "Connected to the master" : "Not connected"}
          aria-label={node.connected ? "connected" : "not connected"}
        />
        <div className="node-card-title">
          <span className="node-card-name" title={node.node_id}>
            {node.name}
          </span>
          <span className="node-card-machine">
            {node.machine ? `on ${node.machine}` : "machine not reported"}
          </span>
        </div>
        <span className={`node-status node-status--${node.status}`}>{node.status}</span>
        {node.status === "offline" ? (
          <button
            type="button"
            className={`node-card-action${confirmingRemove ? " node-card-action--danger" : ""}`}
            disabled={pending}
            onClick={() => (confirmingRemove ? void remove() : setConfirmingRemove(true))}
            onBlur={() => setConfirmingRemove(false)}
            title="Forget this offline node. It reappears if it connects again."
          >
            {pending ? "..." : confirmingRemove ? "Confirm" : "Remove"}
          </button>
        ) : (
          <button
            type="button"
            className="node-card-action"
            disabled={pending}
            onClick={() => void toggleDrain()}
            title={draining ? "Let the node receive jobs again" : "No new jobs for this node; running ones finish"}
          >
            {pending ? "..." : draining ? "Resume" : "Drain"}
          </button>
        )}
      </header>

      {actionError && <p className="meta warning node-card-error">{actionError}</p>}

      {node.out_of_date && (
        <div className="node-stale" role="status">
          <strong>Out of date:</strong>{" "}
          {isWhollyOutOfDate(node)
            ? "its images differ from the master's release, so it gets no jobs."
            : stale.length > 0
              ? `the images of ${stale.map(componentLabel).join(", ")} differ from the master's release; jobs needing ${stale.length === 1 ? "it" : "them"} go elsewhere.`
              : "its images differ from the master's release."}
          <ul className="node-stale-list">
            {node.fingerprint_mismatches.map((mismatch) => (
              <li key={mismatch.image}>
                <code>{mismatch.image}</code> needs <code title={mismatch.required}>{shortHash(mismatch.required)}</code>
                {mismatch.actual === null ? (
                  ", missing on the node"
                ) : (
                  <>
                    , has <code title={mismatch.actual}>{shortHash(mismatch.actual)}</code>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="node-components" aria-label="Components">
        {node.components.length === 0 ? (
          <li className="meta">No components reported.</li>
        ) : (
          node.components.map((entry) => (
            <li
              key={entry.component}
              className={`node-component${entry.state === "out_of_date" ? " node-component--stale" : ""}`}
              title={`${entry.component}${entry.images.length > 0 ? `: ${entry.images.join(", ")}` : ", no image of its own"}${entry.state === "out_of_date" ? " (out of date)" : ""}`}
            >
              {componentLabel(entry.component)}
              {entry.state === "out_of_date" && <span className="node-component-state"> out of date</span>}
            </li>
          ))
        )}
      </ul>

      <div className="node-card-summary">
        <div className="node-card-block-head">
          <span>Slots in use</span>
          <span className="node-card-block-total">
            {totals.inUse} / {totals.slots}
          </span>
        </div>
        <Meter value={totals.inUse} max={totals.slots} label="Slots in use" />
        {memoryLow && <span className="node-chip node-chip--warn">Memory is low</span>}
      </div>

      <button
        type="button"
        className={`node-card-instances${instancesOpen ? " node-card-instances--open" : ""}`}
        aria-expanded={instancesOpen}
        aria-controls="cluster-node-instances"
        onClick={onToggleInstances}
        title="The node's pools and the jobs it holds, each viewable live"
      >
        {instancesOpen ? "Hide the instances" : `Instances${node.leases.length > 0 ? ` (${node.leases.length} ${node.leases.length === 1 ? "job" : "jobs"})` : ""}`}
      </button>

      <Disclosure
        id={`cluster:node:${node.node_id}`}
        variant="link"
        headingLevel={null}
        title="Details"
        openTitle="Hide details"
      >
      <div className="node-card-block">
        <div className="node-card-block-head">
          <span>Slots</span>
          <span className="node-card-block-total">
            {totals.inUse} / {totals.slots} in use
          </span>
        </div>
        {slots.length === 0 ? (
          <p className="meta">No slots reported.</p>
        ) : (
          <ul className="node-capabilities">
            {slots.map(([jobType, usage]) => (
              <li key={jobType} className="node-capability">
                <span className="node-capability-name" title={jobType}>
                  {jobTypeLabel(jobType)}
                </span>
                <Meter value={usage.slots_in_use} max={usage.slots} label={`${jobTypeLabel(jobType)} slots in use`} />
                <span className="node-capability-count">
                  {usage.slots_in_use}/{usage.slots}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <dl className="node-facts">
        <div>
          <dt>CPUs</dt>
          <dd>
            {resources.cpus} <span className="node-fact-sub">load {resources.load_average.toFixed(2)}</span>
          </dd>
        </div>
        <div>
          <dt>Memory</dt>
          <dd>
            <Meter value={memoryUsed} max={resources.memory_mb} label="Memory in use" />
            <span className="node-fact-sub">
              {formatMegabytes(memoryUsed)} of {formatMegabytes(resources.memory_mb)} used
              {memoryLow ? " (low)" : ""}
            </span>
          </dd>
        </div>
        <div>
          <dt>Disk free</dt>
          <dd>{formatMegabytes(resources.free_disk_mb)}</dd>
        </div>
        <div>
          <dt>Leases</dt>
          <dd title={node.leases.join("\n") || undefined}>
            {node.leases.length === 0 ? "none" : node.leases.length}
          </dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd>
            <code title={node.software_revision}>{shortHash(node.software_revision, 10)}</code>
          </dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd title={node.last_seen_at}>{formatAge(node.last_seen_at, nowMs)}</dd>
        </div>
      </dl>

      {labels.length > 0 && (
        <ul className="node-labels" aria-label="Labels">
          {labels.map(([key, value]) => (
            <li key={key} className="node-label">
              {key}={value}
            </li>
          ))}
        </ul>
      )}

      {node.leases.length > 0 && (
        <details className="node-leases">
          <summary>Leases ({node.leases.length})</summary>
          <ul>
            {node.leases.map((lease) => (
              <li key={lease}>
                <code>{lease}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
      </Disclosure>
    </article>
  );
}
