import type { ArchitectureDocument, Fact } from "../../domain/cluster/architectureApi";

export function fact(key: string, value: Fact["value"], overrides: Partial<Fact> = {}): Fact {
  return { key, label: key.replace(/_/g, " "), value, group: "capability", measured: false, unit: null, note: null, ...overrides };
}

/** A small document in the shape the backend writes: three lanes, a ruled-out connection, two adapters on one pair, and the matrix over all combinations. */
export function sampleStackDocument(): ArchitectureDocument {
  const node = (id: string, lane: string, facts: Fact[] = [], extra: Partial<ArchitectureDocument["nodes"][number]> = {}): ArchitectureDocument["nodes"][number] => ({
    id,
    lane,
    label: id.split("/")[1],
    description: `${id} description`,
    implements: `stack/layer/${lane}`,
    status: "available",
    facts,
    ports_provided: [],
    ports_required: [],
    tags: [],
    evidence: "",
    ...extra,
  });
  const edge = (id: string, source: string, target: string, extra: Partial<ArchitectureDocument["edges"][number]> = {}): ArchitectureDocument["edges"][number] => ({
    id,
    source,
    target,
    label: id,
    description: `${id} description`,
    implements: "stack/adapter/upper",
    kind: "adapter",
    status: "available",
    default: true,
    facts: [],
    ports_provided: [],
    ports_required: [],
    tags: [],
    evidence: "",
    ...extra,
  });
  const exact = [fact("repeatability_tier", "exact"), fact("max_speedup", "unbounded", { unit: "x" }), fact("wind", "unsupported"), fact("waves", "supported", { measured: true })];
  // An available combination names the cluster job that runs it, or none (a workbench live session)
  const clusterJob = (jobType: string | null) =>
    fact("cluster_job", jobType, { label: "Cluster job", group: "property", note: jobType === null ? "no job type runs it yet" : "runs as this job on a node" });
  const combination = (path: string[], status: string, reasons: string[] = [], jobType: string | null = null) => ({
    path,
    status,
    reasons,
    facts: status === "available" ? [...exact, clusterJob(jobType)] : [],
  });
  return {
    schema_version: 1,
    id: "stack",
    title: "Stack",
    summary: "A stack of three layers.",
    lanes: [
      { id: "top", label: "Top", description: "The top layer." },
      { id: "middle", label: "Middle", description: "The middle layer." },
      { id: "bottom", label: "Bottom", description: "The bottom layer." },
    ],
    metamodel_nodes: ["top", "middle", "bottom"].map((lane) => ({
      id: `stack/layer/${lane}`,
      lane,
      label: `${lane} layer`,
      description: `The generic ${lane} layer.`,
      kind: "role",
      members: [`${lane}.run()`],
      extension: `Add a ${lane}.`,
      code: `pkg/${lane}.py`,
    })),
    metamodel_edges: [
      { id: "stack/adapter/upper", source: "stack/layer/top", target: "stack/layer/middle", label: "upper adapter", description: "", kind: "adapter", members: ["AdapterSpec"], extension: null, code: null },
      { id: "stack/adapter/lower", source: "stack/layer/middle", target: "stack/layer/bottom", label: "lower adapter", description: "", kind: "adapter", members: [], extension: null, code: null },
    ],
    nodes: [
      node("top/a", "top", exact, { tags: ["in-process"] }),
      node("top/b", "top", [fact("repeatability_tier", "none")]),
      node("middle/c", "middle", exact),
      node("middle/d", "middle", [], { status: "planned" }),
      node("bottom/e", "bottom", exact, { evidence: "Measured on a 12-core host." }),
      node("bottom/f", "bottom", [fact("repeatability_tier", "bounded"), fact("max_speedup", null, { unit: "x" })]),
    ],
    edges: [
      edge("a_to_c", "top/a", "middle/c"),
      edge("a_to_c_alt", "top/a", "middle/c", { default: false, tags: ["alternative"] }),
      edge("b_to_c", "top/b", "middle/c"),
      edge("c_to_e", "middle/c", "bottom/e", { implements: "stack/adapter/lower", facts: [fact("repeatability_tier", "bounded", { measured: true })] }),
      edge("c_to_f", "middle/c", "bottom/f", { implements: "stack/adapter/lower" }),
    ],
    unsupported: [{ source: "middle/d", target: "bottom/e", reason: "d has no adapter to e" }],
    combinations: [
      combination(["top/a", "middle/c", "bottom/e"], "available", [], "sim.e"),
      combination(["top/a", "middle/c", "bottom/f"], "available", [], "sim.f"),
      combination(["top/b", "middle/c", "bottom/e"], "available"),
      combination(["top/b", "middle/c", "bottom/f"], "available"),
      combination(["top/a", "middle/d", "bottom/e"], "unavailable", ["no adapter from top/a to middle/d"]),
      combination(["top/b", "middle/d", "bottom/f"], "planned"),
    ],
    notes: ["A note on the stack."],
    role: "step",
    step: "Stacking",
    takes: "parts",
    gives: "a stack",
    job_types: ["simulation"],
  };
}

/** The same document as a master from before the overview writes it: without its place in the chain. */
export function sampleStackDocumentWithoutChain(): Record<string, unknown> {
  const document: Record<string, unknown> = { ...sampleStackDocument() };
  for (const key of ["role", "step", "takes", "gives", "job_types"]) {
    delete document[key];
  }
  return document;
}
