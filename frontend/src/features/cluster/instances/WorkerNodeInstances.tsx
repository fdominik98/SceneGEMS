import { useMemo, useState } from "react";
import "./instances.css";
import { Disclosure } from "../../../components/Disclosure";
import { EmptyState } from "../../../components/EmptyState";
import { workerNodeInstances, viewerFor, type ObservableInstance } from "../../../domain/cluster/observableInstances";
import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import type { WorkerNodeView } from "../../../domain/cluster/schemas";
import { InstanceList } from "./InstanceList";
import { InstanceViewer } from "./InstanceViewer";
import { useWorkerNodeJobs } from "./useWorkerNodeJobs";

export interface WorkerNodeInstancesProps {
  workerNode: WorkerNodeView;
  operatorUrl: string;
  onClose: () => void;
}

/**
 * The instances of one worker node (its pools and the jobs it holds) and the viewer of the chosen one.
 * Only the viewed instance is subscribed; choosing another, closing the view or closing the panel
 * ends the subscription, and with it the control node's observation of that instance.
 */
export function WorkerNodeInstances({ workerNode, operatorUrl, onClose }: WorkerNodeInstancesProps) {
  const [selected, setSelected] = useState<ObservableInstance | null>(null);
  const jobsQuery = useWorkerNodeJobs(operatorUrl, workerNode);
  const instances = useMemo(() => workerNodeInstances(workerNode, jobsQuery.data ?? []), [workerNode, jobsQuery.data]);
  const viewed = selected && selected.workerNodeId === workerNode.worker_node_id ? selected : null;

  return (
    <section className="panel instances-panel" aria-label={`Instances of ${workerNode.name}`}>
      <header className="instances-panel-head">
        <h3>Instances of {workerNode.name}</h3>
        {viewed && (
          <span className="section-badge section-badge--ok">
            {viewerFor(viewed) === "job" ? "following" : "observing"} {viewed.instance}
          </span>
        )}
        <button type="button" className="instances-panel-close" onClick={onClose}>
          Close the instances
        </button>
      </header>
      <div className="instances-layout">
        <InstanceList
          instances={instances}
          jobsLoading={jobsQuery.isPending}
          jobsError={jobsQuery.error ? describeOperatorError(jobsQuery.error) : null}
          selectedTopic={viewed?.topic ?? null}
          onSelect={setSelected}
        />
        <div className="instances-stage">
          {viewed ? (
            <>
              <div className="instances-stage-bar">
                <button type="button" onClick={() => setSelected(null)}>
                  Close the view
                </button>
              </div>
              <InstanceViewer key={viewed.topic} instance={viewed} />
            </>
          ) : (
            <EmptyState title="Nothing observed yet">
              <p>Choose an instance on the left. The control node observes an instance only while you view it.</p>
              <Disclosure id="cluster:instances-what-you-see" variant="link" headingLevel={null} title="What will I see?" openTitle="Hide the explanation">
                Scene generation and trajectory search instances show their latest sample or preview, a simulation shows its frames at a pace you
                choose, and other jobs show their status and log.
              </Disclosure>
            </EmptyState>
          )}
        </div>
      </div>
    </section>
  );
}
