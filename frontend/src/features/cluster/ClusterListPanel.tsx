import { useState, type FormEvent } from "react";
import { Disclosure } from "../../components/Disclosure";
import { DEFAULT_OPERATOR_URL, useClusterStore, type ClusterEntry } from "../../domain/cluster/clusterStore";

export const SSH_TUNNEL_COMMAND = "ssh -L 5174:127.0.0.1:5174 <user>@<control node>";

interface ClusterFormProps {
  initial: { name: string; operatorUrl: string };
  submitLabel: string;
  onSubmit: (name: string, operatorUrl: string) => string | null;
  onCancel?: () => void;
}

function ClusterForm({ initial, submitLabel, onSubmit, onCancel }: ClusterFormProps) {
  const [name, setName] = useState(initial.name);
  const [operatorUrl, setOperatorUrl] = useState(initial.operatorUrl);
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(onSubmit(name, operatorUrl));
  };

  return (
    <form className="cluster-form" onSubmit={submit}>
      <label className="cluster-form-field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="lab cluster" aria-label="Cluster name" />
      </label>
      <label className="cluster-form-field">
        <span>Operator URL</span>
        <input
          value={operatorUrl}
          onChange={(e) => setOperatorUrl(e.target.value)}
          placeholder={DEFAULT_OPERATOR_URL}
          aria-label="Operator URL"
          spellCheck={false}
        />
      </label>
      {error && <p className="meta warning cluster-form-error">{error}</p>}
      <div className="cluster-form-actions">
        <button type="submit" className="primary-btn accent">
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function ClusterRow({ cluster, selected }: { cluster: ClusterEntry; selected: boolean }) {
  const selectCluster = useClusterStore((s) => s.selectCluster);
  const updateCluster = useClusterStore((s) => s.updateCluster);
  const removeCluster = useClusterStore((s) => s.removeCluster);
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <li className="cluster-row cluster-row--editing">
        <ClusterForm
          initial={cluster}
          submitLabel="Save"
          onCancel={() => setEditing(false)}
          onSubmit={(name, operatorUrl) => {
            const outcome = updateCluster(cluster.id, { name, operatorUrl });
            if (!outcome.ok) {
              return outcome.error;
            }
            setEditing(false);
            return null;
          }}
        />
      </li>
    );
  }

  return (
    <li className={`cluster-row${selected ? " cluster-row--selected" : ""}`}>
      <button
        type="button"
        className="cluster-row-select"
        onClick={() => selectCluster(cluster.id)}
        aria-pressed={selected}
        title={selected ? "Selected cluster" : "Select this cluster"}
      >
        <span className="cluster-row-name">{cluster.name}</span>
        <span className="cluster-row-url">{cluster.operatorUrl}</span>
      </button>
      <div className="cluster-row-actions">
        <button type="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          onClick={() => {
            if (window.confirm(`Remove the cluster "${cluster.name}" from this browser's list?`)) {
              removeCluster(cluster.id);
            }
          }}
        >
          Remove
        </button>
      </div>
    </li>
  );
}

/** The browser's cluster list: select, add, edit and remove clusters. The tunnel hint is behind a toggle. */
export function ClusterListPanel() {
  const clusters = useClusterStore((s) => s.clusters);
  const selectedClusterId = useClusterStore((s) => s.selectedClusterId);
  const addCluster = useClusterStore((s) => s.addCluster);
  const selectCluster = useClusterStore((s) => s.selectCluster);
  const [adding, setAdding] = useState(false);

  return (
    <section className="panel cluster-list-panel" aria-label="Clusters">
      <div className="cluster-panel-head">
        <h3>Clusters</h3>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)}>
            Add cluster
          </button>
        )}
      </div>
      {clusters.length === 0 ? (
        <p className="meta">No clusters yet. Add one with its control node's operator URL.</p>
      ) : (
        <ul className="cluster-rows">
          {clusters.map((cluster) => (
            <ClusterRow key={cluster.id} cluster={cluster} selected={cluster.id === selectedClusterId} />
          ))}
        </ul>
      )}
      {adding && (
        <ClusterForm
          initial={{ name: "", operatorUrl: DEFAULT_OPERATOR_URL }}
          submitLabel="Add"
          onCancel={() => setAdding(false)}
          onSubmit={(name, operatorUrl) => {
            const outcome = addCluster({ name, operatorUrl });
            if (!outcome.ok) {
              return outcome.error;
            }
            selectCluster(outcome.cluster.id);
            setAdding(false);
            return null;
          }}
        />
      )}
      <Disclosure
        id="cluster:tunnel-hint"
        variant="link"
        headingLevel={null}
        title="How do I reach a remote control node?"
        openTitle="Hide the tunnel instructions"
      >
        <div className="cluster-hint">
          <p>
            The UI talks to a control node's operator API, which listens on the control node's 127.0.0.1:5174 only. On the
            control node itself use {DEFAULT_OPERATOR_URL}; from another machine, open a tunnel first and keep that URL:
          </p>
          <code className="cluster-hint-command">{SSH_TUNNEL_COMMAND}</code>
          <p>
            For several clusters, give each tunnel its own local port (such as <code>-L 5175:127.0.0.1:5174</code>)
            and use that port in the cluster's URL. The workbench keeps its own gateway socket.
          </p>
        </div>
      </Disclosure>
    </section>
  );
}
