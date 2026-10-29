import type { CatalogClass } from "../../../domain/cluster/campaignApi";

/**
 * The functional scenarios the scene page offers: the master's class catalog
 * (`backend/assets/generated_functional_models/all/`), found by text and by vessel and obstacle counts.
 * A class id (`3vessel_0obstacle_scenarios/functional_model5`) is also the scenario's label.
 */

export const ANY_COUNT = "any";

export function filterCatalogClasses(classes: readonly CatalogClass[], query: string, vesselFilter: string, obstacleFilter: string): CatalogClass[] {
  const q = query.trim().toLowerCase();
  const vessels = vesselFilter === ANY_COUNT ? null : Number(vesselFilter);
  const obstacles = obstacleFilter === ANY_COUNT ? null : Number(obstacleFilter);
  return classes.filter((entry) => {
    if (vessels !== null && entry.vessel_count !== vessels) return false;
    if (obstacles !== null && entry.obstacle_count !== obstacles) return false;
    return !q || entry.class_id.toLowerCase().includes(q);
  });
}

/** The distinct vessel or obstacle counts of the catalog, ascending, for the filter selects. */
export function countOptions(classes: readonly CatalogClass[], key: "vessel_count" | "obstacle_count"): number[] {
  return [...new Set(classes.map((entry) => entry[key]))].sort((a, b) => a - b);
}
