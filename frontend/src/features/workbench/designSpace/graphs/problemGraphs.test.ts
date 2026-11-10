import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { readProblem } from "../../../../domain/designSpace/problemModel";
import { borderPoint, linePath, loopPath, placeEdges, type Box, type Point } from "./graphGeometry";
import { classId, enumId, layoutMetamodel, MAX_PER_ROW, metamodelGraph, metamodelSummary } from "./metamodelLayout";
import { layoutModel, modelGraph, modelSummary, objectId, OBJECT_WIDTH } from "./modelLayout";

const BACKEND = resolve(__dirname, "../../../../../../backend");
const DEFAULT_SPECIFICATION = readFileSync(resolve(BACKEND, "assets/design_space/default_specification.problem"), "utf8");
const GENERATED_MODEL = readFileSync(resolve(BACKEND, "src/tests/scenegems_tool/subsystems/design_space_exploration/data/generated_model.problem"), "utf8");

const STATECHART = `abstract class Vertex {
    Transition[0..*] outgoing opposite source
}
class Transition {
    Vertex[1] source opposite outgoing
    Vertex[1] target
}
class State extends Vertex, Named {
    contains Region[0..*] regions
    Kind[1] kind
    int depth
}
class Region {
    container State owner opposite regions
}
class Pseudo extends Vertex.
enum Kind { Simple, Composite }
pred reachable(Vertex a, Vertex b) <-> outgoing(a, t), target(t, b).
error noInitial() <-> !Pseudo(_).
`;

function boxes(cards: { id: string; width: number; height: number }[], positions: Map<string, Point>): Box[] {
  return cards.map((card) => ({ ...(positions.get(card.id) as Point), width: card.width, height: card.height }));
}

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function expectNoOverlap(all: Box[]) {
  for (let i = 0; i < all.length; i++) {
    for (let j = i + 1; j < all.length; j++) {
      expect(overlaps(all[i], all[j]), `cards ${i} and ${j} overlap`).toBe(false);
    }
  }
}

describe("the metamodel graph", () => {
  const graph = metamodelGraph(readProblem(STATECHART).metamodel);

  it("has a card per class, one for a class only used, and one per enum", () => {
    expect(graph.cards.map((card) => card.id)).toEqual([classId("Vertex"), classId("Transition"), classId("State"), classId("Region"), classId("Pseudo"), classId("Named"), enumId("Kind")]);
    const state = graph.cards.find((card) => card.id === classId("State"));
    expect(state).toMatchObject({
      rows: [
        { name: "kind", type: "Kind", multiplicity: "1" },
        { name: "depth", type: "int", multiplicity: null },
      ],
    });
    expect(graph.cards.find((card) => card.id === classId("Named"))).toMatchObject({ defined: false });
    expect(graph.cards.find((card) => card.id === enumId("Kind"))).toMatchObject({ literals: ["Simple", "Composite"] });
  });

  it("draws inheritance, references, containment and an opposite pair as one edge", () => {
    expect(graph.edges.map((edge) => [edge.kind, edge.source, edge.target, edge.label, edge.twoWay, edge.diamond])).toEqual([
      ["reference", classId("Vertex"), classId("Transition"), "", true, null],
      ["reference", classId("Transition"), classId("Vertex"), "target [1]", false, null],
      ["extends", classId("State"), classId("Vertex"), "", false, null],
      ["extends", classId("State"), classId("Named"), "", false, null],
      ["contains", classId("State"), classId("Region"), "", true, "source"],
      ["extends", classId("Pseudo"), classId("Vertex"), "", false, null],
    ]);
    // Each name of an opposite pair sits next to the class it leads to
    expect(graph.edges[0].endLabels).toEqual({ source: "source [1]", target: "outgoing [0..*]" });
    // Only Region names the opposite; the pair is still one edge
    expect(graph.edges[4].endLabels).toEqual({ source: "owner", target: "regions [0..*]" });
  });

  it("draws a reference that is its own opposite as one loop", () => {
    const vessel = metamodelGraph(readProblem(DEFAULT_SPECIFICATION).metamodel);
    const loops = vessel.edges.filter((edge) => edge.source === classId("Vessel") && edge.target === classId("Vessel"));
    expect(loops.map((edge) => [edge.label, edge.twoWay])).toEqual([
      ["overtakingToPort [0..*]", false],
      ["overtakingToStarboard [0..*]", false],
      ["crossingFromPort [0..*]", false],
      ["headOn [0..*]", true],
    ]);
    // Room for its loops
    const card = vessel.cards.find((item) => item.id === classId("Vessel"));
    expect(card?.height).toBeGreaterThanOrEqual(4 * 26);
    expect(card?.layoutWidth).toBeGreaterThan(card?.width ?? 0);
  });

  it("sums the metamodel up", () => {
    expect(metamodelSummary(readProblem(STATECHART).metamodel)).toBe("5 classes, 1 enum, 1 predicate, 1 constraint, 1 class used but not defined here.");
    expect(metamodelSummary(readProblem(DEFAULT_SPECIFICATION).metamodel)).toBe("4 classes, 1 enum, 5 predicates, 7 constraints.");
    expect(metamodelSummary(readProblem("problem fs.\n#datatype Money.\nrule r() ==> .\nclass A.\n").metamodel)).toBe("Module fs: 1 class, 0 enums, 0 predicates, 0 constraints, 1 datatype, 1 rule.");
  });

  it("puts superclasses above their subclasses and the enums below, without overlaps, the same each time", () => {
    const positions = layoutMetamodel(graph);
    const y = (id: string) => (positions.get(id) as Point).y;
    expect(y(classId("Vertex"))).toBeLessThan(y(classId("State")));
    expect(y(classId("Named"))).toBeLessThan(y(classId("State")));
    expect(y(classId("Vertex"))).toBeLessThan(y(classId("Pseudo")));
    for (const card of graph.cards.filter((item) => item.kind === "class")) {
      expect(y(enumId("Kind"))).toBeGreaterThan(y(card.id));
    }
    expectNoOverlap(boxes(graph.cards, positions));
    expect(layoutMetamodel(metamodelGraph(readProblem(STATECHART).metamodel))).toEqual(positions);
  });

  it("wraps a wide layer and still keeps the cards apart", () => {
    const text = Array.from({ length: 20 }, (_, index) => `class C${index} { C${(index + 1) % 20}[0..1] next }`).join("\n");
    const wide = metamodelGraph(readProblem(text).metamodel);
    const positions = layoutMetamodel(wide);
    const rows = new Set([...positions.values()].map((point) => point.y));
    expect(rows.size).toBe(Math.ceil(20 / MAX_PER_ROW));
    expectNoOverlap(boxes(wide.cards, positions));
  });

  it("survives an inheritance cycle", () => {
    const cyclic = metamodelGraph(readProblem("class A extends B.\nclass B extends A.\n").metamodel);
    expect(() => layoutMetamodel(cyclic)).not.toThrow();
    expectNoOverlap(boxes(cyclic.cards, layoutMetamodel(cyclic)));
  });
});

describe("the model graph", () => {
  it("has a card per object with its types and values, and an edge per link", () => {
    const read = readProblem(GENERATED_MODEL);
    const graph = modelGraph(read);
    expect(graph.cards.map((card) => [card.name, card.types, card.tone])).toEqual([
      ["os", ["OS"], 1],
      ["tS1", ["TS"], 2],
      ["staticObstacle1", ["StaticObstacle"], 3],
      ["tS2", ["TS"], 2],
    ]);
    expect(graph.cards[0].values).toEqual([{ relation: "vesselType", value: "OSPassengerShip", kind: "enum", possible: false }]);
    expect(graph.edges.map((edge) => [edge.source, edge.target, edge.label, edge.twoWay])).toEqual([
      [objectId("tS1"), objectId("os"), "overtakingToPort", false],
      [objectId("staticObstacle1"), objectId("os"), "atDangerousHeadOnSectorOf", false],
      [objectId("os"), objectId("tS2"), "headOn", true],
    ]);
    expect(modelSummary(read)).toBe("4 objects, 3 links.");
  });

  it("says what it does not draw", () => {
    expect(modelSummary(readProblem("declare a, b, c.\nr(a, b).\n?s(b, a).\nbetween(a, b, c).\n"))).toBe("3 objects, 2 links, 1 of them possible. 1 fact of more than two objects (between) is not drawn.");
  });

  it("puts the object with the most links in the middle, whatever the names", () => {
    const one = layoutModel(modelGraph(readProblem("declare x, hub, y, z.\nr(x, hub).\nr(hub, y).\nr(z, hub).\n")));
    expect(one.get(objectId("hub"))).toEqual({ x: -OBJECT_WIDTH / 2, y: expect.any(Number) });
    const renamed = layoutModel(modelGraph(readProblem("declare a, b, c, d.\nr(a, b).\nr(b, c).\nr(d, b).\n")));
    expect([...renamed.values()]).toEqual([...one.values()]);
  });

  it("never overlaps two cards, also for 30 objects with links and one apart", () => {
    const names = Array.from({ length: 30 }, (_, index) => `o${index}`);
    const links = names.slice(1, 25).map((name, index) => `link(${names[Math.floor(index / 4)]}, ${name}).`);
    const text = `enum E { V }\ndeclare ${names.join(", ")}.\n${links.join("\n")}\nvalue(o3, V).\nself(o4, o4).\n`;
    const graph = modelGraph(readProblem(text));
    const positions = layoutModel(graph);
    expect(positions.size).toBe(30);
    expectNoOverlap(boxes(graph.cards, positions));
    expect(layoutModel(modelGraph(readProblem(text)))).toEqual(positions);
  });

  it("lays out an empty model and a single object", () => {
    expect(layoutModel(modelGraph(readProblem(""))).size).toBe(0);
    expect(layoutModel(modelGraph(readProblem("declare only.\n")))).toEqual(new Map([[objectId("only"), { x: -OBJECT_WIDTH / 2, y: expect.any(Number) }]]));
  });
});

describe("the edge geometry", () => {
  const a: Box = { x: 0, y: 0, width: 100, height: 50 };
  const b: Box = { x: 300, y: 0, width: 100, height: 50 };

  it("leaves a card where the line to the other card crosses its border", () => {
    expect(borderPoint(a, { x: 350, y: 25 })).toEqual({ x: 100, y: 25 });
    expect(borderPoint(a, { x: 50, y: 500 })).toEqual({ x: 50, y: 50 });
  });

  it("bows the edges between the same two cards apart, in both directions", () => {
    const placement = placeEdges([
      { id: "1", source: "a", target: "b" },
      { id: "2", source: "b", target: "a" },
      { id: "3", source: "a", target: "a" },
      { id: "4", source: "a", target: "a" },
    ]);
    expect(placement.get("1")).toEqual({ kind: "line", offset: -20 });
    expect(placement.get("2")).toEqual({ kind: "line", offset: 20 });
    expect(placement.get("4")).toEqual({ kind: "loop", index: 1, count: 2 });
    const forth = linePath(a, b, -20, true);
    const back = linePath(b, a, 20, false);
    expect(forth.labelY).toBeCloseTo(back.labelY * -1 + 50);
    expect(forth.labelY).not.toBeCloseTo(back.labelY);
    expect(linePath(a, b, 0, true).path).toBe("M 100,25 L 300,25");
  });

  it("loops out of the right side of a card", () => {
    const loop = loopPath(a, 0, 1);
    expect(loop.path.startsWith("M 100,")).toBe(true);
    expect(loop.labelX).toBeGreaterThan(100);
  });
});
