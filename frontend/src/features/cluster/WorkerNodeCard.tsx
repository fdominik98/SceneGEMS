import { useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { componentLabel, isWhollyOutOfDate, staleComponents } from "../../domain/cluster/components";
import { createOperatorClient, describeOperatorError } from "../../domain/cluster/operatorApi";
import { useWorkerNodesStore } from "../../domain/cluster/workerNodesStore";
import type { WorkerNodeView } from "../../domain/cluster/schemas";
import {
  formatAge,
  formatMegabytes,
  jobTypeLabel,
  memoryUseFraction,
  workerNodeSlotTotals,
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
    <span className={`worker-node-meter worker-node-meter--${level}`} role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <span className="worker-node-meter-fill" style={{ width: `${Math.round(fraction * 100)}%` }} />
    </span>
  );
}

interface WorkerNodeCardProps {
  workerNode: WorkerNodeView;
  operatorUrl: string;
  nowMs: number;
  /** The worker node's instances are shown below the cards. */
  instancesOpen: boolean;
  onToggleInstances: () => void;
}

/** One worker node of the cluster as a machine resource: state, components, slots, resources, leases and release; it opens the worker node's instances. */
export function WorkerNodeCard({ workerNode, operatorUrl, nowMs, instancesOpen, onToggleInstances }: WorkerNodeCardProps) {
  const applyWorkerNode = useWorkerNodesStore((s) => s.applyWorkerNode);
  const removeWorkerNode = useWorkerNodesStore((s) => s.removeWorkerNode);
  const [pending, setPending] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const totals = workerNodeSlotTotals(workerNode);
  const slots = Object.entries(workerNode.slots).sort(([a], [b]) => a.localeCompare(b));
  const stale = staleComponents(workerNode);
  const labels = Object.entries(workerNode.labels).sort(([a], [b]) => a.localeCompare(b));
  const { resources } = workerNode;
  const memoryUsed = resources.memory_mb - resources.free_memory_mb;
  const draining = workerNode.status === "draining";
  const memoryLow = memoryUseFraction(resources.memory_mb, resources.free_memory_mb) >= 0.9;

  const toggleDrain = async () => {
    setPending(true);
    setActionError(null);
    try {
      const client = createOperatorClient(operatorUrl);
      applyWorkerNode(draining ? await client.resumeWorkerNode(workerNode.worker_node_id) : await client.drainWorkerNode(workerNode.worker_node_id));
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
      removeWorkerNode(await createOperatorClient(operatorUrl).removeWorkerNode(workerNode.worker_node_id));
    } catch (error) {
      setActionError(describeOperatorError(error));
      setConfirmingRemove(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <article className={`worker-node-card worker-node-card--${workerNode.status}${workerNode.out_of_date ? " worker-node-card--stale" : ""}`}>
      <header className="worker-node-card-head">
        <span
          className={`worker-node-dot${workerNode.connected ? " worker-node-dot--connected" : ""}`}
          title={workerNode.connected ? "Connected to the control node" : "Not connected"}
          aria-label={workerNode.connected ? "connected" : "not connected"}
        />
        <div className="worker-node-card-title">
          <span className="worker-node-card-name" title={workerNode.worker_node_id}>
            {workerNode.name}
          </span>
          <span className="worker-node-card-machine">
            {workerNode.machine ? `on ${workerNode.machine}` : "machine not reported"}
          </span>
        </div>
        <span className={`worker-node-status worker-node-status--${workerNode.status}`}>{workerNode.status}</span>
        {workerNode.status === "offline" ? (
          <button
            type="button"
            className={`worker-node-card-action${confirmingRemove ? " worker-node-card-action--danger" : ""}`}
            disabled={pending}
            onClick={() => (confirmingRemove ? void remove() : setConfirmingRemove(true))}
            onBlur={() => setConfirmingRemove(false)}
            title="Forget this offline worker node. It reappears if it connects again."
          >
            {pending ? "..." : confirmingRemove ? "Confirm" : "Remove"}
          </button>
        ) : (
          <button
            type="button"
            className="worker-node-card-action"
            disabled={pending}
            onClick={() => void toggleDrain()}
            title={draining ? "Let the worker node receive jobs again" : "No new jobs for this worker node; running ones finish"}
          >
            {pending ? "..." : draining ? "Resume" : "Drain"}
          </button>
        )}
      </header>

      {actionError && <p className="meta warning worker-node-card-error">{actionError}</p>}

      {workerNode.out_of_date && (
        <div className="worker-node-stale" role="status">
          <strong>Out of date:</strong>{" "}
          {isWhollyOutOfDate(workerNode)
            ? "its images differ from the control node's release, so it gets no jobs."
            : stale.length > 0
              ? `the images of ${stale.map(componentLabel).join(", ")} differ from the control node's release; jobs needing ${stale.length === 1 ? "it" : "them"} go elsewhere.`
              : "its images differ from the control node's release."}
          <ul className="worker-node-stale-list">
            {workerNode.fingerprint_mismatches.map((mismatch) => (
              <li key={mismatch.image}>
                <code>{mismatch.image}</code> needs <code title={mismatch.required}>{shortHash(mismatch.required)}</code>
                {mismatch.actual === null ? (
                  ", missing on the worker node"
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

      <ul className="worker-node-components" aria-label="Components">
        {workerNode.components.length === 0 ? (
          <li className="meta">No components reported.</li>
        ) : (
          workerNode.components.map((entry) => (
            <li
              key={entry.component}
              className={`worker-node-component${entry.state === "out_of_date" ? " worker-node-component--stale" : ""}`}
              title={`${entry.component}${entry.images.length > 0 ? `: ${entry.images.join(", ")}` : ", no image of its own"}${entry.state === "out_of_date" ? " (out of date)" : ""}`}
            >
              {componentLabel(entry.component)}
              {entry.state === "out_of_date" && <span className="worker-node-component-state"> out of date</span>}
            </li>
          ))
        )}
      </ul>

      <div className="worker-node-card-summary">
        <div className="worker-node-card-block-head">
          <span>Slots in use</span>
          <span className="worker-node-card-block-total">
            {totals.inUse} / {totals.slots}
          </span>
        </div>
        <Meter value={totals.inUse} max={totals.slots} label="Slots in use" />
        {memoryLow && <span className="worker-node-chip worker-node-chip--warn">Memory is low</span>}
      </div>

      <button
        type="button"
        className={`worker-node-card-instances${instancesOpen ? " worker-node-card-instances--open" : ""}`}
        aria-expanded={instancesOpen}
        aria-controls="cluster-worker-node-instances"
        onClick={onToggleInstances}
        title="The worker node's pools and the jobs it holds, each viewable live"
      >
        {instancesOpen ? "Hide the instances" : `Instances${workerNode.leases.length > 0 ? ` (${workerNode.leases.length} ${workerNode.leases.length === 1 ? "job" : "jobs"})` : ""}`}
      </button>

      <Disclosure
        id={`cluster:worker node:${workerNode.worker_node_id}`}
        variant="link"
        headingLevel={null}
        title="Details"
        openTitle="Hide details"
      >
      <div className="worker-node-card-block">
        <div className="worker-node-card-block-head">
          <span>Slots</span>
          <span className="worker-node-card-block-total">
            {totals.inUse} / {totals.slots} in use
          </span>
        </div>
        {slots.length === 0 ? (
          <p className="meta">No slots reported.</p>
        ) : (
          <ul className="worker-node-capabilities">
            {slots.map(([jobType, usage]) => (
              <li key={jobType} className="worker-node-capability">
                <span className="worker-node-capability-name" title={jobType}>
                  {jobTypeLabel(jobType)}
                </span>
                <Meter value={usage.slots_in_use} max={usage.slots} label={`${jobTypeLabel(jobType)} slots in use`} />
                <span className="worker-node-capability-count">
                  {usage.slots_in_use}/{usage.slots}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <dl className="worker-node-facts">
        <div>
          <dt>CPUs</dt>
          <dd>
            {resources.cpus} <span className="worker-node-fact-sub">load {resources.load_average.toFixed(2)}</span>
          </dd>
        </div>
        <div>
          <dt>Memory</dt>
          <dd>
            <Meter value={memoryUsed} max={resources.memory_mb} label="Memory in use" />
            <span className="worker-node-fact-sub">
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
          <dd title={workerNode.leases.join("\n") || undefined}>
            {workerNode.leases.length === 0 ? "none" : workerNode.leases.length}
          </dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd>
            <code title={workerNode.software_revision}>{shortHash(workerNode.software_revision, 10)}</code>
          </dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd title={workerNode.last_seen_at}>{formatAge(workerNode.last_seen_at, nowMs)}</dd>
        </div>
      </dl>

      {labels.length > 0 && (
        <ul className="worker-node-labels" aria-label="Labels">
          {labels.map(([key, value]) => (
            <li key={key} className="worker-node-label">
              {key}={value}
            </li>
          ))}
        </ul>
      )}

      {workerNode.leases.length > 0 && (
        <details className="worker-node-leases">
          <summary>Leases ({workerNode.leases.length})</summary>
          <ul>
            {workerNode.leases.map((lease) => (
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
