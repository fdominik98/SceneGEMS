import { viewerFor, type ObservableInstance } from "../../../domain/cluster/observableInstances";
import { JobViewer } from "./JobViewer";
import { SceneGenerationViewer } from "./SceneGenerationViewer";
import { SimulationViewer } from "./SimulationViewer";
import { TrajectoryViewer } from "./TrajectoryViewer";

/**
 * The viewer of one instance. Each viewer subscribes to its instance topic while it is
 * mounted; the section keys this component by topic, so changing or closing the view ends
 * the subscription and with it the control node's observation.
 */
export function InstanceViewer({ instance }: { instance: ObservableInstance }) {
  switch (viewerFor(instance)) {
    case "scene_generation":
      return <SceneGenerationViewer instance={instance} />;
    case "trajectory_search":
      return <TrajectoryViewer instance={instance} />;
    case "simulation":
      return <SimulationViewer instance={instance} />;
    case "job":
      return <JobViewer instance={instance} />;
  }
}
