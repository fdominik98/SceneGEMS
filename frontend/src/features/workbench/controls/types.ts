import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { LoadScenarioOptions } from "../../../domain/simulation/useSimulationWorkflow";
import type { ClientToServerMessage } from "../../../domain/simulation/wireTypes";
import type { TrajectoryEntryRequest } from "../cluster/workbenchJobDriver";
import type { JobTypeResources } from "../cluster/workbenchResources";
import type { ClusterRunPlan } from "../cluster/simulationJobs";
import type { PageInput } from "../pages/pageStore";

export interface SimulationStreamControls {
  loadScenarioFromFile: (file: File | null, options?: LoadScenarioOptions) => Promise<void>;
  /** @deprecated Use loadScenarioFromFile */
  initializeSimulation: (file: File | null, options?: LoadScenarioOptions) => Promise<void>;
  startSimulation: () => void;
  resetSimulation: () => void;
  setSpeed: (value: number) => void;
  seek: (value: number) => void;
  sendMessage: (message: ClientToServerMessage) => void;
  /** What the active cluster offers for a job type, and why the workbench cannot run it when it cannot. */
  clusterResources: (jobType: string, components?: readonly string[]) => JobTypeResources;
  /** The active cluster's operator client, null without one. */
  operatorClient: OperatorClient | null;
  generateTrajectories: (requestId: string, request: TrajectoryEntryRequest) => void;
  stopTrajectoryGeneration: () => void;
  /** Sets the simulation page's input and loads its trajectories. */
  setSimulationInput: (input: PageInput, content: string, options?: LoadScenarioOptions) => Promise<void>;
  runSimulationOnCluster: (plan: ClusterRunPlan, colregsConstraintsContent: string) => void;
  stopSimulationOnCluster: () => void;
  /** The operator's Start of an attended run that waits for it. */
  startSimulationOnCluster: () => void;
  setClusterRunSpeed: (speed: number) => void;
}
