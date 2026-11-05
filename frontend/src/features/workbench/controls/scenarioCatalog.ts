import type { CatalogClass } from "../../../domain/cluster/campaignApi";

/**
 * The functional scenarios the scene page offers: the master's class catalog
 * (`backend/assets/generated_functional_models/all/`), found by text and by vessel and obstacle counts.
 * A class id (`3vessel_0obstacle_scenarios/fec5`) is also the scenario's label.
 */

export const ANY_COUNT = "any";

export function filterCatalogClasses(classes: readonly CatalogClass[], query: string, vesselFilter: string, obstacleFilter: string): CatalogClass[] {
  const q = query.trim().toLowerCase();
  const vessels = vesselFilter === ANY_COUNT ? null : Number(vesselFilter);
  const obstacles = obstacleFilter === ANY_COUNT ? null : Number(obstacleFilter);
  return classes.filter((entry) => {
    if (vessels !== null && entry.vessel_count !== vessels) return false;
    if (obstacles !== null && entry.obstacle_count !== obstacles) return false;
    return !q || entry.fec_id.toLowerCase().includes(q);
  });
}

/**
 * What the single scene list shows: the scenario loaded in the editor when it is among the listed ones, else
 * nothing (the placeholder). A list that showed a scenario it had not loaded, as a browser does when the
 * filters, the search or the page change its options, could never load that scenario: picking the option a
 * select already shows fires no change.
 */
export function listedValue(listed: readonly CatalogClass[], loadedLabel: string | null): string {
  return loadedLabel !== null && listed.some((entry) => entry.fec_id === loadedLabel) ? loadedLabel : "";
}

/** Batch selection: the listed classes join the selection; classes the filters hide stay selected. */
export function selectListed(selected: readonly string[], listed: readonly CatalogClass[]): string[] {
  return [...new Set([...selected, ...listed.map((entry) => entry.fec_id)])];
}

/** How many selected classes the filters hide. */
export function hiddenSelections(selected: readonly string[], listed: readonly CatalogClass[]): number {
  const shown = new Set(listed.map((entry) => entry.fec_id));
  return selected.filter((classId) => !shown.has(classId)).length;
}

/** The distinct vessel or obstacle counts of the catalog, ascending, for the filter selects. */
export function countOptions(classes: readonly CatalogClass[], key: "vessel_count" | "obstacle_count"): number[] {
  return [...new Set(classes.map((entry) => entry[key]))].sort((a, b) => a - b);
}
