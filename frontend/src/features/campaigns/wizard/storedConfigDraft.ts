import { configArtifactRefSchema, inputItemSourceSchema } from "../../../domain/cluster/campaignApi";
import { normalizeNewlines, type DomainTexts } from "../../../domain/cluster/presetsApi";
import type { BuilderCatalog, ConfigObject } from "./configBuilder";
import { draftFromConfig } from "./presetDraft";
import { runsStep } from "./stepPlan";
import { newEntryId, UNLIMITED_FAILURE_BUDGET, type FailureBudgetDraft, type InputDraft, type InputItemDraft, type ScenarioFileDraft, type WizardDraft } from "./wizardState";

/**
 * The config of a campaign in Campaign History as a draft of the wizard, to run it again or adjust
 * it first. The control node stores a config with every default filled in (`CampaignConfig.to_json`),
 * so what a preset leaves out is there as null, as an empty map or as the default: those are read as
 * not set, and the draft builds the config the operator would have written. Unlike a preset, a
 * stored config has its input, which the draft keeps: the control node holds the files of a campaign
 * for as long as an entry uses them.
 */

function record(value: unknown): ConfigObject {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as ConfigObject) : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function isEmptyMap(value: unknown): boolean {
  return typeof value === "object" && value !== null && !Array.isArray(value) && Object.keys(value).length === 0;
}

/** The entries of a section that say something: null is the stored form of a field that was not given. */
function given(section: ConfigObject, alsoDrop: (value: unknown) => boolean = () => false): ConfigObject {
  return Object.fromEntries(Object.entries(section).filter(([, value]) => value !== null && value !== undefined && !alsoDrop(value)));
}

/** A run as it was written: the stack without the fields nobody set, and no wind when it is the calm default. */
function writtenRun(item: unknown): ConfigObject {
  const run = record(item);
  const environment = given(record(run.environment));
  const wind = list(environment.wind_vector);
  if (wind.every((value) => value === 0)) {
    delete environment.wind_vector;
  }
  return { ...run, stack: given(record(run.stack)), environment };
}

/** The stored config with the trajectory and run sections as they were written (the other sections read their defaults themselves). */
function writtenConfig(config: ConfigObject): ConfigObject {
  const result: ConfigObject = { ...config };
  if (config.trajectories !== undefined) {
    // A generator without a parameter section of its own stores the other generators' empty one
    result.trajectories = given(record(config.trajectories), isEmptyMap);
  }
  if (config.execution !== undefined) {
    result.execution = { ...record(config.execution), runs: list(record(config.execution).runs).map(writtenRun) };
  }
  return result;
}

function failureBudgetOf(value: unknown): FailureBudgetDraft {
  return value === UNLIMITED_FAILURE_BUDGET ? UNLIMITED_FAILURE_BUDGET : typeof value === "number" ? value : 0;
}

function scenarioOf(item: unknown): ScenarioFileDraft | null {
  const scenario = record(item);
  const ref = configArtifactRefSchema.safeParse(scenario.ref);
  if (typeof scenario.name !== "string" || !ref.success) {
    return null;
  }
  return {
    id: newEntryId("scenario"),
    // The config does not keep the name of the file the scenario was uploaded as
    fileName: scenario.name,
    name: scenario.name,
    ref: ref.data,
    quota: typeof scenario.quota === "number" ? scenario.quota : 1,
    failureBudget: failureBudgetOf(scenario.failure_budget),
    uploadedAt: null,
  };
}

function itemOf(item: unknown): InputItemDraft | null {
  const entry = record(item);
  const ref = configArtifactRefSchema.safeParse(entry.ref);
  // The stored source holds both shapes, the one that does not apply as nulls
  const source = inputItemSourceSchema.safeParse(given(record(entry.source)));
  if (typeof entry.name !== "string" || !ref.success || !source.success) {
    return null;
  }
  return { id: newEntryId("item"), name: entry.name, ref: ref.data, source: source.data, uploadedAt: null };
}

function present<T>(value: T | null): value is T {
  return value !== null;
}

function inputOf(config: ConfigObject): InputDraft {
  const input = record(config.input);
  return {
    scenarios: list(input.functional_scenarios).map(scenarioOf).filter(present),
    items: list(input.items).map(itemOf).filter(present),
  };
}

const DOMAIN_FIELDS = [
  ["colregs_constants", "colregsConstants"],
  ["vessel_types", "vesselTypes"],
  ["obstacle_types", "obstacleTypes"],
] as const;

/**
 * The domain contents of a stored config. The control node writes the cluster's domain configuration into a
 * config that states none, so contents equal to the cluster's are read as "use the cluster's" and
 * only contents that differ stay the campaign's own.
 */
function domainOf(domain: WizardDraft["domain"], clusterDomain: DomainTexts | null | undefined): WizardDraft["domain"] {
  if (!domain.custom || !clusterDomain) {
    return domain;
  }
  const same = DOMAIN_FIELDS.every(([stored, drafted]) => normalizeNewlines(domain[drafted]) === normalizeNewlines(clusterDomain[stored]));
  return same ? { ...domain, custom: false, colregsConstants: "", vesselTypes: "", obstacleTypes: "" } : domain;
}

export interface StoredConfigContext {
  /** The cluster's domain configuration as it is now; without it the stored contents stay the campaign's own. */
  clusterDomain?: DomainTexts | null;
}

/**
 * What a stored config says about where its jobs run that the wizard does not take over: a new
 * campaign uses every machine, with its queue caps sized to the cluster as it is then.
 */
export function namedAllocation(source: Record<string, unknown>): string[] {
  const resources = record(record(source).resources);
  const named: string[] = [];
  const workerNodes = Array.isArray(resources.worker_nodes) ? resources.worker_nodes.length : 0;
  if (workerNodes > 0) {
    named.push(workerNodes === 1 ? "one chosen machine" : `${workerNodes} chosen machines`);
  }
  if (Object.keys(record(resources.required_labels)).length > 0) {
    named.push("machine labels");
  }
  if (typeof resources.priority === "number" && resources.priority !== 0) {
    named.push(`priority ${resources.priority}`);
  }
  return named;
}

/**
 * The draft a stored campaign config describes, with its input. The config's resources are not
 * part of it (`namedAllocation` says what they named): the wizard sizes the queue caps to the
 * cluster again when the config is built.
 */
export function draftFromStoredConfig(source: Record<string, unknown>, catalog: BuilderCatalog, context: StoredConfigContext = {}): WizardDraft {
  const config = record(source);
  const draft = draftFromConfig(writtenConfig(config), catalog);
  return {
    ...draft,
    input: inputOf(config),
    domain: domainOf(draft.domain, context.clusterDomain),
  };
}

/** The runs of the draft whose stack this control node does not offer (they need another one before the campaign can be created). */
export function runsWithoutStack(draft: WizardDraft): number {
  return runsStep(draft.steps, "simulation") ? draft.runs.filter((run) => run.stackId === "").length : 0;
}
