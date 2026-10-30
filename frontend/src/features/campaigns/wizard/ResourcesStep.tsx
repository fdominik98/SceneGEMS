import { Disclosure } from "../../../components/Disclosure";
import type { NodeView } from "../../../domain/cluster/schemas";
import { formatMegabytes } from "../../cluster/clusterFormat";
import { plural } from "../campaignFormat";
import { capabilityLabel, fullUsageQueueDepth, needKey, needLabel, nodeProblems, simulationJobTypesOf, slotsByJobType, type CapabilityCoverage } from "../resourcePlan";
import { requiredLabelsOf, stagesOf } from "./configBuilder";
import { Field, FieldIssues, NumberField } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import type { ClusterResources, StepProps } from "./stepTypes";
import { QUEUE_DEPTH_DEFAULTS, QUEUE_DEPTH_LABELS } from "./wizardState";

export interface ResourcesStepProps extends StepProps {
  cluster: ClusterResources;
}

function NeedRow({ entry }: { entry: CapabilityCoverage }) {
  const covered = entry.nodes.length > 0;
  return (
    <li className={`wiz-need wiz-need--${covered ? "ok" : "missing"}`}>
      <span className="wiz-need-mark" aria-hidden="true">
        {covered ? "✓" : "✕"}
      </span>
      <span className="wiz-need-body">
        <strong>{capitalized(needLabel(entry.capability))}</strong>
        <span className="wiz-need-reason">{entry.capability.reason}</span>
      </span>
      <span className="wiz-need-status">{covered ? `${plural(entry.nodes.length, "machine")}, ${plural(entry.slots, "slot")}` : "No machine"}</span>
    </li>
  );
}

function capitalized(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

interface MachineProps {
  node: NodeView;
  /** Whether the campaign uses the node (always in full usage while it can take jobs). */
  used: boolean;
  fullUsage: boolean;
  problems: readonly string[];
  requiredJobTypes: ReadonlySet<string>;
  onToggle: () => void;
}

function Machine({ node, used, fullUsage, problems, requiredJobTypes, onToggle }: MachineProps) {
  const slots = Object.entries(node.slots).sort(([a], [b]) => Number(requiredJobTypes.has(b)) - Number(requiredJobTypes.has(a)) || a.localeCompare(b));
  const title = node.machine ?? node.name;
  return (
    <li className={`wiz-machine${used ? " wiz-machine--used" : ""}${problems.length > 0 ? " wiz-machine--unusable" : ""}`}>
      <label className="wiz-machine-head">
        <input type="checkbox" checked={used} disabled={fullUsage} onChange={onToggle} aria-label={`Use ${title} for the campaign`} />
        <span className="wiz-machine-title">
          <strong title={node.node_id}>{title}</strong>
          <span className="wiz-machine-sub">{node.machine ? `node ${node.name}` : "machine not reported"}</span>
        </span>
        <span className={`node-status node-status--${node.status}`}>{node.status}</span>
      </label>
      <p className="wiz-machine-specs">
        {plural(node.resources.cpus, "CPU")}, {formatMegabytes(node.resources.memory_mb)} memory
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

/** Resources: what the campaign needs, the machines that give it, and which of them the campaign uses (every one at full capacity, or a choice). */
export function ResourcesStep({ draft, update, reasons, cluster }: ResourcesStepProps) {
  const { resources } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), ["nodes", "required_labels", "queue_depth", "priority"]);
  const labels = requiredLabelsOf(draft);
  // Only the stages the campaign's steps use have a queue
  const used = new Set(stagesOf(draft));
  const queueStages = Object.entries(QUEUE_DEPTH_LABELS).filter(([stage]) => used.has(stage));
  const plan = cluster.plan;
  const requiredJobTypes = new Set(plan?.required.map((capability) => capability.jobType) ?? []);
  const usableIds = cluster.nodes.filter((node) => nodeProblems(node, labels).length === 0).map((node) => node.node_id);
  const simulators = simulationJobTypesOf(plan?.required ?? []);
  const fullDepth = fullUsageQueueDepth(cluster.slots, simulators);
  const selectedNodes = cluster.nodes.filter((node) => resources.nodes.includes(node.node_id));

  const setFullUsage = (fullUsage: boolean) =>
    update((next) => {
      next.resources.fullUsage = fullUsage;
      // Switching to a choice starts from what full usage used
      if (!fullUsage && next.resources.nodes.length === 0) {
        next.resources.nodes = [...usableIds];
      }
    });
  const toggleNode = (nodeId: string) =>
    update((next) => {
      next.resources.nodes = next.resources.nodes.includes(nodeId) ? next.resources.nodes.filter((id) => id !== nodeId) : [...next.resources.nodes, nodeId];
    });

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
  } else if (cluster.nodes.length === 0) {
    machines = <p className="wiz-notice">The master lists no machines. Deploy a node and pair it with the master first.</p>;
  } else {
    machines = (
      <ul className="wiz-machines">
        {cluster.nodes.map((node) => {
          const problems = nodeProblems(node, labels);
          return (
            <Machine
              key={node.node_id}
              node={node}
              used={resources.fullUsage ? problems.length === 0 : resources.nodes.includes(node.node_id)}
              fullUsage={resources.fullUsage}
              problems={problems}
              requiredJobTypes={requiredJobTypes}
              onToggle={() => toggleNode(node.node_id)}
            />
          );
        })}
      </ul>
    );
  }

  return (
    <div className="wiz-step">
      <section className="wiz-resources-part" aria-labelledby="wiz-needs-title">
        <h4 id="wiz-needs-title">What the campaign needs</h4>
        <p className="meta wiz-explain">Worked out from the runs. Each one needs at least one usable machine of the campaign, otherwise the campaign cannot start.</p>
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
            <strong>The campaign cannot start.</strong> {cluster.startBlocker} Bring such a machine online{resources.fullUsage ? "" : " or select one"}.
          </p>
        )}
      </section>

      <section className="wiz-resources-part" aria-labelledby="wiz-machines-title">
        <h4 id="wiz-machines-title">Machines</h4>
        <label className={`wiz-option${resources.fullUsage ? " wiz-option--on" : ""}`}>
          <input type="checkbox" checked={resources.fullUsage} onChange={(event) => setFullUsage(event.target.checked)} />
          <span>
            <strong>Use every machine at full capacity</strong>
            <span className="meta">
              The fastest run: every machine of the cluster takes the campaign's jobs, also machines that join later, and the queues are sized so no slot waits for work.
            </span>
          </span>
        </label>
        {!resources.fullUsage && cluster.loaded && (
          <div className="wiz-machine-tools">
            <span className="meta">
              {plural(resources.nodes.length, "machine")} selected, {plan ? plural(plan.usable.length, "machine") : "none"} usable now
            </span>
            <button type="button" onClick={() => update((next) => void (next.resources.nodes = [...usableIds]))} disabled={usableIds.length === 0}>
              Select every usable machine
            </button>
            <button type="button" onClick={() => update((next) => void (next.resources.nodes = []))} disabled={resources.nodes.length === 0}>
              Clear the selection
            </button>
          </div>
        )}
        {plan && plan.unknownNodes.length > 0 && !resources.fullUsage && (
          <p className="wiz-hint wiz-hint--warn">
            {plural(plan.unknownNodes.length, "selected machine")} the master no longer lists.{" "}
            <button
              type="button"
              className="camp-link"
              onClick={() => update((next) => void (next.resources.nodes = next.resources.nodes.filter((id) => !plan.unknownNodes.includes(id))))}
            >
              Remove {plan.unknownNodes.length === 1 ? "it" : "them"}
            </button>
          </p>
        )}
        <FieldIssues reasons={own.byField.get("nodes")} />
        {machines}
      </section>

      <Disclosure
        id="wizard:resources:advanced"
        title="Advanced"
        hint={Object.keys(labels).length > 0 ? `${plural(Object.keys(labels).length, "label")} required` : "queue sizes, priority, labels"}
        forceOpen={own.byField.has("required_labels") || own.byField.has("queue_depth") || own.byField.has("priority")}
        headingLevel={4}
      >
        <div className="wiz-subsection wiz-subsection--first">
          <h5>Queue depth per stage</h5>
          <p className="meta wiz-explain">A new case starts only while every stage has fewer queued jobs of this campaign than its cap. Smaller caps keep the campaign from flooding the cluster.</p>
          {resources.fullUsage ? (
            <>
              <p className="wiz-hint wiz-explain">Full usage sizes each cap to the cluster's slots for that stage, never below the default.</p>
              <dl className="wiz-depths">
                {queueStages.map(([stage, label]) => (
                  <div key={stage}>
                    <dt>{label}</dt>
                    <dd>{fullDepth[stage]}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <>
              <div className="wiz-row">
                {queueStages.map(([stage, label]) => (
                  <Field
                    key={stage}
                    label={label}
                    htmlFor={`depth-${stage}`}
                    hint={`Default ${QUEUE_DEPTH_DEFAULTS[stage]}.`}
                    issues={own.byField.get("queue_depth")?.filter((reason) => reason.field === `queue_depth.${stage}`)}
                  >
                    <NumberField
                      id={`depth-${stage}`}
                      integer
                      min={1}
                      value={resources.queueDepth[stage] ?? null}
                      placeholder={String(QUEUE_DEPTH_DEFAULTS[stage])}
                      onChange={(value) => update((next) => void (next.resources.queueDepth[stage] = value))}
                    />
                  </Field>
                ))}
              </div>
              <div>
                <button
                  type="button"
                  disabled={selectedNodes.length === 0}
                  onClick={() => {
                    const sized = fullUsageQueueDepth(slotsByJobType(selectedNodes, labels), simulators);
                    update((next) => void (next.resources.queueDepth = sized));
                  }}
                >
                  Size to the selected machines
                </button>
              </div>
            </>
          )}
          <FieldIssues reasons={own.byField.get("queue_depth")?.filter((reason) => reason.field === "queue_depth")} />
        </div>

        <div className="wiz-subsection">
          <Field label="Priority" htmlFor="wiz-priority" hint="Base priority of the campaign's jobs. Later stages run above it, so a higher value moves the whole campaign ahead of others." issues={own.byField.get("priority")}>
            <NumberField id="wiz-priority" integer value={resources.priority} invalid={own.byField.has("priority")} onChange={(value) => update((next) => void (next.resources.priority = value))} />
          </Field>
        </div>

        <div className="wiz-subsection">
          <h5>Required node labels</h5>
          <p className="meta wiz-explain">Every job of the campaign runs only on machines that carry all of these labels (for example site: lab). A machine without them is not usable.</p>
          {resources.labels.map((label, index) => (
            <div key={index} className="wiz-map-row">
              <input
                type="text"
                value={label.key}
                placeholder="label"
                aria-label={`Label ${index + 1} name`}
                onChange={(event) => update((next) => void (next.resources.labels[index].key = event.target.value))}
              />
              <input
                type="text"
                value={label.value}
                placeholder="value"
                aria-label={`Label ${index + 1} value`}
                onChange={(event) => update((next) => void (next.resources.labels[index].value = event.target.value))}
              />
              <button type="button" onClick={() => update((next) => void (next.resources.labels = next.resources.labels.filter((_item, at) => at !== index)))}>
                Remove
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="wiz-add" onClick={() => update((next) => void next.resources.labels.push({ key: "", value: "" }))}>
              Add a label
            </button>
          </div>
          <FieldIssues reasons={own.byField.get("required_labels")} />
        </div>
      </Disclosure>
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
