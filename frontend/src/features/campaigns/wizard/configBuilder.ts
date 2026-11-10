import { Document, isSeq, visit, type YAMLSeq } from "yaml";
import type { CatalogGenerator, CatalogParameter, CatalogStack, ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import { fullUsageQueueDepth, KINEMATIC_JOB, simulationJobType } from "../resourcePlan";
import { activeStages, firstStep, normalizeSteps, runsStep } from "./stepPlan";
import { QUEUE_DEPTH_DEFAULTS, type InputItemDraft, type ParamValues, type RunDraft, type ScenarioFileDraft, type ScopeEntryDraft, type WizardDraft } from "./wizardState";

/**
 * The wizard's draft as a campaign config (`campaign_config.CampaignConfig`): an object in the
 * config's key order, and the YAML text of it. Only what the operator set is written, plus the
 * fields the exit campaign states explicitly (repeats, monitor, priority, retention, seed);
 * everything else keeps the config model's defaults on the master.
 */

export type ConfigObject = Record<string, unknown>;

/** The catalog parts the builder needs. */
export interface BuilderCatalog {
  stacks: readonly CatalogStack[];
  generators: readonly CatalogGenerator[];
  /** Slots per job type of the nodes that can take the campaign's jobs, for full usage's queue caps; absent while the nodes are not known. */
  slots?: Readonly<Record<string, number>>;
}

export const CONFIG_FORMAT = 3;

/** The media type the master assumes for a reference that states none. */
const DEFAULT_MEDIA_TYPE = "application/json";

export function isSet(value: unknown): boolean {
  return value !== undefined && value !== null && value !== "";
}

function put(target: ConfigObject, key: string, value: unknown): void {
  if (isSet(value)) {
    target[key] = value;
  }
}

/** The values of a parameter set that are given (non-empty), in the order of the catalog's parameters, then any others. */
function givenValues(values: ParamValues, parameters: readonly CatalogParameter[]): ConfigObject {
  const result: ConfigObject = {};
  const known = new Set(parameters.map((parameter) => parameter.key));
  for (const parameter of parameters) {
    const value = values[parameter.key];
    if (isSet(value) && !(isMapValue(value) && Object.keys(value).length === 0)) {
      result[parameter.key] = value;
    }
  }
  for (const [key, value] of Object.entries(values)) {
    if (!known.has(key) && isSet(value)) {
      result[key] = value;
    }
  }
  return result;
}

function isMapValue(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function findStack(catalog: BuilderCatalog, stackId: string): CatalogStack | undefined {
  return catalog.stacks.find((stack) => stack.id === stackId);
}

export function findGenerator(catalog: BuilderCatalog, generatorId: string): CatalogGenerator | undefined {
  return catalog.generators.find((generator) => generator.id === generatorId);
}

function normalizeNewlines(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** Whether a stack lets a run set the wind or the waves (`environment` support is not `unsupported`). */
export function supportsEnvironment(stack: CatalogStack | undefined): { wind: boolean; waves: boolean } {
  return {
    wind: stack !== undefined && stack.environment.wind !== "unsupported",
    waves: stack !== undefined && stack.environment.waves !== "unsupported",
  };
}

/** A scope entry that names nothing: ignored when the campaign has scenario files to start from, reported otherwise. */
export function isEmptyScopeEntry(entry: ScopeEntryDraft): boolean {
  return entry.classes.length === 0 && entry.patterns.length === 0;
}

function buildScope(draft: WizardDraft): ConfigObject[] {
  const entries = draft.input.scenarios.length > 0 ? draft.scope.filter((entry) => !isEmptyScopeEntry(entry)) : draft.scope;
  return entries.map((entry) => {
    const item: ConfigObject = {};
    if (entry.classes.length > 0) {
      item.fecs = [...entry.classes];
    }
    if (entry.patterns.length > 0) {
      item.patterns = [...entry.patterns];
    }
    put(item, "quota", entry.quota);
    put(item, "failure_budget", entry.failureBudget);
    return item;
  });
}

function buildRef(ref: ConfigArtifactRef): ConfigObject {
  const result: ConfigObject = { sha256: ref.sha256 };
  put(result, "size_bytes", ref.size_bytes);
  result.kind = ref.kind;
  if (isSet(ref.media_type) && ref.media_type !== DEFAULT_MEDIA_TYPE) {
    result.media_type = ref.media_type;
  }
  put(result, "pointer", ref.pointer);
  return result;
}

function buildScenario(scenario: ScenarioFileDraft): ConfigObject {
  const result: ConfigObject = { name: scenario.name.trim(), ref: buildRef(scenario.ref) };
  put(result, "quota", scenario.quota);
  put(result, "failure_budget", scenario.failureBudget);
  return result;
}

function buildItem(item: InputItemDraft): ConfigObject {
  return { name: item.name.trim(), ref: buildRef(item.ref), source: { ...item.source } };
}

/**
 * The design space exploration section: the specification inline, the scope, the search's limits
 * (`max_fecs` null for every FEC) and what each explored FEC needs when later steps run.
 */
function buildExploration(draft: WizardDraft): ConfigObject {
  const exploration = draft.exploration;
  // An empty specification is left out: the master then explores its default (a preset may name none)
  const section: ConfigObject = {};
  if (exploration.specification.trim().length > 0) {
    section.specification = normalizeNewlines(exploration.specification);
  }
  section.scope = exploration.scope.trim();
  section.max_fecs = exploration.maxFecs;
  put(section, "timeout_s", exploration.timeoutS);
  put(section, "quota", exploration.quota);
  put(section, "failure_budget", exploration.failureBudget);
  return section;
}

/**
 * The input section: scenario files for a campaign that starts with scene generation, items for one
 * that starts later, none for one that starts with the design space exploration (its FECs come from it).
 */
function buildInput(draft: WizardDraft): ConfigObject {
  const input: ConfigObject = {};
  if (firstStep(draft.steps) === "design_space_exploration") {
    return input;
  }
  if (firstStep(draft.steps) === "scene_generation") {
    if (draft.input.scenarios.length > 0) {
      input.functional_scenarios = draft.input.scenarios.map(buildScenario);
    }
  } else if (draft.input.items.length > 0) {
    input.items = draft.input.items.map(buildItem);
  }
  return input;
}

function buildDomain(draft: WizardDraft): ConfigObject {
  const domain: ConfigObject = {};
  if (draft.domain.custom) {
    domain.colregs_constants = normalizeNewlines(draft.domain.colregsConstants);
    domain.vessel_types = normalizeNewlines(draft.domain.vesselTypes);
    domain.obstacle_types = normalizeNewlines(draft.domain.obstacleTypes);
  }
  if (runsStep(draft.steps, "scene_generation")) {
    put(domain, "scene_generation_timeout_s", draft.domain.sceneGenerationTimeoutS);
    domain.enforce_low_tcpa = draft.domain.enforceLowTcpa;
  }
  return domain;
}

function buildTrajectories(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const trajectories: ConfigObject = { generator: draft.trajectories.generator };
  const generator = findGenerator(catalog, draft.trajectories.generator);
  const parameters = generator?.parameters ?? [];
  const given = givenValues(draft.trajectories.parameters, parameters);
  if (generator?.params_field) {
    if (Object.keys(given).length > 0) {
      trajectories[generator.params_field] = given;
    }
  } else {
    Object.assign(trajectories, given);
  }
  put(trajectories, "timeout_s", draft.trajectories.timeoutS);
  if (draft.trajectoryMonitor === "post_hoc") {
    trajectories.monitor = "post_hoc";
  }
  return trajectories;
}

/** A run's stack section: the fields that pick the catalog option (its stack_section), then the given parameters and groups. */
function buildStack(run: RunDraft, stack: CatalogStack | undefined): ConfigObject {
  const result: ConfigObject = stack ? { ...(stack.stack_section ?? { simulation_layer: stack.simulation_layer, mode: stack.mode }) } : { simulation_layer: "kinematic" };
  Object.assign(result, givenValues(run.stackParameters, stack?.parameters ?? []));
  for (const group of stack?.groups ?? []) {
    const values = run.groups[group.key];
    if (values !== undefined) {
      result[group.key] = givenValues(values, group.parameters);
    }
  }
  return result;
}

function buildRun(run: RunDraft, catalog: BuilderCatalog): ConfigObject {
  const stack = findStack(catalog, run.stackId);
  const result: ConfigObject = {};
  put(result, "name", run.name.trim());
  result.stack = buildStack(run, stack);
  const environment: ConfigObject = {};
  const support = supportsEnvironment(stack);
  if (support.wind && run.windVector && run.windVector.length === 3) {
    environment.wind_vector = [...run.windVector];
  }
  if (support.waves && run.waves) {
    environment.waves = { ...run.waves };
  }
  if (Object.keys(environment).length > 0) {
    result.environment = environment;
  }
  put(result, "seed", run.seed);
  result.repeats = run.repeats ?? 1;
  result.monitor = run.monitor;
  if (run.earlyStop) {
    result.early_stop = true;
  }
  return result;
}

/** The labels every job needs, as the config writes them (named ones only). */
export function requiredLabelsOf(draft: WizardDraft): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const { key, value } of draft.resources.labels) {
    if (key.trim()) {
      labels[key.trim()] = value;
    }
  }
  return labels;
}

/** The queue caps the config gets: full usage's from the cluster's slots, else the operator's. */
export function effectiveQueueDepth(draft: WizardDraft, catalog: BuilderCatalog): Record<string, number | null> {
  if (!draft.resources.fullUsage) {
    return draft.resources.queueDepth;
  }
  const layers = draft.runs.map((run) => findStack(catalog, run.stackId)?.simulation_layer);
  const simulators = [...new Set(layers.map((layer) => simulationJobType({ simulation_layer: layer })))];
  return fullUsageQueueDepth(catalog.slots ?? {}, simulators.length > 0 ? simulators : [KINEMATIC_JOB]);
}

/** The queue stages the campaign's cases pass through (the others get no cap in the config). */
export function stagesOf(draft: WizardDraft): string[] {
  const simulates = runsStep(draft.steps, "simulation");
  const stages = activeStages(draft.steps, {
    scene: draft.sceneMonitor === "post_hoc",
    trajectories: draft.trajectoryMonitor === "post_hoc",
    simulation: simulates && draft.runs.some((run) => run.monitor === "post_hoc"),
  });
  if (simulates && draft.runs.some((run) => (run.repeats ?? 1) > 1)) {
    stages.push("calibrate");
  }
  return stages;
}

function buildResources(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const resources: ConfigObject = {};
  if (!draft.resources.fullUsage && draft.resources.nodes.length > 0) {
    resources.nodes = [...draft.resources.nodes].sort();
  }
  const labels = requiredLabelsOf(draft);
  if (Object.keys(labels).length > 0) {
    resources.required_labels = labels;
  }
  const queueDepth: Record<string, number> = {};
  const depths = effectiveQueueDepth(draft, catalog);
  const used = new Set(stagesOf(draft));
  for (const [stage, defaultDepth] of Object.entries(QUEUE_DEPTH_DEFAULTS)) {
    const depth = depths[stage];
    if (!used.has(stage)) {
      continue;
    }
    if (depth !== null && depth !== undefined && depth !== defaultDepth) {
      queueDepth[stage] = depth;
    }
  }
  if (Object.keys(queueDepth).length > 0) {
    resources.queue_depth = queueDepth;
  }
  resources.priority = draft.resources.priority ?? 0;
  return resources;
}

function buildPolicy(draft: WizardDraft): ConfigObject {
  const policy: ConfigObject = {
    retention: draft.policy.retention,
    keep_frames: draft.policy.keepFrames,
    seed: draft.policy.seed ?? 0,
  };
  const stop: ConfigObject = {};
  put(stop, "max_cases", draft.policy.maxCases);
  put(stop, "max_failed_verdicts", draft.policy.maxFailedVerdicts);
  put(stop, "max_duration_s", draft.policy.maxDurationS);
  if (Object.keys(stop).length > 0) {
    policy.stop = stop;
  }
  return policy;
}

/**
 * The config the draft describes (format 3: a scope entry lists its FECs under `fecs`). Sections of steps the campaign does not run are left out,
 * and the scope only goes in when the campaign starts with scene generation (one that starts with the design space exploration has
 * neither scope nor input). A run with an unknown
 * stack gets the layer only; `checkDraft` reports it.
 */
export function buildCampaignConfig(draft: WizardDraft, catalog: BuilderCatalog): ConfigObject {
  const steps = normalizeSteps(draft.steps);
  const plan = { ...draft, steps };
  const config: ConfigObject = { format: CONFIG_FORMAT, name: draft.name.trim() };
  put(config, "description", draft.description.trim());
  config.steps = [...steps];
  if (firstStep(steps) === "scene_generation") {
    const scope = buildScope(plan);
    if (scope.length > 0) {
      config.scope = scope;
    }
  }
  const input = buildInput(plan);
  if (Object.keys(input).length > 0) {
    config.input = input;
  }
  if (runsStep(steps, "design_space_exploration")) {
    config.design_space_exploration = buildExploration(plan);
  }
  const domain = buildDomain(plan);
  if (Object.keys(domain).length > 0) {
    config.domain = domain;
  }
  if (runsStep(steps, "scene_generation") && draft.sceneMonitor === "post_hoc") {
    config.scene_generation = { monitor: "post_hoc" };
  }
  if (runsStep(steps, "trajectory_generation")) {
    config.trajectories = buildTrajectories(plan, catalog);
  }
  if (runsStep(steps, "simulation")) {
    config.execution = { runs: draft.runs.map((run) => buildRun(run, catalog)) };
  }
  config.resources = buildResources(plan, catalog);
  config.policy = buildPolicy(plan);
  return config;
}

/** The YAML text of a config: lists of numbers inline, long text as block scalars, nothing folded. */
export function configToYaml(config: ConfigObject): string {
  const document = new Document(config);
  visit(document, {
    Seq(_key, seq: YAMLSeq) {
      if (seq.items.length > 0 && seq.items.every((item) => !isSeq(item) && typeof (item as { value?: unknown }).value === "number")) {
        seq.flow = true;
      }
    },
  });
  return document.toString({ lineWidth: 0, indent: 2, flowCollectionPadding: false });
}

export function buildCampaignYaml(draft: WizardDraft, catalog: BuilderCatalog): string {
  return configToYaml(buildCampaignConfig(draft, catalog));
}
