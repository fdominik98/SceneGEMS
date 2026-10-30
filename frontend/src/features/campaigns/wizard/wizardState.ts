import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";
import type { ConfigArtifactRef, InputItemSource, StepMonitor } from "../../../domain/cluster/campaignApi";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { CHAIN, normalizeSteps } from "./stepPlan";

/**
 * The state of the create wizard. It holds what the operator entered, in plain JSON, and leaves
 * out everything the master derives: `configBuilder.ts` turns it into the campaign config, and the
 * stored draft survives a reload (one per browser).
 */

export const WIZARD_STEPS = ["steps", "input", "domain", "trajectories", "runs", "resources", "policy", "review"] as const;
export type WizardStepId = (typeof WIZARD_STEPS)[number];

export const WIZARD_STEP_LABELS: Record<WizardStepId, string> = {
  steps: "Steps",
  input: "Input",
  domain: "Domain",
  trajectories: "Trajectories",
  runs: "Runs",
  resources: "Resources",
  policy: "Policy",
  review: "Review",
};

/** Values by parameter key; a key that is absent is left out of the config. */
export type ParamValues = Record<string, unknown>;

/** The failure budget of a class that is never abandoned: it replaces dropped and failed cases until its quota is complete. */
export const UNLIMITED_FAILURE_BUDGET = "unlimited";

/** Dropped and failed cases a class may use up before it is abandoned, or unlimited; null while the box is empty. */
export type FailureBudgetDraft = number | typeof UNLIMITED_FAILURE_BUDGET | null;

export interface ScopeEntryDraft {
  id: string;
  /** Class ids of the catalog. */
  classes: string[];
  /** Folder patterns (no slash) or class id patterns (with a slash), shell wildcards. */
  patterns: string[];
  quota: number | null;
  failureBudget: FailureBudgetDraft;
}

/** How long an uploaded file stays on the master unless a campaign uses it (`artifact_reference.expires_at` of an upload). */
export const UPLOAD_LIFETIME_MS = 24 * 60 * 60 * 1000;

/** A functional scenario file uploaded for scene generation: a class of its own, `scenario/<name>`. */
export interface ScenarioFileDraft {
  id: string;
  /** The file's name as it was picked. */
  fileName: string;
  /** The scenario's name in the campaign (the class id is `scenario/<name>`). */
  name: string;
  ref: ConfigArtifactRef;
  quota: number | null;
  failureBudget: FailureBudgetDraft;
  /** When the file was uploaded (ms since the epoch); it expires 24 hours later unless a campaign uses it. */
  uploadedAt: number;
}

/** A scene (trajectory generation) or a trajectory set (simulation) a campaign starts from. */
export interface InputItemDraft {
  id: string;
  name: string;
  ref: ConfigArtifactRef;
  source: InputItemSource;
  /** Set for an uploaded file; null for an output of Campaign History, which the master keeps. */
  uploadedAt: number | null;
}

export interface InputDraft {
  scenarios: ScenarioFileDraft[];
  items: InputItemDraft[];
}

export interface DomainDraft {
  /** False: the fields stay out of the config and the master's defaults apply. */
  custom: boolean;
  colregsConstants: string;
  vesselTypes: string;
  obstacleTypes: string;
  sceneGenerationTimeoutS: number | null;
  enforceLowTcpa: boolean;
}

export interface TrajectoriesDraft {
  generator: string;
  /** The generator's own parameters (search parameters, or the straight generator's timespan). */
  parameters: ParamValues;
  timeoutS: number | null;
}

export interface RunDraft {
  id: string;
  name: string;
  stackId: string;
  monitor: string;
  earlyStop: boolean;
  seed: number | null;
  repeats: number | null;
  /** Parameters of the stack itself (`dt`, `steps`). */
  stackParameters: ParamValues;
  /** Parameter groups by key; a group that is absent is left out and derived per scene. */
  groups: Record<string, ParamValues>;
  windVector: number[] | null;
  waves: ParamValues | null;
}

export interface ResourcesDraft {
  /** Every node of the cluster, also nodes that join later, with the queue caps sized to its slots. */
  fullUsage: boolean;
  /** Node ids the campaign may use when it does not use every node. */
  nodes: string[];
  labels: { key: string; value: string }[];
  queueDepth: Record<string, number | null>;
  priority: number | null;
}

export type RetentionPolicy = "all" | "failures" | "verdicts_only";

export interface PolicyDraft {
  retention: RetentionPolicy;
  keepFrames: boolean;
  seed: number | null;
  maxCases: number | null;
  maxFailedVerdicts: number | null;
  maxDurationS: number | null;
}

export interface WizardDraft {
  name: string;
  description: string;
  /** The consecutive part of the chain the campaign runs. */
  steps: CampaignStep[];
  /** The monitor after scene generation: post hoc judges each scene as a one-scene log. */
  sceneMonitor: StepMonitor;
  /** The monitor after trajectory generation: post hoc judges the planned trajectories. */
  trajectoryMonitor: StepMonitor;
  /** Catalog classes; only used when the campaign starts with scene generation. */
  scope: ScopeEntryDraft[];
  /** Uploaded scenario files and the items of earlier outputs or uploaded files. */
  input: InputDraft;
  domain: DomainDraft;
  trajectories: TrajectoriesDraft;
  runs: RunDraft[];
  resources: ResourcesDraft;
  policy: PolicyDraft;
}

/** The queue depth stages and the config's defaults (`QueueDepthCaps`). */
export const QUEUE_DEPTH_DEFAULTS: Record<string, number> = {
  generate_scene: 16,
  generate_trajectories: 16,
  simulate: 32,
  monitor: 32,
  calibrate: 8,
};

export const QUEUE_DEPTH_LABELS: Record<string, string> = {
  generate_scene: "Scene generation",
  generate_trajectories: "Trajectory generation",
  simulate: "Simulation",
  monitor: "Monitoring",
  calibrate: "Calibration",
};

export const DEFAULT_SCENE_GENERATION_TIMEOUT_S = 60;
export const DEFAULT_TRAJECTORY_TIMEOUT_S = 1800;
export const DEFAULT_CAMPAIGN_SEED = 0;

let idCounter = 0;

/** An id for a list entry of the draft (stable while the entry exists). */
export function newEntryId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

export function emptyScopeEntry(): ScopeEntryDraft {
  return { id: newEntryId("scope"), classes: [], patterns: [], quota: 1, failureBudget: 0 };
}

export function emptyRun(stackId = "", monitor = "post_hoc"): RunDraft {
  return {
    id: newEntryId("run"),
    name: "",
    stackId,
    monitor,
    earlyStop: false,
    seed: null,
    repeats: 1,
    stackParameters: {},
    groups: {},
    windVector: null,
    waves: null,
  };
}

export function emptyDraft(): WizardDraft {
  return {
    name: "",
    description: "",
    steps: [...CHAIN],
    sceneMonitor: "empty",
    trajectoryMonitor: "empty",
    scope: [emptyScopeEntry()],
    input: { scenarios: [], items: [] },
    domain: {
      custom: false,
      colregsConstants: "",
      vesselTypes: "",
      obstacleTypes: "",
      sceneGenerationTimeoutS: DEFAULT_SCENE_GENERATION_TIMEOUT_S,
      enforceLowTcpa: false,
    },
    trajectories: { generator: "monitor_driven_rrt", parameters: {}, timeoutS: DEFAULT_TRAJECTORY_TIMEOUT_S },
    runs: [emptyRun()],
    resources: { fullUsage: true, nodes: [], labels: [], queueDepth: { ...QUEUE_DEPTH_DEFAULTS }, priority: 0 },
    policy: { retention: "all", keepFrames: false, seed: DEFAULT_CAMPAIGN_SEED, maxCases: null, maxFailedVerdicts: null, maxDurationS: null },
  };
}

export interface WizardState {
  step: WizardStepId;
  draft: WizardDraft;
  /** Steps the operator has left at least once (they show their problems in the stepper). */
  visited: WizardStepId[];
  setStep: (step: WizardStepId) => void;
  /** Applies a change to the draft; the function gets a copy it may change in place. */
  update: (change: (draft: WizardDraft) => void) => void;
  /** Starts over from another draft (a preset): the first page, nothing visited yet. */
  replaceDraft: (draft: WizardDraft) => void;
  reset: () => void;
}

export const WIZARD_STORAGE_KEY = "scenegems:campaign-wizard";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** The persisted draft with every section present (a draft stored by an older build may lack newer fields). */
export function normalizeDraft(stored: unknown): WizardDraft {
  const base = emptyDraft();
  if (!stored || typeof stored !== "object") {
    return base;
  }
  const draft = stored as Partial<WizardDraft>;
  return {
    name: typeof draft.name === "string" ? draft.name : base.name,
    description: typeof draft.description === "string" ? draft.description : base.description,
    // A draft saved before Phase 6 has no steps: it was the full chain
    steps: Array.isArray(draft.steps) ? normalizeSteps(draft.steps) : base.steps,
    sceneMonitor: draft.sceneMonitor === "post_hoc" ? "post_hoc" : "empty",
    trajectoryMonitor: draft.trajectoryMonitor === "post_hoc" ? "post_hoc" : "empty",
    scope: Array.isArray(draft.scope) && draft.scope.length > 0 ? draft.scope : base.scope,
    input: {
      scenarios: Array.isArray(draft.input?.scenarios) ? draft.input.scenarios : base.input.scenarios,
      items: Array.isArray(draft.input?.items) ? draft.input.items : base.input.items,
    },
    domain: { ...base.domain, ...(draft.domain ?? {}) },
    trajectories: { ...base.trajectories, ...(draft.trajectories ?? {}) },
    runs: Array.isArray(draft.runs) && draft.runs.length > 0 ? draft.runs.map((run) => ({ ...emptyRun(), ...run })) : base.runs,
    resources: {
      ...base.resources,
      ...(draft.resources ?? {}),
      queueDepth: { ...base.resources.queueDepth, ...(draft.resources?.queueDepth ?? {}) },
    },
    policy: { ...base.policy, ...(draft.policy ?? {}) },
  };
}

/** The step id a build before Phase 6 stored for the scope page is the input page now. */
const LEGACY_STEP_IDS: Record<string, WizardStepId> = { scope: "input" };

function knownStep(value: unknown): WizardStepId | null {
  if (typeof value !== "string") {
    return null;
  }
  const mapped = LEGACY_STEP_IDS[value] ?? value;
  return WIZARD_STEPS.includes(mapped as WizardStepId) ? (mapped as WizardStepId) : null;
}

export interface StoredWizard {
  /** Null when the stored step is not one this build knows. */
  step: WizardStepId | null;
  draft: WizardDraft;
  visited: WizardStepId[];
}

/**
 * A stored wizard (version 1: the scope page and no steps, the full chain implied; version 2: this
 * shape) as the current one: legacy step ids renamed, unknown ones dropped, the draft with every
 * field present. The scope page of a version 1 draft is the input page now and its new first page is
 * not marked as visited, so the stepper does not report what the operator never saw.
 */
export function migrateStoredWizard(stored: unknown): StoredWizard {
  const state = (stored && typeof stored === "object" ? stored : {}) as { step?: unknown; draft?: unknown; visited?: unknown };
  const visited = Array.isArray(state.visited) ? state.visited.map(knownStep).filter((step): step is WizardStepId => step !== null) : [];
  return { step: knownStep(state.step), draft: normalizeDraft(state.draft), visited: [...new Set(visited)] };
}

/** The wizard store, kept per browser. Tests pass an in-memory storage. */
export function createWizardStore(storage?: StateStorage) {
  return create<WizardState>()(
    persist(
      (set) => ({
        step: "steps",
        draft: emptyDraft(),
        visited: [],
        setStep: (step) =>
          set((state) => ({ step, visited: state.visited.includes(state.step) ? state.visited : [...state.visited, state.step] })),
        update: (change) =>
          set((state) => {
            const draft = clone(state.draft);
            change(draft);
            return { draft };
          }),
        replaceDraft: (draft) => set({ step: "steps", draft: clone(draft), visited: [] }),
        reset: () => set({ step: "steps", draft: emptyDraft(), visited: [] }),
      }),
      {
        name: WIZARD_STORAGE_KEY,
        version: 2,
        storage: createJSONStorage(() => storage ?? localStorage),
        partialize: (state) => ({ step: state.step, draft: state.draft, visited: state.visited }),
        migrate: (stored) => {
          const migrated = migrateStoredWizard(stored);
          return { step: migrated.step ?? "steps", draft: migrated.draft, visited: migrated.visited };
        },
        merge: (persisted, current) => {
          const stored = migrateStoredWizard(persisted);
          return { ...current, step: stored.step ?? current.step, draft: stored.draft, visited: stored.visited };
        },
      }
    )
  );
}

export const useWizardStore = createWizardStore();
