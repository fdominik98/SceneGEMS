import { z } from "zod";
import { artifactRefSchema, type ArtifactRef } from "../cluster/schemas";

/**
 * The design space exploration as the control node reports it: the result of its job (the stage
 * `explore_design_space` of the exploration case), the explored FECs and their ids. The campaign
 * gets one class with id `exploration` for the exploration itself; when it succeeds, the control node
 * adds one class per generated model, `explored/<five digit index>`.
 */

/** The class of the exploration itself (no scenario class: it has no vessels and no verdicts). */
export const EXPLORATION_FEC_ID = "exploration";
export const EXPLORED_FEC_PREFIX = "explored/";

export function isExplorationFec(fecId: string): boolean {
  return fecId === EXPLORATION_FEC_ID;
}

export function isExploredFec(fecId: string): boolean {
  return fecId.startsWith(EXPLORED_FEC_PREFIX);
}

/** The id of the FEC of a generated model: `explored/00003` for index 3. */
export function exploredFecId(index: number): string {
  return `${EXPLORED_FEC_PREFIX}${String(index).padStart(5, "0")}`;
}

/**
 * The job's result; unknown fields are kept out. `stop_reason` says why the search ended: `exhausted`
 * (every FEC found), `unsatisfiable` (no model at all), `cap_reached`, `timeout` or `stopped`; one
 * this console does not know reads as a plain string.
 */
export const explorationResultSchema = z.object({
  stop_reason: z.string(),
  complete: z.boolean().optional(),
  models_found: z.number().int().nonnegative(),
  max_models: z.number().int().nullable().optional(),
  random_seed: z.number().int().nullable().optional(),
  elapsed_s: z.number().nullable().optional(),
  message: z.string().nullable().optional(),
  fecs: z.array(z.object({ index: z.number().int(), vessel_count: z.number().int(), obstacle_count: z.number().int() })).optional(),
  functional_scenarios: z.array(z.unknown()).optional(),
});
export type ExplorationResult = z.infer<typeof explorationResultSchema>;

/** The job result as an exploration result, null when it is none (a job that has not ended, another control node). */
export function parseExplorationResult(value: unknown): ExplorationResult | null {
  const parsed = explorationResultSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/** One explored FEC as the page lists it. */
export interface ExploredFec {
  fecId: string;
  index: number;
  vesselCount: number | null;
  obstacleCount: number | null;
  /** Its `.problem` text on the control node, null when the control node names none. */
  artifact: ArtifactRef | null;
}

/** The FECs a result names with the artifacts of its `functional_scenarios`, for when the outputs are not readable. */
export function exploredFecsOfResult(result: ExplorationResult): ExploredFec[] {
  const artifacts = result.functional_scenarios ?? [];
  return (result.fecs ?? []).map((fec, position) => {
    const artifact = artifactRefSchema.safeParse(artifacts[position]);
    return {
      fecId: exploredFecId(fec.index),
      index: fec.index,
      vesselCount: fec.vessel_count,
      obstacleCount: fec.obstacle_count,
      artifact: artifact.success ? artifact.data : null,
    };
  });
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * How many FECs were found and what that means, in plain words: all FECs of the design space, the
 * first N because of the cap or the time limit, or none because the specification has no model.
 */
export function describeExploration(result: Pick<ExplorationResult, "stop_reason" | "models_found" | "max_models">, shown: number = result.models_found): string {
  const found = plural(shown, "FEC");
  switch (result.stop_reason) {
    case "exhausted":
      return shown === 0 ? "No FEC: the specification has no model within the scope." : `${found}: all FECs of the design space.`;
    case "unsatisfiable":
      return "No FEC: the specification has no model within the scope.";
    case "cap_reached":
      return `The first ${found}: the cap${typeof result.max_models === "number" ? ` of ${result.max_models}` : ""} was reached, there may be more.`;
    case "timeout":
      return shown === 0 ? "No FEC: the time limit ended the search before it found one." : `The first ${found}: the time limit ended the search, there may be more.`;
    case "stopped":
      return shown === 0 ? "No FEC: the search was stopped before it found one." : `The first ${found}: the search was stopped, there may be more.`;
    default:
      return `${found} (the search ended: ${result.stop_reason}).`;
  }
}
