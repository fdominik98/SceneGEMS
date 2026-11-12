import type { StepStatus } from "./StepPanel";

/** The words the four step panels share, so that the same state reads the same on every page. */

/** The status of every page that has nothing to run on yet. */
export const NO_INPUT_STATUS: StepStatus = { label: "No input yet", tone: "idle" };

/** The status of a page that has its input and waits for the run button: "Ready to plan". */
export function readyStatus(verb: string): StepStatus {
  return { label: `Ready to ${verb}`, tone: "idle" };
}

/** Where a page's run happens, the same sentence on every page: the cluster's slots for it, and that the run is kept. */
export function describeWhere(resources: string): string {
  return `Runs as a job on the cluster: ${resources}. Every run is kept in Campaign History.`;
}
