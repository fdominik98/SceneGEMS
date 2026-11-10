import type { ObservableInstance } from "../../../domain/cluster/observableInstances";
import { KindChip, StateChip } from "./StatusParts";

const KIND_LABELS: Record<ObservableInstance["kind"], string> = {
  scene_generation: "scene generation",
  trajectory_generation: "trajectory search",
  simulation: "simulation",
  monitoring: "monitoring",
};

interface InstanceListProps {
  instances: ObservableInstance[];
  jobsLoading: boolean;
  jobsError: string | null;
  selectedTopic: string | null;
  onSelect: (instance: ObservableInstance) => void;
}

function InstanceRow({ instance, selected, onSelect }: { instance: ObservableInstance; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button type="button" className={`instances-item${selected ? " instances-item--selected" : ""}`} aria-pressed={selected} onClick={onSelect}>
        <span className="instances-item-label">{instance.label}</span>
        <span className="instances-item-chips">
          <KindChip>{KIND_LABELS[instance.kind]}</KindChip>
          <StateChip state={instance.state} />
        </span>
      </button>
    </li>
  );
}

/** A worker node's instances: pool instances from its capabilities and slots, then the jobs it holds. */
export function InstanceList({ instances, jobsLoading, jobsError, selectedTopic, onSelect }: InstanceListProps) {
  const pools = instances.filter((entry) => entry.origin === "pool");
  const jobs = instances.filter((entry) => entry.origin === "job");
  return (
    <nav className="instances-picker" aria-label="Instances">
      <h4 className="instances-subhead">Pools</h4>
      {pools.length === 0 ? (
        <p className="meta">This worker node offers no scene generation or trajectory search slots.</p>
      ) : (
        <ul className="instances-item-list">
          {pools.map((entry) => (
            <InstanceRow key={entry.topic} instance={entry} selected={entry.topic === selectedTopic} onSelect={() => onSelect(entry)} />
          ))}
        </ul>
      )}
      <h4 className="instances-subhead">Leased jobs</h4>
      {jobsError ? (
        <p className="instances-notice instances-notice--warn">{jobsError}</p>
      ) : jobs.length === 0 ? (
        <p className="meta">{jobsLoading ? "Loading the jobs." : "No job is leased or running on this worker node."}</p>
      ) : (
        <ul className="instances-item-list">
          {jobs.map((entry) => (
            <InstanceRow key={entry.topic} instance={entry} selected={entry.topic === selectedTopic} onSelect={() => onSelect(entry)} />
          ))}
        </ul>
      )}
    </nav>
  );
}
