import { buildCampaignConfig, findGenerator, type BuilderCatalog, type ConfigObject } from "./configBuilder";
import { normalizeNewlines } from "../../../domain/cluster/presetsApi";
import { IMPLIED_STEPS } from "../../../domain/cluster/schemas";
import { DEFAULT_EXPLORATION_QUOTA, DEFAULT_EXPLORATION_TIMEOUT_S, DEFAULT_MAX_FECS, designSpaceSectionOf } from "../../../domain/designSpace/designSpaceConfig";
import { normalizeSteps } from "./stepPlan";
import {
  DEFAULT_CAMPAIGN_SEED,
  DEFAULT_SCENE_GENERATION_TIMEOUT_S,
  DEFAULT_TRAJECTORY_TIMEOUT_S,
  emptyDraft,
  emptyExploration,
  emptyRun,
  emptyScopeEntry,
  newEntryId,
  QUEUE_DEPTH_DEFAULTS,
  UNLIMITED_FAILURE_BUDGET,
  type FailureBudgetDraft,
  type ParamValues,
  type RetentionPolicy,
  type RunDraft,
  type ScopeEntryDraft,
  type WizardDraft,
} from "./wizardState";

/**
 * Campaign presets in the wizard: a preset's config becomes a draft to adjust (the inverse of
 * `configBuilder.ts`), and the draft becomes a preset's config. A preset has no input section, so
 * the draft starts without input and saving leaves out the uploaded files and picked outputs: they
 * belong to one campaign.
 */

function record(value: unknown): ConfigObject {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as ConfigObject) : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === "string");
}

function numberOr<T>(value: unknown, fallback: T): number | T {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function failureBudgetOf(value: unknown): FailureBudgetDraft {
  return value === UNLIMITED_FAILURE_BUDGET ? UNLIMITED_FAILURE_BUDGET : numberOr(value, 0);
}

function scopeOf(config: ConfigObject): ScopeEntryDraft[] {
  const entries = list(config.scope).map((item) => {
    const entry = record(item);
    return {
      id: newEntryId("scope"),
      // Format 3 lists an entry's FECs under fecs, a preset saved in format 2 under classes
      classes: strings(entry.fecs ?? entry.classes),
      patterns: strings(entry.patterns),
      quota: numberOr(entry.quota, null),
      failureBudget: failureBudgetOf(entry.failure_budget),
    };
  });
  return entries.length > 0 ? entries : [emptyScopeEntry()];
}

const DOMAIN_TEXT_KEYS = ["colregs_constants", "vessel_types", "obstacle_types"] as const;

function domainOf(config: ConfigObject): WizardDraft["domain"] {
  const domain = record(config.domain);
  const text = (key: (typeof DOMAIN_TEXT_KEYS)[number]) => (typeof domain[key] === "string" ? (domain[key] as string) : "");
  return {
    // A preset that states its own domain content keeps it; one that leaves it out uses the cluster's
    custom: DOMAIN_TEXT_KEYS.some((key) => typeof domain[key] === "string"),
    colregsConstants: text("colregs_constants"),
    vesselTypes: text("vessel_types"),
    obstacleTypes: text("obstacle_types"),
    sceneGenerationTimeoutS: numberOr(domain.scene_generation_timeout_s, DEFAULT_SCENE_GENERATION_TIMEOUT_S),
    enforceLowTcpa: domain.enforce_low_tcpa === true,
  };
}

/** The design space exploration section; a config without one keeps the draft's defaults. */
function explorationOf(config: ConfigObject): WizardDraft["exploration"] {
  const section = designSpaceSectionOf(config);
  if (section === null) {
    return emptyExploration();
  }
  return {
    specification: section.specification,
    specificationLabel: null,
    scope: section.scope,
    maxFecs: section.max_fecs === undefined ? DEFAULT_MAX_FECS : section.max_fecs,
    timeoutS: section.timeout_s ?? DEFAULT_EXPLORATION_TIMEOUT_S,
    quota: section.quota ?? DEFAULT_EXPLORATION_QUOTA,
    failureBudget: failureBudgetOf(section.failure_budget),
  };
}

const TRAJECTORY_FIELDS = new Set(["generator", "timeout_s", "monitor"]);

function trajectoriesOf(config: ConfigObject, catalog: BuilderCatalog): WizardDraft["trajectories"] {
  const trajectories = record(config.trajectories);
  const generator = typeof trajectories.generator === "string" ? trajectories.generator : "monitor_driven_rrt";
  const spec = findGenerator(catalog, generator);
  const parameters: ParamValues = spec?.params_field
    ? { ...record(trajectories[spec.params_field]) }
    : Object.fromEntries(Object.entries(trajectories).filter(([key]) => !TRAJECTORY_FIELDS.has(key)));
  return { generator, parameters, timeoutS: numberOr(trajectories.timeout_s, DEFAULT_TRAJECTORY_TIMEOUT_S) };
}

/**
 * The catalog stack a run's stack section names, or "" when the control node offers none: its layer and
 * mode (kinematic replay when it names none), and its control layer when it names one. A section
 * without a control layer is the option whose own section names none (the layer's implied one).
 */
export function stackIdOf(stack: ConfigObject, catalog: BuilderCatalog): string {
  const layer = typeof stack.simulation_layer === "string" ? stack.simulation_layer : "kinematic";
  const mode = typeof stack.mode === "string" ? stack.mode : "replay";
  const control = typeof stack.control_layer === "string" ? stack.control_layer : undefined;
  const matches = (entry: BuilderCatalog["stacks"][number]) =>
    control === undefined ? entry.stack_section?.control_layer === undefined : (entry.stack_section?.control_layer ?? entry.control_layer) === control;
  return catalog.stacks.find((entry) => entry.simulation_layer === layer && entry.mode === mode && matches(entry))?.id ?? "";
}

function runOf(item: unknown, catalog: BuilderCatalog): RunDraft {
  const run = record(item);
  const stack = record(run.stack);
  const stackId = stackIdOf(stack, catalog);
  const spec = catalog.stacks.find((entry) => entry.id === stackId);
  const stackParameters: ParamValues = {};
  for (const parameter of spec?.parameters ?? []) {
    if (stack[parameter.key] !== undefined) {
      stackParameters[parameter.key] = stack[parameter.key];
    }
  }
  const groups: Record<string, ParamValues> = {};
  for (const group of spec?.groups ?? []) {
    if (stack[group.key] !== undefined) {
      groups[group.key] = { ...record(stack[group.key]) };
    }
  }
  const environment = record(run.environment);
  const wind = list(environment.wind_vector);
  return {
    ...emptyRun(stackId, typeof run.monitor === "string" ? run.monitor : "post_hoc"),
    name: typeof run.name === "string" ? run.name : "",
    earlyStop: run.early_stop === true,
    seed: numberOr(run.seed, null),
    repeats: numberOr(run.repeats, 1),
    stackParameters,
    groups,
    windVector: wind.length === 3 && wind.every((value) => typeof value === "number") ? (wind as number[]) : null,
    waves: Object.keys(record(environment.waves)).length > 0 ? { ...record(environment.waves) } : null,
  };
}

function resourcesOf(config: ConfigObject): WizardDraft["resources"] {
  const resources = record(config.resources);
  const workerNodes = strings(resources.worker_nodes);
  const queueDepth = record(resources.queue_depth);
  return {
    // A preset that names neither worker nodes nor queue caps uses every worker node with caps sized to their slots
    fullUsage: workerNodes.length === 0 && Object.keys(queueDepth).length === 0,
    workerNodes,
    labels: Object.entries(record(resources.required_labels)).map(([key, value]) => ({ key, value: String(value) })),
    queueDepth: Object.fromEntries(Object.entries(QUEUE_DEPTH_DEFAULTS).map(([stage, depth]) => [stage, numberOr(queueDepth[stage], depth)])),
    priority: numberOr(resources.priority, 0),
  };
}

const RETENTIONS: readonly RetentionPolicy[] = ["all", "failures", "verdicts_only"];

function policyOf(config: ConfigObject): WizardDraft["policy"] {
  const policy = record(config.policy);
  const stop = record(policy.stop);
  return {
    retention: RETENTIONS.includes(policy.retention as RetentionPolicy) ? (policy.retention as RetentionPolicy) : "all",
    keepFrames: policy.keep_frames === true,
    seed: numberOr(policy.seed, DEFAULT_CAMPAIGN_SEED),
    maxCases: numberOr(stop.max_cases, null),
    maxFailedVerdicts: numberOr(stop.max_failed_verdicts, null),
    maxDurationS: numberOr(stop.max_duration_s, null),
  };
}

/** The draft a preset's config describes. Runs need the stack catalog to find their stack; a stack the control node does not offer leaves the run without one. */
export function draftFromConfig(source: Record<string, unknown>, catalog: BuilderCatalog): WizardDraft {
  const config = record(source);
  const steps = Array.isArray(config.steps) ? normalizeSteps(config.steps) : [...IMPLIED_STEPS];
  const runs = list(record(config.execution).runs).map((item) => runOf(item, catalog));
  return {
    ...emptyDraft(),
    name: typeof config.name === "string" ? config.name : "",
    description: typeof config.description === "string" ? config.description : "",
    steps,
    sceneMonitor: record(config.scene_generation).monitor === "post_hoc" ? "post_hoc" : "empty",
    trajectoryMonitor: record(config.trajectories).monitor === "post_hoc" ? "post_hoc" : "empty",
    scope: scopeOf(config),
    exploration: explorationOf(config),
    domain: domainOf(config),
    trajectories: trajectoriesOf(config, catalog),
    runs: runs.length > 0 ? runs : [emptyRun()],
    resources: resourcesOf(config),
    policy: policyOf(config),
  };
}

/**
 * The draft as a preset's config: the campaign config without its input, and with full usage left
 * as it is meant (no queue caps sized to this cluster's slots), so the preset fits any cluster.
 */
export function presetConfigOf(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const { input: _input, ...config } = buildCampaignConfig(draft, { ...catalog, slots: undefined });
  void _input;
  return config;
}

/**
 * A draft whose design space exploration names no specification (a preset that leaves it to the control node)
 * starts from the control node's default, so the wizard shows and sends what will run; without a default the
 * editor stays empty and the exploration page reports it.
 */
export function withDefaultSpecification(draft: WizardDraft, shipped: { specification: string } | null | undefined, label: string): WizardDraft {
  if (!draft.steps.includes("design_space_exploration") || draft.exploration.specification.trim() !== "" || !shipped) {
    return draft;
  }
  return { ...draft, exploration: { ...draft.exploration, specification: normalizeNewlines(shipped.specification), specificationLabel: label } };
}

/** Whether the draft holds entries a preset would replace (the operator is asked first): a name, a description, classes, input or an explored specification. */
export function draftHasEntries(draft: WizardDraft): boolean {
  return (
    draft.name.trim() !== "" ||
    draft.description.trim() !== "" ||
    draft.scope.some((entry) => entry.classes.length > 0 || entry.patterns.length > 0) ||
    draft.input.scenarios.length > 0 ||
    draft.input.items.length > 0 ||
    (draft.steps.includes("design_space_exploration") && draft.exploration.specification.trim() !== "")
  );
}
