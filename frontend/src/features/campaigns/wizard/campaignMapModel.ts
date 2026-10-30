import type { CatalogClass, CatalogStacks, StepMonitor } from "../../../domain/cluster/campaignApi";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { plural } from "../campaignFormat";
import { needLabel, type ResourcePlan } from "../resourcePlan";
import { isEmptyScopeEntry } from "./configBuilder";
import { planScope } from "./scopePlan";
import { CAMPAIGN_STEP_LABELS, CHAIN, inputKindOf, normalizeSteps } from "./stepPlan";
import type { ValidationState } from "./useValidation";
import type { RetentionPolicy, RunDraft, WizardDraft, WizardStepId } from "./wizardState";

/**
 * The campaign map: the draft drawn as what the campaign does. The chain runs left to right (the input, each step the
 * campaign runs, one card per simulation run, the review) and the settings of the whole campaign (steps, domain,
 * resources, policy) sit in a row under it. Every card says in a few words what its page holds and opens that page,
 * so the operator sees what the earlier pages set while filling in the next one. Pure: the facts and the layout are
 * tested without a canvas.
 */

export type MapTone = "plain" | "ok" | "warn" | "bad" | "muted";

export interface MapFact {
  text: string;
  tone: MapTone;
}

/** `skipped` is a step of the chain the campaign does not run. */
export type MapCardKind = "input" | "stage" | "skipped" | "run" | "review";

export interface MapCard {
  id: string;
  kind: MapCardKind;
  title: string;
  /** What the page holds now, a short line each. */
  facts: MapFact[];
  /** The wizard page that sets what the card shows. */
  page: WizardStepId;
  /** The problems the page shows for the card, as the stepper counts them. */
  problems: number;
  /** The run a run card shows. */
  runId?: string;
  /** Top left corner and size in the drawing. */
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A box drawn behind cards that belong together (the runs of the simulation step). */
export interface MapFrame {
  id: string;
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MapEdge {
  id: string;
  source: string;
  target: string;
}

/** A setting of the whole campaign, shown under the chain. */
export interface MapSetting {
  id: string;
  title: string;
  facts: MapFact[];
  page: WizardStepId;
  problems: number;
}

export interface CampaignMap {
  cards: MapCard[];
  frames: MapFrame[];
  edges: MapEdge[];
  settings: MapSetting[];
  /** The size of the chain's drawing. */
  width: number;
  height: number;
}

/** Where the master's check of the config stands, as the review card says it. */
export type ReviewStatus = "incomplete" | "unchecked" | "checking" | "accepted" | "refused" | "failed";

export interface MapContext {
  stacks: CatalogStacks | undefined;
  classes: readonly CatalogClass[] | undefined;
  /** What the campaign needs against the machines it may use; null until the machines are read. */
  plan: ResourcePlan | null;
  /** The problems each page shows (the stepper's counts). */
  problems: Readonly<Record<WizardStepId, number>>;
  /** The problems the runs page shows per run, by index. */
  runProblems: readonly number[];
  review: ReviewStatus;
}

export const CARD_WIDTH = 188;
export const SKIPPED_WIDTH = 132;
export const COLUMN_GAP = 44;
export const STAGE_HEIGHT = 100;
export const RUN_HEIGHT = 80;
export const SKIPPED_HEIGHT = 64;
export const FRAME_PAD = 8;
export const FRAME_HEAD = 30;
export const RUN_GAP = 10;

const RETENTION_LABELS: Record<RetentionPolicy, string> = {
  all: "Keep everything",
  failures: "Keep failures",
  verdicts_only: "Verdicts only",
};

const REVIEW_FACTS: Record<ReviewStatus, MapFact> = {
  incomplete: { text: "Not complete yet", tone: "muted" },
  unchecked: { text: "Not checked on the master", tone: "plain" },
  checking: { text: "Checking on the master", tone: "plain" },
  accepted: { text: "Accepted by the master", tone: "ok" },
  refused: { text: "Refused by the master", tone: "bad" },
  failed: { text: "The check did not complete", tone: "warn" },
};

/** Where the check stands: the browser's own problems first, then the master's answer to the current config. */
export function reviewStatusOf(localProblems: number, validation: Pick<ValidationState, "status" | "yaml">, yaml: string): ReviewStatus {
  if (localProblems > 0) {
    return "incomplete";
  }
  if (validation.status === "checking") {
    return "checking";
  }
  if (validation.yaml !== yaml) {
    return "unchecked";
  }
  switch (validation.status) {
    case "valid":
      return "accepted";
    case "invalid":
      return "refused";
    case "error":
      return "failed";
    default:
      return "unchecked";
  }
}

function fact(text: string, tone: MapTone = "plain"): MapFact {
  return { text, tone };
}

function monitorFact(monitor: StepMonitor): MapFact {
  return monitor === "post_hoc" ? fact("Post hoc monitor") : fact("No monitor", "muted");
}

/** The cases the input brings (each class's quota added up, or one per item); null while the catalog a pattern needs is not loaded. */
export function plannedCases(draft: WizardDraft, classes: readonly CatalogClass[] | undefined): number | null {
  if (inputKindOf(draft.steps) !== "catalog_or_scenarios") {
    return draft.input.items.length;
  }
  const scenarioCases = draft.input.scenarios.reduce((total, scenario) => total + (scenario.quota ?? 0), 0);
  if (!draft.scope.some((entry) => !isEmptyScopeEntry(entry))) {
    return scenarioCases;
  }
  return classes ? planScope(draft.scope, classes).casesPlanned + scenarioCases : null;
}

function inputFacts(draft: WizardDraft, classes: readonly CatalogClass[] | undefined): MapFact[] {
  const kind = inputKindOf(draft.steps);
  if (kind !== "catalog_or_scenarios") {
    const items = draft.input.items;
    if (items.length === 0) {
      return [fact("Nothing chosen yet", "warn")];
    }
    const files = items.filter((item) => "file" in item.source).length;
    const fromHistory = items.length - files;
    const sources = [fromHistory > 0 ? `${fromHistory} from Campaign History` : null, files > 0 ? plural(files, "file") : null].filter((part) => part !== null);
    return [fact(plural(items.length, kind === "scenes" ? "scene" : "trajectory set")), fact(sources.join(", "), "muted")];
  }
  const facts: MapFact[] = [];
  const entries = draft.scope.filter((entry) => !isEmptyScopeEntry(entry));
  if (entries.length > 0) {
    if (classes) {
      const count = planScope(draft.scope, classes).classes;
      facts.push(fact(`${plural(count, "FEC")} of the catalog`, count > 0 ? "plain" : "warn"));
    } else {
      const named = entries.reduce((total, entry) => total + entry.classes.length, 0);
      const patterns = entries.reduce((total, entry) => total + entry.patterns.length, 0);
      facts.push(fact([named > 0 ? plural(named, "FEC") : null, patterns > 0 ? plural(patterns, "pattern") : null].filter((part) => part !== null).join(", ")));
    }
  }
  if (draft.input.scenarios.length > 0) {
    facts.push(fact(plural(draft.input.scenarios.length, "scenario file")));
  }
  if (facts.length === 0) {
    facts.push(fact("Nothing chosen yet", "warn"));
  }
  const cases = plannedCases(draft, classes);
  if (cases !== null && cases > 0) {
    facts.push(fact(`${plural(cases, "case")} to complete`, "muted"));
  }
  return facts;
}

function sceneFacts(draft: WizardDraft): MapFact[] {
  const timeout = draft.domain.sceneGenerationTimeoutS;
  const facts = [monitorFact(draft.sceneMonitor), timeout !== null && timeout > 0 ? fact(`At most ${timeout} s per scene`, "muted") : fact("No timeout set", "warn")];
  if (draft.domain.enforceLowTcpa) {
    facts.push(fact("Low TCPA enforced"));
  }
  return facts;
}

function trajectoryFacts(draft: WizardDraft, stacks: CatalogStacks | undefined): MapFact[] {
  const generator = stacks?.trajectory_generators.find((entry) => entry.id === draft.trajectories.generator);
  const changed = Object.keys(draft.trajectories.parameters).length;
  return [
    fact(generator?.label ?? draft.trajectories.generator, stacks && !generator ? "bad" : "plain"),
    changed > 0 ? fact(`${plural(changed, "parameter")} changed`) : fact("Default parameters", "muted"),
    monitorFact(draft.trajectoryMonitor),
  ];
}

function runTitle(run: RunDraft, index: number): string {
  const name = run.name.trim();
  return `Run ${index + 1}${name ? `: ${name}` : ""}`;
}

function runFacts(run: RunDraft, stacks: CatalogStacks | undefined): MapFact[] {
  const stack = stacks?.stacks.find((entry) => entry.id === run.stackId);
  const monitor = stacks?.monitors.find((entry) => entry.id === run.monitor);
  const repeats = run.repeats ?? 1;
  const label = monitor?.label ?? run.monitor.replace(/_/g, " ");
  const details = [run.monitor === "empty" ? "No monitor" : `${label.charAt(0).toUpperCase()}${label.slice(1)} monitor`, repeats > 1 ? `${repeats} repeats` : null, run.earlyStop ? "early stop" : null];
  return [
    run.stackId === "" ? fact("No stack chosen", "warn") : fact(stack?.label ?? run.stackId, stacks && !stack ? "bad" : "plain"),
    fact(details.filter((part) => part !== null).join(", "), "muted"),
  ];
}

function reviewFacts(draft: WizardDraft, context: MapContext, steps: readonly CampaignStep[]): MapFact[] {
  const facts = [REVIEW_FACTS[context.review]];
  const cases = plannedCases(draft, context.classes);
  if (cases !== null && cases > 0) {
    if (steps.includes("simulation")) {
      const perCase = draft.runs.reduce((total, run) => total + (run.repeats ?? 1), 0);
      facts.push(fact(`${plural(cases, "case")}, ${plural(cases * perCase, "simulation")}`, "muted"));
    } else {
      facts.push(fact(`${plural(cases, "case")} planned`, "muted"));
    }
  }
  return facts;
}

function settingsOf(draft: WizardDraft, context: MapContext): MapSetting[] {
  const { plan, problems } = context;
  const { resources, policy } = draft;
  let machines: MapFact[];
  if (plan === null) {
    machines = [fact(resources.fullUsage ? "Every machine, full capacity" : `${plural(resources.nodes.length, "machine")} chosen`), fact("Machines not read yet", "muted")];
  } else if (plan.missing.length > 0) {
    // The need as the resources step names it: a simulation with the components its runs need
    const label = needLabel(plan.missing[0]);
    const missing = label.charAt(0).toUpperCase() + label.slice(1);
    machines = [fact(plan.missing.length === 1 ? `Missing: ${missing}` : `Missing: ${missing} and ${plan.missing.length - 1} more`, "bad")];
  } else {
    machines = [fact(resources.fullUsage ? "Every machine, full capacity" : `${plural(resources.nodes.length, "machine")} chosen`), fact(`${plural(plan.usable.length, "machine")} usable`, plan.usable.length > 0 ? "ok" : "warn")];
  }
  const stops = [policy.maxCases, policy.maxFailedVerdicts, policy.maxDurationS].filter((value) => value !== null).length;
  const name = draft.name.trim();
  const chosen = normalizeSteps(draft.steps);
  const chain = chosen.length === 1 ? `${CAMPAIGN_STEP_LABELS[chosen[0]]} only` : `${CAMPAIGN_STEP_LABELS[chosen[0]]} to ${CAMPAIGN_STEP_LABELS[chosen[chosen.length - 1]].toLowerCase()}`;
  return [
    { id: "steps", title: "Steps", page: "steps", problems: problems.steps, facts: [name ? fact(name) : fact("No name yet", "warn"), fact(chain, "muted")] },
    { id: "domain", title: "Domain", page: "domain", problems: problems.domain, facts: [draft.domain.custom ? fact("Customized for this campaign") : fact("The cluster's configuration", "muted")] },
    { id: "resources", title: "Resources", page: "resources", problems: problems.resources, facts: machines },
    {
      id: "policy",
      title: "Policy",
      page: "policy",
      problems: problems.policy,
      facts: [fact(`${RETENTION_LABELS[policy.retention]}, base seed ${policy.seed ?? 0}`), stops > 0 ? fact(plural(stops, "stop condition")) : fact("No stop conditions", "muted")],
    },
  ];
}

/**
 * Where the drawing starts in a canvas `width` wide with `pad` kept free at each side: in the middle while the
 * drawing (`drawn` wide at `zoom`) fits, otherwise at its left end unless the cards of the page shown, which end at
 * `currentRight` in the drawing, lie further right: those are brought to the canvas's right edge.
 */
export function drawingOffset(width: number, drawn: number, zoom: number, currentRight: number | null, pad: number): number {
  if (drawn <= width - 2 * pad) {
    return Math.max(pad, (width - drawn) / 2);
  }
  if (currentRight === null) {
    return pad;
  }
  return Math.max(width - pad - drawn, Math.min(pad, width - pad - currentRight * zoom));
}

type Column = { kind: "input" } | { kind: "stage"; step: CampaignStep } | { kind: "skipped"; step: CampaignStep } | { kind: "runs" } | { kind: "review" };

/** The columns of the chain: the steps before the first and after the last are drawn as skipped, the input comes before the first and the review after the last. */
function columnsOf(steps: readonly CampaignStep[]): Column[] {
  const columns: Column[] = [];
  const first = steps[0];
  const last = steps[steps.length - 1];
  for (const step of CHAIN) {
    if (!steps.includes(step)) {
      columns.push({ kind: "skipped", step });
      continue;
    }
    if (step === first) {
      columns.push({ kind: "input" });
    }
    columns.push(step === "simulation" ? { kind: "runs" } : { kind: "stage", step });
    if (step === last) {
      columns.push({ kind: "review" });
    }
  }
  return columns;
}

const STAGE_PAGES: Record<Exclude<CampaignStep, "simulation">, WizardStepId> = {
  scene_generation: "scenes",
  trajectory_generation: "trajectories",
};

/** The map of the draft: the chain's cards laid out left to right, the arrows between them and the settings of the whole campaign. */
export function buildCampaignMap(draft: WizardDraft, context: MapContext): CampaignMap {
  const steps = normalizeSteps(draft.steps);
  const columns = columnsOf(steps);
  const runsHeight = FRAME_HEAD + draft.runs.length * RUN_HEIGHT + Math.max(0, draft.runs.length - 1) * RUN_GAP + FRAME_PAD;
  const height = steps.includes("simulation") ? Math.max(STAGE_HEIGHT, runsHeight) : STAGE_HEIGHT;
  const middle = (size: number) => (height - size) / 2;

  const cards: MapCard[] = [];
  const frames: MapFrame[] = [];
  const edges: MapEdge[] = [];
  // The cards whose output the next column takes
  let feeding: string[] = [];
  const connect = (target: string) => {
    for (const source of feeding) {
      edges.push({ id: `${source}->${target}`, source, target });
    }
  };

  let x = 0;
  for (const column of columns) {
    switch (column.kind) {
      case "skipped":
        cards.push({
          id: `skipped:${column.step}`,
          kind: "skipped",
          title: CAMPAIGN_STEP_LABELS[column.step],
          facts: [fact("Not run", "muted")],
          page: "steps",
          problems: 0,
          x,
          y: middle(SKIPPED_HEIGHT),
          width: SKIPPED_WIDTH,
          height: SKIPPED_HEIGHT,
        });
        x += SKIPPED_WIDTH + COLUMN_GAP;
        break;
      case "input":
        cards.push({ id: "input", kind: "input", title: "Input", facts: inputFacts(draft, context.classes), page: "input", problems: context.problems.input, x, y: middle(STAGE_HEIGHT), width: CARD_WIDTH, height: STAGE_HEIGHT });
        feeding = ["input"];
        x += CARD_WIDTH + COLUMN_GAP;
        break;
      case "stage": {
        const page = STAGE_PAGES[column.step as Exclude<CampaignStep, "simulation">];
        const facts = column.step === "scene_generation" ? sceneFacts(draft) : trajectoryFacts(draft, context.stacks);
        cards.push({ id: column.step, kind: "stage", title: CAMPAIGN_STEP_LABELS[column.step], facts, page, problems: context.problems[page], x, y: middle(STAGE_HEIGHT), width: CARD_WIDTH, height: STAGE_HEIGHT });
        connect(column.step);
        feeding = [column.step];
        x += CARD_WIDTH + COLUMN_GAP;
        break;
      }
      case "runs": {
        const top = middle(runsHeight);
        frames.push({ id: "simulation", title: `${CAMPAIGN_STEP_LABELS.simulation}, ${plural(draft.runs.length, "run")}`, x, y: top, width: CARD_WIDTH + 2 * FRAME_PAD, height: runsHeight });
        const runIds = draft.runs.map((run) => `run:${run.id}`);
        draft.runs.forEach((run, index) => {
          cards.push({
            id: runIds[index],
            kind: "run",
            title: runTitle(run, index),
            facts: runFacts(run, context.stacks),
            page: "runs",
            problems: context.runProblems[index] ?? 0,
            runId: run.id,
            x: x + FRAME_PAD,
            y: top + FRAME_HEAD + index * (RUN_HEIGHT + RUN_GAP),
            width: CARD_WIDTH,
            height: RUN_HEIGHT,
          });
          connect(runIds[index]);
        });
        feeding = runIds;
        x += CARD_WIDTH + 2 * FRAME_PAD + COLUMN_GAP;
        break;
      }
      case "review":
        cards.push({ id: "review", kind: "review", title: "Review", facts: reviewFacts(draft, context, steps), page: "review", problems: 0, x, y: middle(STAGE_HEIGHT), width: CARD_WIDTH, height: STAGE_HEIGHT });
        connect("review");
        feeding = [];
        x += CARD_WIDTH + COLUMN_GAP;
        break;
    }
  }

  return { cards, frames, edges, settings: settingsOf(draft, context), width: x - COLUMN_GAP, height };
}
