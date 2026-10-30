import { describe, expect, it } from "vitest";
import { fact, sampleStackDocument } from "../../test/fixtures/architectureDocuments";
import {
  buildMatrix,
  cardFacts,
  CLUSTER_JOB_FACT,
  clusterJobOf,
  connectedIds,
  factsByGroup,
  factTone,
  formatFactValue,
  highlightFor,
  parallelIndex,
  shortId,
  stacksRunAsJobs,
  stacksThrough,
  words,
} from "./capabilitiesModel";

describe("fact tones", () => {
  it("rates repeatability, environment support and the lockstep flags", () => {
    expect(factTone(fact("repeatability_tier", "exact"))).toBe("ok");
    expect(factTone(fact("repeatability_tier", "bounded"))).toBe("warn");
    expect(factTone(fact("repeatability_tier", "none"))).toBe("bad");
    expect(factTone(fact("wind", "supported"))).toBe("ok");
    expect(factTone(fact("waves", "unmeasured"))).toBe("warn");
    expect(factTone(fact("waves", "unsupported"))).toBe("bad");
    expect(factTone(fact("lockstep", true))).toBe("ok");
    expect(factTone(fact("faster_than_real_time", false))).toBe("bad");
    expect(factTone(fact("interactive_only", true))).toBe("warn");
    expect(factTone(fact("interactive_only", false))).toBe("neutral");
    expect(factTone(fact("anything_else", "x"))).toBe("neutral");
  });
});

describe("fact values", () => {
  it("prints speedups, limits, booleans and a value that was not measured", () => {
    expect(formatFactValue(fact("max_speedup", 100, { unit: "x" }))).toBe("100x");
    expect(formatFactValue(fact("max_speedup", "unbounded", { unit: "x" }))).toBe("no limit");
    expect(formatFactValue(fact("max_speedup", null, { unit: "x" }))).toBe("not measured");
    expect(formatFactValue(fact("lockstep", true))).toBe("yes");
    expect(formatFactValue(fact("interactive_only", false))).toBe("no");
    expect(formatFactValue(fact("throughput", 1425, { unit: "scenes/s per core" }))).toBe("1,425 scenes/s per core");
    expect(formatFactValue(fact("early_stop", null))).toBe("none");
  });

  it("groups facts and picks the chips of a card", () => {
    const facts = [fact("a", 1), fact("b", 2, { group: "parameter" }), fact("c", 3, { group: "property" })];
    const grouped = factsByGroup(facts);
    expect([grouped.capability.length, grouped.parameter.length, grouped.property.length]).toEqual([1, 1, 1]);
    expect(cardFacts({ facts: [fact("wind", "supported"), fact("repeatability_tier", "exact"), fact("lockstep", true)] }).map((item) => item.key)).toEqual(["repeatability_tier", "wind"]);
    expect(cardFacts({ facts: [fact("one", 1), fact("two", 2), fact("three", 3), fact("p", 4, { group: "parameter" })] }).map((item) => item.key)).toEqual(["one", "two"]);
  });
});

describe("highlighting", () => {
  const document = sampleStackDocument();

  it("follows the edges both ways from a node", () => {
    const reached = connectedIds(document.edges, "middle/c");
    expect([...reached.nodes].sort()).toEqual(["bottom/e", "bottom/f", "middle/c", "top/a", "top/b"]);
  });

  it("lights what is on a path through the selected node and dims the rest", () => {
    const lit = highlightFor(document.edges, { kind: "node", id: "top/b" });
    expect([...(lit?.nodes ?? [])].sort()).toEqual(["bottom/e", "bottom/f", "middle/c", "top/b"]);
    expect(lit?.edges.has("a_to_c")).toBe(false);
    expect(lit?.edges.has("b_to_c")).toBe(true);
  });

  it("lights both ends of a selected edge and what they reach", () => {
    const lit = highlightFor(document.edges, { kind: "edge", id: "c_to_e" });
    expect(lit?.nodes.has("middle/c") && lit.nodes.has("bottom/e") && lit.nodes.has("top/a")).toBe(true);
    expect(highlightFor(document.edges, null)).toBeNull();
  });

  it("lights nothing else for a node with no edges", () => {
    const lit = highlightFor(document.edges, { kind: "node", id: "middle/d" });
    expect([...(lit?.nodes ?? [])]).toEqual(["middle/d"]);
    expect(lit?.edges.size).toBe(0);
  });
});

describe("parallel edges", () => {
  it("numbers the edges between the same two nodes", () => {
    const placed = parallelIndex(sampleStackDocument().edges);
    expect(placed.get("a_to_c")).toEqual({ index: 0, count: 2 });
    expect(placed.get("a_to_c_alt")).toEqual({ index: 1, count: 2 });
    expect(placed.get("b_to_c")).toEqual({ index: 0, count: 1 });
  });
});

describe("stacks and the matrix", () => {
  const document = sampleStackDocument();

  it("lists the available stacks through a node", () => {
    expect(stacksThrough(document, "top/b").map((stack) => stack.path.join(">"))).toEqual(["top/b>middle/c>bottom/e", "top/b>middle/c>bottom/f"]);
    expect(stacksThrough(document, null)).toHaveLength(4);
    expect(stacksThrough(document, "middle/d")).toEqual([]);
  });

  it("builds one row per upper and middle pair with the ruled-out reason on the broken cell", () => {
    const matrix = buildMatrix(document);
    expect(matrix?.columns.map((column) => column.id)).toEqual(["bottom/e", "bottom/f"]);
    expect(matrix?.rows.map((row) => row.key)).toEqual(["top/a>middle/c", "top/a>middle/d", "top/b>middle/c", "top/b>middle/d"]);
    const broken = matrix?.rows[1].cells.get("bottom/e");
    expect(broken?.combination.status).toBe("unavailable");
    expect(broken?.reason).toBe("d has no adapter to e");
    expect(matrix?.rows[0].cells.get("bottom/f")?.combination.status).toBe("available");
  });

  it("has no matrix for a document without combinations", () => {
    expect(buildMatrix({ ...document, combinations: [] })).toBeNull();
  });
});

describe("cluster jobs", () => {
  const document = sampleStackDocument();

  it("reads the job type that runs an available stack, none for a workbench stack, nothing for one that is not available", () => {
    expect(clusterJobOf(document.combinations[0])?.value).toBe("sim.e");
    expect(clusterJobOf(document.combinations[2])?.value).toBeNull();
    expect(clusterJobOf(document.combinations[4])).toBeUndefined();
  });

  it("counts the stacks a cluster job runs, and nothing for a document of an older master", () => {
    expect(stacksRunAsJobs(document)).toBe(2);
    const older = { ...document, combinations: document.combinations.map((combination) => ({ ...combination, facts: combination.facts.filter((fact) => fact.key !== CLUSTER_JOB_FACT) })) };
    expect(stacksRunAsJobs(older)).toBeNull();
  });

  it("rates a stack without a cluster job amber", () => {
    expect(factTone(fact(CLUSTER_JOB_FACT, "simulation.gazebo"))).toBe("ok");
    expect(factTone(fact(CLUSTER_JOB_FACT, null))).toBe("warn");
  });
});

describe("text helpers", () => {
  it("shortens ids and spaces snake case", () => {
    expect(shortId("simulation_layer/gazebo")).toBe("gazebo");
    expect(shortId("plain")).toBe("plain");
    expect(words("usv_navigation_in_process")).toBe("usv navigation in process");
  });
});
