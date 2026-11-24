import type { WorkerNodeView } from "../../../domain/cluster/schemas";
import { formatMegabytes } from "../../cluster/clusterFormat";
import { plural } from "../campaignFormat";
import { capabilityLabel, needKey, needLabel, workerNodeProblems, type CapabilityCoverage } from "../resourcePlan";
import { FieldIssues } from "./fields";
import type { ClusterResources, StepProps } from "./stepTypes";

export interface ResourcesStepProps extends StepProps {
  cluster: ClusterResources;
}

/** A campaign of the wizard requires no machine labels. */
const NO_LABELS: Readonly<Record<string, string>> = {};

function NeedRow({ entry }: { entry: CapabilityCoverage }) {
  const covered = entry.workerNodes.length > 0;
  return (
    <li className={`wiz-need wiz-need--${covered ? "ok" : "missing"}`}>
      <span className="wiz-need-mark" aria-hidden="true">
        {covered ? "✓" : "✕"}
      </span>
      <span className="wiz-need-body">
        <strong>{capitalized(needLabel(entry.capability))}</strong>
        <span className="wiz-need-reason">{entry.capability.reason}</span>
      </span>
      <span className="wiz-need-status">{covered ? `${plural(entry.workerNodes.length, "machine")}, ${plural(entry.slots, "slot")}` : "No machine"}</span>
    </li>
  );
}

function capitalized(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

interface MachineProps {
  workerNode: WorkerNodeView;
  problems: readonly string[];
  requiredJobTypes: ReadonlySet<string>;
}

function Machine({ workerNode, problems, requiredJobTypes }: MachineProps) {
  const slots = Object.entries(workerNode.slots).sort(([a], [b]) => Number(requiredJobTypes.has(b)) - Number(requiredJobTypes.has(a)) || a.localeCompare(b));
  const title = workerNode.machine ?? workerNode.name;
  const used = problems.length === 0;
  return (
    <li className={`wiz-machine${used ? " wiz-machine--used" : " wiz-machine--unusable"}`}>
      <div className="wiz-machine-head">
        <span className="wiz-machine-title">
          <strong title={workerNode.worker_node_id}>{title}</strong>
          <span className="wiz-machine-sub">{workerNode.machine ? `worker node ${workerNode.name}` : "machine not reported"}</span>
        </span>
        <span className={`worker-node-status worker-node-status--${workerNode.status}`}>{workerNode.status}</span>
      </div>
      <p className="wiz-machine-specs">
        {plural(workerNode.resources.cpus, "CPU")}, {formatMegabytes(workerNode.resources.memory_mb)} memory
      </p>
      {slots.length === 0 ? (
        <p className="wiz-hint">Offers no job types.</p>
      ) : (
        <ul className="wiz-machine-caps" aria-label={`Capabilities of ${title}`}>
          {slots.map(([jobType, usage]) => (
            <li key={jobType} className={`wiz-cap${requiredJobTypes.has(jobType) ? " wiz-cap--needed" : ""}`}>
              {capabilityLabel(jobType)} <span className="wiz-cap-slots">{plural(usage.slots, "slot")}</span>
            </li>
          ))}
        </ul>
      )}
      {problems.map((problem) => (
        <p key={problem} className="wiz-hint wiz-hint--warn">
          {problem}
        </p>
      ))}
    </li>
  );
}

/**
 * Resources: what the campaign needs and the machines that give it. There is nothing to set: a
 * campaign uses every machine of the cluster that can take jobs, also machines that join later,
 * and the control node hands each job to the first machine with a free slot for it. The page says
 * whether the cluster can run the campaign at all, and on what.
 */
export function ResourcesStep({ reasons, cluster }: ResourcesStepProps) {
  const plan = cluster.plan;
  const requiredJobTypes = new Set(plan?.required.map((capability) => capability.jobType) ?? []);

  let machines;
  if (!cluster.selected) {
    machines = <p className="wiz-notice">Choose a cluster in the Cluster section to see its machines.</p>;
  } else if (!cluster.loaded) {
    machines = cluster.error ? (
      <p className="wiz-error" role="alert">
        The machines could not be read: {cluster.error}
      </p>
    ) : (
      <p className="meta" role="status">
        Reading the cluster's machines...
      </p>
    );
  } else if (cluster.workerNodes.length === 0) {
    machines = <p className="wiz-notice">The control node lists no machines. Deploy a worker node and pair it with the control node first.</p>;
  } else {
    machines = (
      <ul className="wiz-machines">
        {cluster.workerNodes.map((workerNode) => (
          <Machine key={workerNode.worker_node_id} workerNode={workerNode} problems={workerNodeProblems(workerNode, NO_LABELS)} requiredJobTypes={requiredJobTypes} />
        ))}
      </ul>
    );
  }

  return (
    <div className="wiz-step">
      <section className="wiz-resources-part" aria-labelledby="wiz-needs-title">
        <h4 id="wiz-needs-title">What the campaign needs</h4>
        <p className="meta wiz-explain">Worked out from the runs. Each one needs at least one usable machine, otherwise the campaign cannot start.</p>
        {plan ? (
          <ul className="wiz-needs">
            {plan.coverage.map((entry) => (
              <NeedRow key={needKey(entry.capability)} entry={entry} />
            ))}
          </ul>
        ) : (
          <p className="meta">Shown once the cluster's machines are read.</p>
        )}
        {cluster.startBlocker && cluster.loaded && (
          <p className="wiz-error" role="alert">
            <strong>The campaign cannot start.</strong> {cluster.startBlocker} Bring such a machine online.
          </p>
        )}
      </section>

      <section className="wiz-resources-part" aria-labelledby="wiz-machines-title">
        <h4 id="wiz-machines-title">Machines</h4>
        <p className="wiz-hint">
          Nothing to set here: the campaign uses every machine that can take jobs, also machines that join later, and each job goes to the first machine with a free slot for it.
          {plan && cluster.loaded ? ` ${plural(plan.usable.length, "machine")} usable now.` : ""}
        </p>
        {machines}
      </section>
      <FieldIssues reasons={reasons} showField />
    </div>
  );
}
