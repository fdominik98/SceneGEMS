import { parseDocument } from "yaml";
import { scopeProblem } from "../../../domain/designSpace/designSpaceScope";
import { findGenerator, findStack, isEmptyScopeEntry, isSet, supportsEnvironment, type BuilderCatalog } from "./configBuilder";
import type { EntryList, Reason } from "./reasons";
import { firstStep, inputKindOf, itemKindsFor, normalizeSteps, runsStep } from "./stepPlan";
import { UPLOAD_LIFETIME_MS, type WizardDraft, type WizardStepId } from "./wizardState";

/**
 * Problems of a draft the browser can see without the master: a missing name, an empty scope entry, a
 * run without an available stack, a parameter the stack requires, domain text that is not YAML. They
 * come in the shape of the server's reasons so the steps show both the same way. The master still
 * validates everything (the catalog, the resolver, every range).
 */

function local(step: WizardStepId, entry: number | null, field: string | null, message: string, list?: EntryList): Reason {
  const path = entry === null ? field : field ? `${entry}.${field}` : String(entry);
  return { raw: message, step, entry, ...(list ? { list } : {}), field, path, message, source: "local" };
}

function yamlProblem(text: string): string | null {
  const document = parseDocument(text, { uniqueKeys: true });
  if (document.errors.length > 0) {
    return document.errors[0].message.split("\n")[0];
  }
  const value: unknown = document.toJS();
  if (typeof value !== "object" || value === null || Array.isArray(value) || Object.keys(value).length === 0) {
    return "expected a YAML mapping with at least one entry";
  }
  return null;
}

/** Whether an upload made at `uploadedAt` is gone from the master by `now` (it holds the file for 24 hours). */
export function uploadExpired(uploadedAt: number | null, now: number): boolean {
  return uploadedAt !== null && now - uploadedAt >= UPLOAD_LIFETIME_MS;
}

const EXPIRED_UPLOAD = "The upload has expired on the master; upload the file again.";

/** The design space exploration's own fields: a specification, a valid scope, and limits in range. */
function checkExploration(draft: WizardDraft, reasons: Reason[]): void {
  const exploration = draft.exploration;
  if (exploration.specification.trim().length === 0) {
    reasons.push(local("exploration", null, "specification", "Write or load the metamodel and the well-formedness constraints."));
  }
  const scope = scopeProblem(exploration.scope);
  if (scope !== null) {
    reasons.push(local("exploration", null, "scope", scope));
  }
  if (exploration.maxFecs !== null && exploration.maxFecs < 1) {
    reasons.push(local("exploration", null, "max_fecs", "Max FECs is at least 1, or empty for every FEC."));
  }
  if (exploration.timeoutS === null || exploration.timeoutS <= 0) {
    reasons.push(local("exploration", null, "timeout_s", "The timeout is above 0 seconds."));
  }
  if (draft.steps.length <= 1) {
    // Quota and failure budget matter only for the cases of later steps
    return;
  }
  if (exploration.quota === null || exploration.quota < 1) {
    reasons.push(local("exploration", null, "quota", "Each explored FEC needs at least 1 case."));
  }
  if (typeof exploration.failureBudget === "number" && exploration.failureBudget < 0) {
    reasons.push(local("exploration", null, "failure_budget", "The failure budget is 0 or more."));
  }
}

function checkInput(draft: WizardDraft, reasons: Reason[], now: number): void {
  const steps = normalizeSteps(draft.steps);
  if (inputKindOf(steps) === "explored") {
    // The FECs come from the exploration: nothing to pick
    return;
  }
  if (inputKindOf(steps) === "catalog_or_scenarios") {
    const scenarios = draft.input.scenarios;
    const names = scenarios.map((scenario) => scenario.name.trim());
    scenarios.forEach((scenario, index) => {
      const name = scenario.name.trim();
      if (name.length === 0) {
        reasons.push(local("input", index, "name", "Give the scenario a name.", "scenario"));
      } else if (name.includes("/")) {
        reasons.push(local("input", index, "name", "The name has no slash.", "scenario"));
      } else if (names.indexOf(name) !== index) {
        reasons.push(local("input", index, "name", "Another scenario file has this name.", "scenario"));
      }
      if (scenario.quota === null || scenario.quota < 1) {
        reasons.push(local("input", index, "quota", "The quota is at least 1.", "scenario"));
      }
      if (typeof scenario.failureBudget === "number" && scenario.failureBudget < 0) {
        reasons.push(local("input", index, "failure_budget", "The failure budget is 0 or more.", "scenario"));
      }
      if (uploadExpired(scenario.uploadedAt, now)) {
        reasons.push(local("input", index, "ref", EXPIRED_UPLOAD, "scenario"));
      }
    });
    // Entries nothing was picked into are ignored while scenario files give the campaign something to run
    draft.scope.forEach((entry, index) => {
      if (isEmptyScopeEntry(entry)) {
        if (scenarios.length === 0) {
          reasons.push(local("input", index, null, "Choose FECs or a folder pattern, or add a functional scenario file."));
        }
        return;
      }
      if (entry.quota === null || entry.quota < 1) {
        reasons.push(local("input", index, "quota", "The quota is at least 1."));
      }
      if (typeof entry.failureBudget === "number" && entry.failureBudget < 0) {
        reasons.push(local("input", index, "failure_budget", "The failure budget is 0 or more."));
      }
    });
    return;
  }
  const kinds = itemKindsFor(steps);
  const label = inputKindOf(steps) === "scenes" ? "scenes" : "trajectories";
  if (draft.input.items.length === 0) {
    reasons.push(local("input", null, "items", `Add at least one of the ${label} the campaign starts from.`));
  }
  draft.input.items.forEach((item, index) => {
    if (item.name.trim().length === 0) {
      reasons.push(local("input", index, "name", "Give the item a name.", "item"));
    }
    if (!kinds.includes(item.ref.kind)) {
      reasons.push(local("input", index, "ref", `${firstStep(steps) === "trajectory_generation" ? "Trajectory generation" : "Simulation"} takes ${label}, not ${item.ref.kind.replace(/_/g, " ")}.`, "item"));
    }
    if (uploadExpired(item.uploadedAt, now)) {
      reasons.push(local("input", index, "ref", EXPIRED_UPLOAD, "item"));
    }
  });
}

/** The problems found in the draft; `catalog` is null while the master's stack catalog is not loaded; `now` dates the uploads. */
export function checkDraft(draft: WizardDraft, catalog: BuilderCatalog | null, now: number = Date.now()): Reason[] {
  const reasons: Reason[] = [];
  const steps = normalizeSteps(draft.steps);
  if (draft.name.trim().length === 0) {
    reasons.push(local("steps", null, "name", "Give the campaign a name."));
  }
  checkInput(draft, reasons, now);
  if (runsStep(steps, "design_space_exploration")) {
    checkExploration(draft, reasons);
  }
  if (draft.domain.custom) {
    const texts: [string, string][] = [
      ["colregs_constants", draft.domain.colregsConstants],
      ["vessel_types", draft.domain.vesselTypes],
      ["obstacle_types", draft.domain.obstacleTypes],
    ];
    for (const [field, text] of texts) {
      const problem = text.trim().length === 0 ? "expected a YAML mapping with at least one entry" : yamlProblem(text);
      if (problem) {
        reasons.push(local("domain", null, field, `Not valid YAML: ${problem}`));
      }
    }
  }
  if (runsStep(steps, "scene_generation") && (!isSet(draft.domain.sceneGenerationTimeoutS) || (draft.domain.sceneGenerationTimeoutS ?? 0) <= 0)) {
    reasons.push(local("scenes", null, "scene_generation_timeout_s", "The timeout is above 0 seconds."));
  }
  if (catalog && runsStep(steps, "trajectory_generation")) {
    const generator = findGenerator(catalog, draft.trajectories.generator);
    if (!generator) {
      reasons.push(local("trajectories", null, "generator", `The master offers no generator ${draft.trajectories.generator}.`));
    } else {
      for (const parameter of generator.parameters) {
        if (parameter.required && !isSet(draft.trajectories.parameters[parameter.key])) {
          reasons.push(local("trajectories", null, parameter.key, `${parameter.key} is required.`));
        }
      }
    }
  }
  if (runsStep(steps, "trajectory_generation") && (!isSet(draft.trajectories.timeoutS) || (draft.trajectories.timeoutS ?? 0) <= 0)) {
    reasons.push(local("trajectories", null, "timeout_s", "The timeout is above 0 seconds."));
  }
  (runsStep(steps, "simulation") ? draft.runs : []).forEach((run, index) => {
    const stack = catalog ? findStack(catalog, run.stackId) : undefined;
    if (catalog && !run.stackId) {
      reasons.push(local("runs", index, "stack", "Choose a stack."));
    } else if (catalog && !stack) {
      reasons.push(local("runs", index, "stack", `The master offers no stack ${run.stackId}.`));
    } else if (stack && !stack.available) {
      reasons.push(local("runs", index, "stack", `${stack.label} is not available: ${stack.reasons.join("; ") || "no reason given"}.`));
    }
    if (run.earlyStop && run.monitor !== "live") {
      reasons.push(local("runs", index, "early_stop", "Early stop needs the live monitor."));
    } else if (run.earlyStop && stack?.supports_early_stop === false) {
      reasons.push(local("runs", index, "early_stop", `${stack.label} runs to the end: a run on it does not stop early.`));
    }
    if (run.repeats === null || run.repeats < 1) {
      reasons.push(local("runs", index, "repeats", "Repeats is at least 1."));
    }
    for (const group of stack?.groups ?? []) {
      const values = run.groups[group.key];
      if (values === undefined) {
        continue;
      }
      for (const parameter of group.parameters) {
        if (parameter.required && !isSet(values[parameter.key])) {
          reasons.push(local("runs", index, `stack.${group.key}.${parameter.key}`, `${parameter.key} is required when the group is set.`));
        }
      }
    }
    if (supportsEnvironment(stack).waves && run.waves) {
      for (const key of ["amplitude", "period", "steepness", "direction"]) {
        if (!isSet(run.waves[key])) {
          reasons.push(local("runs", index, `environment.waves.${key}`, `${key} is required when waves are set.`));
        }
      }
    }
  });
  if (runsStep(steps, "simulation") && draft.runs.length === 0) {
    reasons.push(local("runs", null, "runs", "Add at least one run."));
  }
  if (!draft.resources.fullUsage && draft.resources.nodes.length === 0) {
    reasons.push(local("resources", null, "nodes", "Choose at least one machine, or use every machine."));
  }
  if (draft.resources.labels.some((label) => label.key.trim().length === 0 && label.value.length > 0)) {
    reasons.push(local("resources", null, "required_labels", "A label value needs a name."));
  }
  return reasons;
}
