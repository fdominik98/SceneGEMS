import type { CatalogClass, CatalogStack } from "../../../domain/cluster/campaignApi";
import type { CampaignPreset } from "../../../domain/cluster/presetsApi";
import { IMPLIED_STEPS, type CampaignStep } from "../../../domain/cluster/schemas";
import { plural } from "../campaignFormat";
import type { CatalogFacet, CatalogModel, CatalogValue } from "./catalogModel";
import { isEmptyScopeEntry, type BuilderCatalog } from "./configBuilder";
import { draftFromConfig } from "./presetDraft";
import { planScope } from "./scopePlan";
import { stackRank } from "./stackCatalog";
import { CAMPAIGN_STEP_LABELS, CHAIN } from "./stepPlan";

/**
 * The preset catalog. A preset states no tags: what it can be filtered by is read from its config,
 * the way loading it reads it (`draftFromConfig`), against the master's stacks and FEC catalog, so a
 * preset saved on the cluster is sorted in the same way as a shipped one.
 */

export interface PresetFacts {
  preset: CampaignPreset;
  /** The vessel and obstacle counts of the FECs its scope selects, ascending; empty until the FEC catalog is read. */
  vessels: number[];
  obstacles: number[];
  /** It has no scope: the campaign's input, picked in the wizard, says what the scenes hold. */
  fromInput: boolean;
  /** It starts with the design space exploration: its FECs come from it (no scope, no input). */
  explores: boolean;
  /** The scope it explores, when it explores. */
  exploredScope: string | null;
  /** FECs and cases of its scope; null when it has no scope or the FEC catalog is not read yet. */
  fecs: number | null;
  cases: number | null;
  /** The stacks of its runs, in catalog order; none when it does not simulate. */
  stacks: CatalogStack[];
  /** A run needs a stack the master does not offer or cannot run. */
  blocked: boolean;
}

const NO_STACKS: BuilderCatalog = { stacks: [], generators: [] };

function ascending(values: Iterable<number>): number[] {
  return [...new Set(values)].sort((a, b) => a - b);
}

/** What a preset's config says, read against the master's catalogs; while one of them loads its part stays empty. */
export function presetFacts(preset: CampaignPreset, catalog: BuilderCatalog | null, classes: readonly CatalogClass[] | undefined): PresetFacts {
  const draft = draftFromConfig(preset.config, catalog ?? NO_STACKS);
  const explores = preset.steps[0] === "design_space_exploration";
  const fromInput = !explores && draft.scope.every(isEmptyScopeEntry);
  const plan = classes && !fromInput ? planScope(draft.scope, classes) : null;
  const selected = plan?.entries.flatMap((entry) => entry.classes) ?? [];
  const runs = preset.steps.includes("simulation") ? draft.runs : [];
  const used = new Set(runs.map((run) => run.stackId));
  return {
    preset,
    vessels: ascending(selected.map((entry) => entry.vessel_count)),
    obstacles: ascending(selected.map((entry) => entry.obstacle_count)),
    fromInput,
    explores,
    exploredScope: explores ? draft.exploration.scope.trim() || null : null,
    fecs: plan?.classes ?? null,
    cases: plan?.casesPlanned ?? null,
    stacks: catalog?.stacks.filter((stack) => used.has(stack.id)) ?? [],
    blocked: catalog !== null && runs.some((run) => !catalog.stacks.some((stack) => stack.id === run.stackId && stack.available)),
  };
}

const INPUT_VALUE: CatalogValue = { value: "input", label: "Set by the input", rank: Number.MAX_SAFE_INTEGER };
const EXPLORED_VALUE: CatalogValue = { value: "explored", label: "Set by the exploration", rank: Number.MAX_SAFE_INTEGER - 1 };

function vesselValues(facts: PresetFacts): CatalogValue[] {
  if (facts.explores) {
    return [EXPLORED_VALUE];
  }
  return facts.fromInput ? [INPUT_VALUE] : facts.vessels.map((count) => ({ value: String(count), label: plural(count, "vessel"), rank: count }));
}

function obstacleValues(facts: PresetFacts): CatalogValue[] {
  if (facts.explores) {
    return [EXPLORED_VALUE];
  }
  return facts.fromInput ? [INPUT_VALUE] : facts.obstacles.map((count) => ({ value: String(count), label: count === 0 ? "No obstacles" : plural(count, "obstacle"), rank: count }));
}

function sourceValues(facts: PresetFacts): CatalogValue[] {
  return [facts.preset.builtin ? { value: "shipped", label: "Shipped with the master", rank: 0 } : { value: "saved", label: "Saved on this cluster", rank: 1 }];
}

function stackValues(facts: PresetFacts): CatalogValue[] {
  return facts.stacks.map((stack) => ({ value: stack.id, label: stack.label, rank: stackRank(stack) }));
}

function stepValues(facts: PresetFacts): CatalogValue[] {
  return facts.preset.steps.map((step) => ({ value: step, label: CAMPAIGN_STEP_LABELS[step], rank: CHAIN.indexOf(step) }));
}

/** The steps in a few words, for the grouping and the cards: the chain of scene generation to simulation is the whole chain. */
export function describeSteps(steps: readonly CampaignStep[]): string {
  const whole = IMPLIED_STEPS.every((step) => steps.includes(step));
  if (whole) {
    return steps.includes("design_space_exploration") ? "Design space exploration and the whole chain" : "Whole chain";
  }
  return steps.map((step) => CAMPAIGN_STEP_LABELS[step]).join(", ");
}

const FACETS: readonly CatalogFacet<PresetFacts>[] = [
  { key: "source", label: "Source", match: "any", values: sourceValues },
  { key: "vessels", label: "Vessels", match: "any", values: vesselValues },
  { key: "obstacles", label: "Obstacles", match: "any", values: obstacleValues },
  { key: "stack", label: "Simulation stack", match: "any", values: stackValues },
  { key: "steps", label: "Steps", match: "all", values: stepValues },
];

/** The stack group a preset's stacks do not fill: it has none to list. */
const NO_SIMULATION: CatalogValue = { value: "none", label: "No simulation", rank: Number.MAX_SAFE_INTEGER };

export const PRESET_CATALOG: CatalogModel<PresetFacts> = {
  idOf: (facts) => facts.preset.preset_id,
  textOf: (facts) => [facts.preset.name, facts.preset.description, ...FACETS.flatMap((facet) => facet.values(facts).map((entry) => entry.label))].join(" "),
  facets: FACETS,
  groupings: [
    { key: "source", label: "Source", groups: sourceValues },
    { key: "vessels", label: "Vessels", groups: vesselValues },
    { key: "stack", label: "Simulation stack", groups: (facts) => (facts.stacks.length > 0 ? stackValues(facts) : [NO_SIMULATION]) },
    {
      key: "steps",
      label: "Steps",
      // Whole chain first, then the shorter ones from the start of the chain on
      groups: (facts) => [{ value: facts.preset.steps.join(), label: describeSteps(facts.preset.steps), rank: CHAIN.indexOf(facts.preset.steps[0]) * CHAIN.length - facts.preset.steps.length }],
    },
  ],
};

/** A range of counts in words: "2 vessels", "2 to 3 vessels". */
function countRange(values: readonly number[], one: string): string {
  const first = values[0];
  const last = values[values.length - 1];
  return first === last ? plural(first, one) : `${first} to ${last} ${one}s`;
}

/** What a preset's card says about its scope, in the order the card shows it. */
export function scopeTags(facts: PresetFacts): string[] {
  if (facts.explores) {
    return [facts.exploredScope !== null ? `Explores the design space, scope ${facts.exploredScope}` : "Explores the design space"];
  }
  if (facts.fromInput) {
    return ["Input picked in the wizard"];
  }
  if (facts.vessels.length === 0) {
    return [];
  }
  const obstacles = facts.obstacles.every((count) => count === 0) ? "no obstacles" : facts.obstacles.includes(0) ? "with and without obstacles" : `with ${countRange(facts.obstacles, "obstacle")}`;
  return [`${countRange(facts.vessels, "vessel")}, ${obstacles}`, `${plural(facts.fecs ?? 0, "FEC")}, ${plural(facts.cases ?? 0, "case")}`];
}
