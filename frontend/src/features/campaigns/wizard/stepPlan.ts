import { CAMPAIGN_STEPS, type CampaignStep } from "../../../domain/cluster/schemas";
import type { WizardStepId } from "./wizardState";

/**
 * Which parts of the chain a campaign runs and what that means for the wizard: the steps it shows,
 * the queue stages it uses and the kind of input it takes. Pure, so the builder, the checks and the
 * steps read the same answers.
 */

export const CHAIN: readonly CampaignStep[] = CAMPAIGN_STEPS;

export const CAMPAIGN_STEP_LABELS: Record<CampaignStep, string> = {
  scene_generation: "Scene generation",
  trajectory_generation: "Trajectory generation",
  simulation: "Simulation",
};

/** What each step produces, in the words the Steps step uses. */
export const CAMPAIGN_STEP_OUTPUTS: Record<CampaignStep, string> = {
  scene_generation: "scenes",
  trajectory_generation: "trajectories",
  simulation: "simulated runs",
};

/** The steps from `first` to `last` in chain order; `last` before `first` gives `first` alone. */
export function stepRange(first: CampaignStep, last: CampaignStep): CampaignStep[] {
  const from = CHAIN.indexOf(first);
  const to = Math.max(from, CHAIN.indexOf(last));
  return CHAIN.slice(from, to + 1);
}

/** The steps as the config states them: only known steps, once each, in chain order; the whole chain when none is left. */
export function normalizeSteps(steps: readonly unknown[] | undefined): CampaignStep[] {
  const chosen = CHAIN.filter((step) => steps?.includes(step));
  if (chosen.length === 0) {
    return [...CHAIN];
  }
  // A gap would be refused by the master: close it
  return stepRange(chosen[0], chosen[chosen.length - 1]);
}

export function firstStep(steps: readonly CampaignStep[]): CampaignStep {
  return normalizeSteps(steps)[0];
}

export function lastStep(steps: readonly CampaignStep[]): CampaignStep {
  const chosen = normalizeSteps(steps);
  return chosen[chosen.length - 1];
}

export function runsStep(steps: readonly CampaignStep[], step: CampaignStep): boolean {
  return steps.includes(step);
}

/** The wizard steps a campaign with these steps goes through, in order. Steps not run hide their own pages. */
export function visibleWizardSteps(steps: readonly CampaignStep[]): WizardStepId[] {
  const shown: WizardStepId[] = ["steps", "input", "domain"];
  if (runsStep(steps, "scene_generation")) {
    shown.push("scenes");
  }
  if (runsStep(steps, "trajectory_generation")) {
    shown.push("trajectories");
  }
  if (runsStep(steps, "simulation")) {
    shown.push("runs");
  }
  shown.push("resources", "policy", "review");
  return shown;
}

/** What the first step takes as input. */
export type InputKind = "catalog_or_scenarios" | "scenes" | "trajectories";

export function inputKindOf(steps: readonly CampaignStep[]): InputKind {
  switch (firstStep(steps)) {
    case "scene_generation":
      return "catalog_or_scenarios";
    case "trajectory_generation":
      return "scenes";
    default:
      return "trajectories";
  }
}

/** The config kinds an item may have for the first step (`input.items[n].ref.kind`). */
export function itemKindsFor(steps: readonly CampaignStep[]): readonly string[] {
  switch (inputKindOf(steps)) {
    case "scenes":
      return ["scene"];
    case "trajectories":
      return ["trajectory_data", "trajectories"];
    default:
      return [];
  }
}

/** The steps of Campaign History whose outputs fit the first step as input. */
export function sourceStepsFor(steps: readonly CampaignStep[]): CampaignStep[] {
  switch (inputKindOf(steps)) {
    case "scenes":
      return ["scene_generation"];
    case "trajectories":
      return ["trajectory_generation", "simulation"];
    default:
      return [];
  }
}

/** The kind an uploaded file is stored as for the first step. */
export function uploadKindFor(steps: readonly CampaignStep[]): "scene" | "trajectories" | null {
  switch (inputKindOf(steps)) {
    case "scenes":
      return "scene";
    case "trajectories":
      return "trajectories";
    default:
      return null;
  }
}

/** The queue stages (`QUEUE_DEPTH_DEFAULTS` keys) the cases of a campaign pass through. */
export function activeStages(steps: readonly CampaignStep[], monitored: { scene: boolean; trajectories: boolean; simulation: boolean }): string[] {
  const stages: string[] = [];
  if (runsStep(steps, "scene_generation")) {
    stages.push("generate_scene");
  }
  if (runsStep(steps, "trajectory_generation")) {
    stages.push("generate_trajectories");
  }
  if (runsStep(steps, "simulation")) {
    stages.push("simulate");
  }
  if ((runsStep(steps, "scene_generation") && monitored.scene) || (runsStep(steps, "trajectory_generation") && monitored.trajectories) || (runsStep(steps, "simulation") && monitored.simulation)) {
    stages.push("monitor");
  }
  return stages;
}
