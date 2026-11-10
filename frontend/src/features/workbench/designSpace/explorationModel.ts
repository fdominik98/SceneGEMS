import { scopeProblem } from "../../../domain/designSpace/designSpaceScope";
import type { ExploredFec } from "../../../domain/designSpace/explorationResult";

/** Pure helpers of the design space exploration page: the run button's reason, the list's rows and the editor's place. */

/** Why the page cannot explore with this input, for the run button's tooltip; null when it can. */
export function explorationInputProblem(specification: string, scope: string): string | null {
  if (specification.trim().length === 0) {
    return "Write or load the metamodel and the well-formedness constraints in the specification pane first";
  }
  const problem = scopeProblem(scope);
  return problem === null ? null : `Correct the scope first: ${problem}`;
}

/** Every row of the list has this height, so the list draws only the rows in view and nothing moves when a text arrives. */
export const FEC_ROW_HEIGHT = 60;
const OVERSCAN = 6;

function count(value: number | null, one: string, many: string): string {
  return value === null ? `? ${many}` : `${value} ${value === 1 ? one : many}`;
}

/** A FEC's counts as the list shows them: "2 vessels, 0 obstacles". */
export function fecCounts(fec: Pick<ExploredFec, "vesselCount" | "obstacleCount">): string {
  return `${count(fec.vesselCount, "vessel", "vessels")}, ${count(fec.obstacleCount, "obstacle", "obstacles")}`;
}

/** The rows of a list of this many rows in view at this scroll position, with some above and below. */
export function visibleRange(total: number, scrollTop: number, height: number): { first: number; last: number } {
  const first = Math.max(0, Math.floor(scrollTop / FEC_ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(total, Math.ceil((scrollTop + height) / FEC_ROW_HEIGHT) + OVERSCAN);
  return { first, last };
}

/** The id of the specification pane, so the page's Input row can bring the editor into view. */
export const DESIGN_SPACE_EDITOR_ID = "design-space-specification";

/** Brings the specification editor into view and puts the cursor in it. */
export function focusDesignSpaceEditor(): void {
  const pane = typeof document === "undefined" ? null : document.getElementById(DESIGN_SPACE_EDITOR_ID);
  pane?.scrollIntoView?.({ block: "nearest" });
  pane?.querySelector<HTMLElement>(".cm-content")?.focus();
}
