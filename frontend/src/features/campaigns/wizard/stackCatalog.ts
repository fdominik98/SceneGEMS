import type { CatalogStack } from "../../../domain/cluster/campaignApi";
import { COMPONENTS, componentLabel } from "../../../domain/cluster/components";
import type { CatalogFacet, CatalogModel, CatalogValue } from "./catalogModel";
import { supportsEnvironment } from "./configBuilder";

/** The stack catalog: every field it filters and groups by is one the control node reports per stack. */

function componentValue(kind: string, id: string): CatalogValue {
  const component = `${kind}/${id}`;
  const rank = (COMPONENTS as readonly string[]).indexOf(component);
  return { value: id, label: componentLabel(component), rank: rank === -1 ? COMPONENTS.length : rank };
}

export function simulationValue(stack: CatalogStack): CatalogValue {
  return componentValue("simulation_layer", stack.simulation_layer);
}

/** An older control node reports the control layer only per vessel. */
export function controlValue(stack: CatalogStack): CatalogValue {
  return componentValue("control_layer", stack.control_layer ?? stack.vessels.own_ship?.control_layer ?? "none");
}

/** The mode is what the own ship runs: the other vessels replay in every stack. */
export function softwareValue(stack: CatalogStack): CatalogValue {
  return componentValue("asv_system", stack.mode);
}

const TIERS: readonly CatalogValue[] = [
  { value: "exact", label: "Exact", rank: 0 },
  { value: "bounded", label: "Bounded", rank: 1 },
  { value: "none", label: "No claim", rank: 2 },
];

export function repeatabilityValue(stack: CatalogStack): CatalogValue {
  const tier = stack.repeatability_tier;
  if (tier === null) {
    return { value: "unknown", label: "Unknown", rank: TIERS.length + 1 };
  }
  return TIERS.find((entry) => entry.value === tier) ?? { value: tier, label: tier, rank: TIERS.length };
}

/** What a run on the stack can use, as the Simulation page offers it. */
export function supportValues(stack: CatalogStack): CatalogValue[] {
  const environment = supportsEnvironment(stack);
  return [
    ...(environment.wind ? [{ value: "wind", label: "Wind", rank: 0 }] : []),
    ...(environment.waves ? [{ value: "waves", label: "Waves", rank: 1 }] : []),
    ...(stack.supports_early_stop ? [{ value: "early_stop", label: "Early stop", rank: 2 }] : []),
  ];
}

function availabilityValue(stack: CatalogStack): CatalogValue {
  return stack.available ? { value: "available", label: "Runs on this control node", rank: 0 } : { value: "unavailable", label: "Cannot run on this control node", rank: 1 };
}

/** Orders stacks wherever they are listed: by simulation layer, then control layer, then what the own ship runs. */
export function stackRank(stack: CatalogStack): number {
  const rank = (entry: CatalogValue) => entry.rank ?? 0;
  return rank(simulationValue(stack)) * COMPONENTS.length ** 2 + rank(controlValue(stack)) * COMPONENTS.length + rank(softwareValue(stack));
}

const FACETS: readonly CatalogFacet<CatalogStack>[] = [
  { key: "simulation", label: "Simulation layer", match: "any", values: (stack) => [simulationValue(stack)] },
  { key: "control", label: "Control layer", match: "any", values: (stack) => [controlValue(stack)] },
  { key: "software", label: "Own ship software", match: "any", values: (stack) => [softwareValue(stack)] },
  { key: "repeatability", label: "Repeatability", match: "any", values: (stack) => [repeatabilityValue(stack)] },
  { key: "supports", label: "Supports", match: "all", values: supportValues },
  { key: "availability", label: "Availability", match: "any", values: (stack) => [availabilityValue(stack)] },
];

export const STACK_CATALOG: CatalogModel<CatalogStack> = {
  idOf: (stack) => stack.id,
  textOf: (stack) => [stack.id, stack.label, stack.description, ...FACETS.flatMap((facet) => facet.values(stack).map((entry) => entry.label))].join(" "),
  facets: FACETS,
  groupings: FACETS.filter((facet) => facet.match === "any" && facet.key !== "availability").map((facet) => ({ key: facet.key, label: facet.label, groups: facet.values })),
};
