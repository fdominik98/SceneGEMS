import type { CatalogClass, CatalogStacks } from "../../../domain/cluster/campaignApi";
import type { WorkerNodeView } from "../../../domain/cluster/schemas";
import type { ResourcePlan } from "../resourcePlan";
import type { Reason } from "./reasons";
import type { WizardDraft } from "./wizardState";

/** What every step of the wizard receives. */
export interface StepProps {
  draft: WizardDraft;
  /** Applies a change to the draft (a copy to edit in place). */
  update: (change: (draft: WizardDraft) => void) => void;
  /** The reasons that belong to this step: the control node's and the browser's. */
  reasons: readonly Reason[];
}

/** The selected cluster's worker nodes as the resources step shows them. */
export interface ClusterResources {
  /** Whether a cluster is selected at all. */
  selected: boolean;
  /** Whether the control node listed its worker nodes yet. */
  loaded: boolean;
  /** The last problem reading the worker nodes. */
  error: string | null;
  workerNodes: readonly WorkerNodeView[];
  /** What the campaign needs against the worker nodes it may use; null until the worker nodes are loaded. */
  plan: ResourcePlan | null;
  /** Slots per job type of every worker node that can take the campaign's jobs (full usage sizes the queues to them). */
  slots: Readonly<Record<string, number>>;
  /** Why the campaign cannot start, or null. */
  startBlocker: string | null;
}

export interface CatalogState {
  classes: readonly CatalogClass[] | undefined;
  classesError: unknown;
  classesLoading: boolean;
  stacks: CatalogStacks | undefined;
  stacksError: unknown;
  stacksLoading: boolean;
  retry: () => void;
}
