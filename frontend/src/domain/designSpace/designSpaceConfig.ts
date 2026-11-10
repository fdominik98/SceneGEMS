/**
 * The `design_space_exploration` section of a format 3 campaign config, present only when the
 * campaign runs the step (then first in its `steps`, with no `scope` and no `input`: the FECs come
 * from the exploration). The master validates it; these are its defaults and its shape.
 */

/** At most this many FECs unless the config says otherwise; null in the config means every FEC. */
export const DEFAULT_MAX_FECS = 1000;
export const DEFAULT_EXPLORATION_TIMEOUT_S = 600;
/** Complete cases each explored FEC needs when later steps run. */
export const DEFAULT_EXPLORATION_QUOTA = 1;

export type ExplorationFailureBudget = number | "unlimited";

export interface DesignSpaceSection {
  /** The metamodel and the well-formedness constraints (the first part of a FEC specification). */
  specification: string;
  scope: string;
  max_fecs?: number | null;
  timeout_s?: number;
  quota?: number;
  failure_budget?: ExplorationFailureBudget;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The section of a config, or null when the config has none. Missing fields stay missing (the defaults apply). */
export function designSpaceSectionOf(config: Record<string, unknown>): DesignSpaceSection | null {
  const section = config.design_space_exploration;
  if (!isRecord(section)) {
    return null;
  }
  const result: DesignSpaceSection = {
    specification: typeof section.specification === "string" ? section.specification : "",
    scope: typeof section.scope === "string" ? section.scope : "",
  };
  if (section.max_fecs === null || typeof section.max_fecs === "number") {
    result.max_fecs = section.max_fecs;
  }
  if (typeof section.timeout_s === "number") {
    result.timeout_s = section.timeout_s;
  }
  if (typeof section.quota === "number") {
    result.quota = section.quota;
  }
  if (typeof section.failure_budget === "number" || section.failure_budget === "unlimited") {
    result.failure_budget = section.failure_budget;
  }
  return result;
}
