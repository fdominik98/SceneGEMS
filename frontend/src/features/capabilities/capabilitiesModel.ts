import type { ArchitectureDocument, ArchitectureNode, Combination, Fact } from "../../domain/cluster/architectureApi";

/** What the graph shows: the implementations and their adapters, or the generic layers they fill in. */
export type GraphView = "concrete" | "metamodel";
/** The page's views of one document: the two graphs, and for the vessel stack the availability matrix. */
export type DocumentView = GraphView | "matrix";

export type Tone = "ok" | "warn" | "bad" | "neutral";

export const UNBOUNDED = "unbounded";
/** The fact of an available stack that names the job and runner running it on a node ("simulation, runner kinematic"), null when it runs on the workbench only (vessel_stack_description.CLUSTER_JOB_FACT). */
export const CLUSTER_JOB_FACT = "cluster_job";

/** How good a capability value is: green for what a run can rely on, amber for what is limited or unconfirmed, red for what is missing. */
export function factTone(fact: Fact): Tone {
  const value = fact.value;
  switch (fact.key) {
    case "repeatability_tier":
      return value === "exact" ? "ok" : value === "bounded" ? "warn" : "bad";
    case "wind":
    case "waves":
      return value === "supported" ? "ok" : value === "unmeasured" ? "warn" : "bad";
    case "lockstep":
    case "faster_than_real_time":
      return value === true ? "ok" : "bad";
    case "interactive_only":
      return value === true ? "warn" : "neutral";
    case CLUSTER_JOB_FACT:
      return value === null ? "warn" : "ok";
    default:
      return "neutral";
  }
}

/** A value as the page prints it: speedups as 100x, an unmeasured one as "not measured", infinity as "no limit". */
export function formatFactValue(fact: Fact): string {
  const { value, unit } = fact;
  if (value === null) {
    return fact.key === "max_speedup" || fact.key === "exact_up_to_speedup" ? "not measured" : "none";
  }
  if (value === UNBOUNDED) {
    return "no limit";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  const text = typeof value === "number" ? value.toLocaleString("en-US") : String(value);
  if (unit === "x") {
    return `${text}x`;
  }
  return unit ? `${text} ${unit}` : text;
}

/** The facts a card shows as chips: in this order when present, otherwise the first capability facts. */
const CARD_FACT_KEYS = ["repeatability_tier", "max_speedup", "wind", "waves"] as const;

export function cardFacts(owner: { facts: Fact[] }): Fact[] {
  const byKey = new Map(owner.facts.map((fact) => [fact.key, fact]));
  const preferred = CARD_FACT_KEYS.map((key) => byKey.get(key)).filter((fact): fact is Fact => fact !== undefined);
  if (preferred.length > 0) {
    return preferred;
  }
  return owner.facts.filter((fact) => fact.group === "capability").slice(0, 2);
}

/** The standard chips are short enough for two to a row; other facts (a name, a description of the randomness) get a row each. */
export function chipsPerRow(chips: readonly Fact[]): number {
  return chips.every((fact) => (CARD_FACT_KEYS as readonly string[]).includes(fact.key)) ? 2 : 1;
}

export function factsByGroup(facts: readonly Fact[]): Record<Fact["group"], Fact[]> {
  return {
    capability: facts.filter((fact) => fact.group === "capability"),
    parameter: facts.filter((fact) => fact.group === "parameter"),
    property: facts.filter((fact) => fact.group === "property"),
  };
}

export function measuredCount(owner: { facts: readonly Fact[] }): number {
  return owner.facts.filter((fact) => fact.measured).length;
}

/** The ids reachable from `start` along `edges`, following them forward and backward, `start` included. */
export function connectedIds(edges: readonly { source: string; target: string }[], start: string): { nodes: Set<string>; edges: Set<number> } {
  const nodes = new Set<string>([start]);
  const used = new Set<number>();
  for (const direction of ["forward", "backward"] as const) {
    const queue = [start];
    const seen = new Set<string>([start]);
    while (queue.length > 0) {
      const current = queue.shift() as string;
      edges.forEach((edge, index) => {
        const from = direction === "forward" ? edge.source : edge.target;
        const to = direction === "forward" ? edge.target : edge.source;
        if (from !== current) {
          return;
        }
        used.add(index);
        nodes.add(to);
        if (!seen.has(to)) {
          seen.add(to);
          queue.push(to);
        }
      });
    }
  }
  return { nodes, edges: used };
}

/** The ends of an edge: all the highlighting and spacing needs of it. */
export interface EdgeEnds {
  id: string;
  source: string;
  target: string;
}

export interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
}

/** What stays lit when a node is selected: everything on a path through it. An edge selects its two ends and what they reach. */
export function highlightFor(edges: readonly EdgeEnds[], selection: { kind: "node" | "edge"; id: string } | null): Highlight | null {
  if (selection === null) {
    return null;
  }
  const starts = selection.kind === "node" ? [selection.id] : edges.filter((edge) => edge.id === selection.id).flatMap((edge) => [edge.source, edge.target]);
  const lit: Highlight = { nodes: new Set(starts), edges: new Set() };
  for (const start of starts) {
    const reached = connectedIds(edges, start);
    reached.nodes.forEach((id) => lit.nodes.add(id));
    reached.edges.forEach((index) => lit.edges.add(edges[index].id));
  }
  return lit;
}

/** Edges from one node to the next, grouped by their ends, so parallel adapters can be drawn apart. */
export function parallelIndex(edges: readonly EdgeEnds[]): Map<string, { index: number; count: number }> {
  const groups = new Map<string, string[]>();
  for (const edge of edges) {
    const key = `${edge.source}>${edge.target}`;
    groups.set(key, [...(groups.get(key) ?? []), edge.id]);
  }
  const placed = new Map<string, { index: number; count: number }>();
  groups.forEach((ids) => ids.forEach((id, index) => placed.set(id, { index, count: ids.length })));
  return placed;
}

/** The available stacks through a node (all of them without one), in the document's order. */
export function stacksThrough(document: ArchitectureDocument, nodeId: string | null): Combination[] {
  return document.combinations.filter((combination) => combination.status === "available" && (nodeId === null || combination.path.includes(nodeId)));
}

/** The cluster job fact of a stack; undefined when the document does not say (an older master, or a stack that is not available). */
export function clusterJobOf(combination: Combination): Fact | undefined {
  return combination.facts.find((fact) => fact.key === CLUSTER_JOB_FACT);
}

/** How many available stacks a cluster job runs, or null when the document names no cluster jobs. */
export function stacksRunAsJobs(document: ArchitectureDocument): number | null {
  const described = document.combinations.map(clusterJobOf).filter((fact): fact is Fact => fact !== undefined);
  return described.length === 0 ? null : described.filter((fact) => fact.value !== null).length;
}

export interface MatrixCell {
  combination: Combination;
  /** The reason a ruled-out connection gives, when the document names one for the pair that breaks the chain. */
  reason: string | null;
}

export interface MatrixRow {
  key: string;
  upper: ArchitectureNode;
  middle: ArchitectureNode;
  cells: Map<string, MatrixCell>;
}

export interface Matrix {
  columns: ArchitectureNode[];
  rows: MatrixRow[];
}

/** The availability matrix of a three-lane document: one row per (first lane, second lane) pair, one column per node of the last lane. */
export function buildMatrix(document: ArchitectureDocument): Matrix | null {
  if (document.combinations.length === 0 || document.lanes.length !== 3) {
    return null;
  }
  const [first, second, last] = document.lanes.map((lane) => document.nodes.filter((node) => node.lane === lane.id));
  const ruledOut = new Map(document.unsupported.map((link) => [`${link.source}>${link.target}`, link.reason]));
  const byPath = new Map(document.combinations.map((combination) => [combination.path.join(">"), combination]));
  const rows: MatrixRow[] = [];
  for (const upper of first) {
    for (const middle of second) {
      const cells = new Map<string, MatrixCell>();
      for (const lower of last) {
        const combination = byPath.get([upper.id, middle.id, lower.id].join(">"));
        if (combination) {
          cells.set(lower.id, { combination, reason: ruledOut.get(`${upper.id}>${middle.id}`) ?? ruledOut.get(`${middle.id}>${lower.id}`) ?? null });
        }
      }
      rows.push({ key: `${upper.id}>${middle.id}`, upper, middle, cells });
    }
  }
  return { columns: last, rows };
}

/** The last path segment of an id: "simulation_layer/gazebo" is "gazebo". */
export function shortId(id: string): string {
  const slash = id.lastIndexOf("/");
  return slash < 0 ? id : id.slice(slash + 1);
}

/** "snake_case" as words. */
export function words(text: string): string {
  return text.replace(/_/g, " ");
}

// The chain: how the parts follow each other, for the page's overview

/** The id of the overview among the page's tabs; no document has it. */
export const OVERVIEW_ID = "overview";

/** A part as the overview names it. */
export interface ChainPart {
  document: ArchitectureDocument;
  /** The step's place in the chain, from 1; null for a supporting part. */
  number: number | null;
  /** The step it performs ("Simulation"), or the part's title when the master names none. */
  name: string;
  /** The part's own title when it differs from the step ("Vessel stack" performs "Simulation"); null otherwise. */
  partName: string | null;
}

export interface Chain {
  /** The parts that each perform one step, in the order the master lists them: the order of the chain. */
  steps: ChainPart[];
  /** The parts that serve the steps (monitoring). */
  support: ChainPart[];
  /** Whether the master says what the steps hand to each other; false for a master from before the overview. */
  described: boolean;
}

export function chainOf(documents: readonly ArchitectureDocument[]): Chain {
  const part = (document: ArchitectureDocument, number: number | null): ChainPart => {
    const name = document.step.trim() || document.title;
    return { document, number, name, partName: name === document.title ? null : document.title };
  };
  const steps = documents.filter((document) => document.role === "step").map((document, index) => part(document, index + 1));
  const support = documents.filter((document) => document.role !== "step").map((document) => part(document, null));
  return { steps, support, described: documents.some((document) => document.takes !== "" || document.gives !== "") };
}

/** How many implementations a part has and how many of its values were measured. */
export function partCounts(document: ArchitectureDocument): { implementations: number; measured: number } {
  return { implementations: document.nodes.length, measured: [...document.nodes, ...document.edges].reduce((sum, item) => sum + measuredCount(item), 0) };
}

/** What a list of machines offers of one job type, as the overview needs it. */
export interface JobOffer {
  jobType: string;
  /** Machines that can run the job type now, and their slots for it. */
  machines: number;
  slots: number;
}

/**
 * What the selected cluster says about a part: the offers per job type that runs it, or why nothing
 * is known (no cluster, not read yet, unreachable). `known` is false while the answer may still change.
 */
export interface PartOffer {
  known: boolean;
  /** A line for the card: "2 slots on 1 machine", "no machine offers it", "the cluster cannot be reached". */
  text: string;
  tone: Tone;
  offers: JobOffer[];
}

export function describePartOffer(state: { selected: boolean; loaded: boolean; unreachable: boolean }, offers: readonly JobOffer[]): PartOffer {
  if (!state.selected) {
    return { known: false, text: "no cluster selected", tone: "neutral", offers: [] };
  }
  if (state.unreachable) {
    return { known: false, text: "the cluster cannot be reached", tone: "warn", offers: [] };
  }
  if (!state.loaded) {
    return { known: false, text: "reading the machines", tone: "neutral", offers: [] };
  }
  if (offers.length === 0) {
    return { known: false, text: "not stated by this master", tone: "neutral", offers: [] };
  }
  const machines = Math.max(...offers.map((offer) => offer.machines));
  const slots = offers.reduce((sum, offer) => sum + offer.slots, 0);
  if (machines === 0) {
    return { known: true, text: "no machine offers it", tone: "warn", offers: [...offers] };
  }
  return { known: true, text: `${slots} slot${slots === 1 ? "" : "s"} on ${machines} machine${machines === 1 ? "" : "s"}`, tone: "ok", offers: [...offers] };
}
