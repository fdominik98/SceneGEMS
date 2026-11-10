import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { describeLink, readProblem, relationWords } from "./problemModel";

// The real grammar reads every text here: the backend's default specification, a generated model and a
// catalog FEC, and hand-written texts that have nothing to do with ships.

const BACKEND = resolve(__dirname, "../../../../backend");
const read = (path: string) => readFileSync(resolve(BACKEND, path), "utf8");
const DEFAULT_SPECIFICATION = read("assets/design_space/default_specification.problem");
const GENERATED_MODEL = read("src/tests/scenegems_tool/subsystems/design_space_exploration/data/generated_model.problem");
const CATALOG_FEC = read("assets/generated_functional_models/all/3vessel_1obstacle_scenarios/fec0.problem");

/** A file system: modules, imports, every kind of comment, quoted ids, annotations, multiple inheritance, containment and opposites. */
const FILE_SYSTEM = `% A file system, as a line comment of the percent kind
module filesystem.
import builtin::strategy as s.

// The entries
/* a block
   comment */
abstract class Entry {
    string name
    int[0..1] size
    container Folder parent opposite entries
}

class Folder extends Entry {
    contains Entry[0..*] entries opposite parent
}

class 'Data File' extends Entry, Shareable {
    refers User[1..*] owners opposite files
    Permission[1] permission
}

class User {
    'Data File'[0..*] files opposite owners
    User[0..1] manager
}

enum Permission { Read, Write, Execute }

#datatype Money.

@doc("anything shared")
error pred orphan(Entry e) <-> !parent(e, _).
error noRoot() <-> !Folder(_).
shadow pred deep(Entry e) <-> parent(e, p), parent(p, _).
pred owned(User u, 'Data File' f) <-> owners(f, u).
int depth(Entry e) = 0.
decision rule share(f) ==> owners(f, *).

declare root, docs, alice.
atom bob.
Folder(root).
Folder(docs).
'Data File'(report).
User(alice).
entries(root, docs).
parent(docs, root).
entries(docs, report).
owners(report, alice).
?owners(report, bob).
manager(alice, alice).
permission(report, Permission::Write).
name(root): "/".
size(report): 42.
?Shareable(report).
!manager(bob, alice).
default !manager(*, *).
grants(alice, bob, report).
!exists(Folder::new).
equals(alice, alice).

scope Entry = 3..10, User += 2.
`;

/** A statechart, with an `opposite` reference to itself, an enum valued feature and a placeholder object. */
const STATECHART = `class Region {
    contains State[1..*] states
}
class State {
    State[0..*] next
    State[0..*] linked opposite linked
    Kind[1] kind
}
enum Kind { Initial, Normal, Final }

declare r, a, b, c.
Region(r). State(a). State(b). State(c).
states(r, a). states(r, b). states(r, c).
next(a, b). next(b, c).
linked(a, c). linked(c, a).
kind(a, Initial).
!exists(State::new).
default !next(*, *).
`;

describe("the metamodel of a text", () => {
  it("reads the classes, features, enums, predicates and other declarations of a non-ship metamodel", () => {
    const { metamodel, syntax } = readProblem(FILE_SYSTEM);
    expect(syntax).toEqual({ errorCount: 0, firstErrorLine: null });
    expect(metamodel.classes.map((item) => [item.name, item.abstract, item.superclasses, item.defined])).toEqual([
      ["Entry", true, [], true],
      ["Folder", false, ["Entry"], true],
      ["Data File", false, ["Entry", "Shareable"], true],
      ["User", false, [], true],
      // Used as a supertype, never defined
      ["Shareable", false, [], false],
    ]);
    const entry = metamodel.classes[0];
    expect(entry.features).toEqual([
      { name: "name", type: "string", multiplicity: null, kind: "plain", opposite: null, subsets: [], target: "datatype" },
      { name: "size", type: "int", multiplicity: "0..1", kind: "plain", opposite: null, subsets: [], target: "datatype" },
      { name: "parent", type: "Folder", multiplicity: null, kind: "container", opposite: "entries", subsets: [], target: "class" },
    ]);
    expect(metamodel.classes[1].features[0]).toMatchObject({ name: "entries", type: "Entry", multiplicity: "0..*", kind: "contains", opposite: "parent", target: "class" });
    expect(metamodel.classes[2].features).toEqual([
      { name: "owners", type: "User", multiplicity: "1..*", kind: "refers", opposite: "files", subsets: [], target: "class" },
      { name: "permission", type: "Permission", multiplicity: "1", kind: "plain", opposite: null, subsets: [], target: "enum" },
    ]);
    expect(metamodel.classes[3].features.map((feature) => [feature.name, feature.type, feature.target])).toEqual([
      ["files", "Data File", "class"],
      ["manager", "User", "class"],
    ]);
    expect(metamodel.enums).toEqual([{ name: "Permission", literals: ["Read", "Write", "Execute"], line: 28 }]);
    expect(metamodel.predicates.map((item) => [item.name, item.error, item.shadow, item.parameters])).toEqual([
      ["orphan", true, false, [{ name: "e", type: "Entry" }]],
      ["noRoot", true, false, []],
      ["deep", false, true, [{ name: "e", type: "Entry" }]],
      [
        "owned",
        false,
        false,
        [
          { name: "u", type: "User" },
          { name: "f", type: "Data File" },
        ],
      ],
    ]);
    expect(metamodel.declarations.map((item) => [item.kind, item.name])).toEqual([
      ["module", "filesystem"],
      ["import", "builtin::strategy"],
      ["datatype", "Money"],
      ["function", "depth"],
      ["rule", "share"],
    ]);
    expect(metamodel.scopes).toEqual([
      { relation: "Entry", increment: false, multiplicity: "3..10" },
      { relation: "User", increment: true, multiplicity: "2" },
    ]);
  });

  it("reads the default specification of the backend", () => {
    const { metamodel, syntax } = readProblem(DEFAULT_SPECIFICATION);
    expect(syntax.errorCount).toBe(0);
    expect(metamodel.classes.map((item) => item.name)).toEqual(["Vessel", "OS", "TS", "StaticObstacle"]);
    expect(metamodel.classes[0]).toMatchObject({ abstract: true, superclasses: [] });
    expect(metamodel.classes[0].features.find((feature) => feature.name === "headOn")).toMatchObject({ type: "Vessel", multiplicity: "0..*", opposite: "headOn", target: "class" });
    expect(metamodel.classes[1]).toMatchObject({ superclasses: ["Vessel"], features: [expect.objectContaining({ name: "vesselType", target: "enum", multiplicity: "1" })] });
    expect(metamodel.enums[0].literals).toHaveLength(10);
    expect(metamodel.predicates.filter((item) => !item.error).map((item) => item.name)).toEqual(["overtaking", "giveWay", "standOn", "ambiguous", "inCOLREGSSituationWith"]);
    expect(metamodel.predicates.filter((item) => item.error)).toHaveLength(7);
  });

  it("reads a feature with subsets and annotations, and an unclassified type as a class used here", () => {
    const { metamodel } = readProblem("class A {\n  @hidden A[0..*] all;\n  A[] some subsets all\n  Mystery thing\n}\n");
    expect(metamodel.classes[0].features).toEqual([
      { name: "all", type: "A", multiplicity: "0..*", kind: "plain", opposite: null, subsets: [], target: "class" },
      { name: "some", type: "A", multiplicity: "", kind: "plain", opposite: null, subsets: ["all"], target: "class" },
      { name: "thing", type: "Mystery", multiplicity: null, kind: "plain", opposite: null, subsets: [], target: "class" },
    ]);
    expect(metamodel.classes.map((item) => [item.name, item.defined])).toEqual([
      ["A", true],
      ["Mystery", false],
    ]);
  });
});

describe("the model of a text", () => {
  it("reads the objects, types, values and links of a non-ship model", () => {
    const { model } = readProblem(FILE_SYSTEM);
    expect(model.nodes.map((node) => [node.name, node.origin])).toEqual([
      ["root", "declare"],
      ["docs", "declare"],
      ["alice", "declare"],
      ["bob", "atom"],
      ["report", "assertion"],
    ]);
    const report = model.nodes.find((node) => node.name === "report");
    expect(report).toMatchObject({
      types: ["Data File"],
      possibleTypes: ["Shareable"],
      values: [
        { relation: "permission", value: "Write", kind: "enum", possible: false },
        { relation: "size", value: "42", kind: "attribute", possible: false },
      ],
    });
    expect(model.nodes[0].values).toEqual([{ relation: "name", value: '"/"', kind: "attribute", possible: false }]);
    expect(model.links).toEqual([
      { relation: "entries", source: "root", target: "docs", possible: false, twoWay: false },
      { relation: "parent", source: "docs", target: "root", possible: false, twoWay: false },
      { relation: "entries", source: "docs", target: "report", possible: false, twoWay: false },
      { relation: "owners", source: "report", target: "alice", possible: false, twoWay: false },
      { relation: "owners", source: "report", target: "bob", possible: true, twoWay: false },
      { relation: "manager", source: "alice", target: "alice", possible: false, twoWay: false },
    ]);
    expect(model.omitted).toEqual({ negative: 1, defaults: 1, newObjects: 1, builtins: 1, higherArity: 1, other: 0 });
    expect(model.higherArityRelations).toEqual(["grants"]);
  });

  it("keeps a pair in both directions once, values of enum literals on their object, and no placeholder", () => {
    const { model } = readProblem(STATECHART);
    expect(model.nodes.map((node) => node.name)).toEqual(["r", "a", "b", "c"]);
    expect(model.nodes[1]).toMatchObject({ types: ["State"], values: [{ relation: "kind", value: "Initial", kind: "enum" }] });
    expect(model.links.filter((link) => link.relation === "linked")).toEqual([{ relation: "linked", source: "a", target: "c", possible: false, twoWay: true }]);
    expect(model.links).toHaveLength(6);
    expect(model.omitted).toMatchObject({ newObjects: 1, defaults: 1 });
  });

  it("reads the generated model: two declare lines, placeholders, defaults, an enum value and a two-way pair", () => {
    const { model, syntax } = readProblem(GENERATED_MODEL);
    expect(syntax.errorCount).toBe(0);
    expect(model.nodes.map((node) => [node.name, node.types])).toEqual([
      ["os", ["OS"]],
      ["tS1", ["TS"]],
      ["staticObstacle1", ["StaticObstacle"]],
      ["tS2", ["TS"]],
    ]);
    expect(model.nodes[0].values).toEqual([{ relation: "vesselType", value: "OSPassengerShip", kind: "enum", possible: false }]);
    expect(model.links).toEqual([
      { relation: "overtakingToPort", source: "tS1", target: "os", possible: false, twoWay: false },
      { relation: "atDangerousHeadOnSectorOf", source: "staticObstacle1", target: "os", possible: false, twoWay: false },
      { relation: "headOn", source: "os", target: "tS2", possible: false, twoWay: true },
    ]);
    expect(model.omitted).toMatchObject({ newObjects: 3, defaults: 6, higherArity: 0 });
  });

  it("reads a catalog FEC", () => {
    const { model, metamodel, syntax } = readProblem(CATALOG_FEC);
    expect(syntax.errorCount).toBe(0);
    expect(metamodel.classes).toHaveLength(4);
    expect(model.nodes.map((node) => node.name)).toEqual(["os", "ts1", "ts2", "obst1"]);
    expect(model.links.map(describeLink)).toEqual(["ts1 overtaking to starboard os", "os crossing from port ts2", "obst1 at dangerous head on sector of os"]);
  });

  it("takes a fact's logic value after a colon as the prefix would say it", () => {
    const { model } = readProblem("declare a, b.\nr(a, b): true.\ns(a, b): false.\nt(a, b): unknown.\nu(a, b): error.\nready(a): true.\n");
    expect(model.links).toEqual([
      { relation: "r", source: "a", target: "b", possible: false, twoWay: false },
      { relation: "t", source: "a", target: "b", possible: true, twoWay: false },
    ]);
    expect(model.nodes[0].facts).toEqual([{ relation: "ready", possible: false }]);
    expect(model.omitted).toMatchObject({ negative: 1, other: 1 });
  });

  it("reads multi objects and the specification's own objects", () => {
    const { model } = readProblem(`${DEFAULT_SPECIFICATION}\ndeclare multi extra.\n`);
    expect(model.nodes.map((node) => [node.name, node.origin])).toEqual([
      ["os", "declare"],
      ["extra", "multi"],
    ]);
  });
});

describe("a text with syntax errors", () => {
  it("reports an unclosed class body and still reads what precedes and follows it", () => {
    const { metamodel, syntax } = readProblem("class A {\n  A[0..*] next\n\nenum E { X, Y }\nclass B.\n");
    expect(syntax.errorCount).toBeGreaterThan(0);
    expect(syntax.firstErrorLine).not.toBeNull();
    expect(metamodel.classes.map((item) => item.name)).toContain("A");
    expect(metamodel.classes[0].features[0]).toMatchObject({ name: "next", type: "A" });
  });

  it("reports a missing comma in an enum and keeps the enum", () => {
    const { metamodel, syntax } = readProblem("enum Color { Red Green, Blue }\nclass Car { Color[1] color }\n");
    expect(syntax.errorCount).toBeGreaterThan(0);
    expect(syntax.firstErrorLine).toBe(1);
    expect(metamodel.enums[0]).toMatchObject({ name: "Color" });
    expect(metamodel.enums[0].literals).toContain("Red");
    expect(metamodel.classes.find((item) => item.name === "Car")).toBeDefined();
  });

  it("reports garbage in the middle and reads the statements around it", () => {
    const { metamodel, model, syntax } = readProblem("class Pump.\n\n}}} ??? <-> 12 ..\n\nclass Valve.\ndeclare p.\nPump(p).\n");
    expect(syntax.errorCount).toBeGreaterThan(0);
    expect(syntax.firstErrorLine).toBe(3);
    expect(metamodel.classes.map((item) => item.name)).toEqual(expect.arrayContaining(["Pump", "Valve"]));
    expect(model.nodes).toEqual([expect.objectContaining({ name: "p", types: ["Pump"] })]);
  });

  // Several hundred parses: a slow machine gets more time than the default
  it("never throws on any truncation of a valid text", { timeout: 30_000 }, () => {
    for (const text of [DEFAULT_SPECIFICATION, FILE_SYSTEM]) {
      for (let end = 0; end <= text.length; end += 7) {
        expect(() => readProblem(text.slice(0, end))).not.toThrow();
      }
    }
  });

  it("reads an empty text as nothing", () => {
    expect(readProblem("")).toEqual({
      metamodel: { classes: [], enums: [], predicates: [], declarations: [], scopes: [] },
      model: { nodes: [], links: [], omitted: { negative: 0, defaults: 0, newObjects: 0, builtins: 0, higherArity: 0, other: 0 }, higherArityRelations: [] },
      syntax: { errorCount: 0, firstErrorLine: null },
    });
  });
});

describe("relations in words", () => {
  it("splits camelCase and underscores and keeps acronyms", () => {
    expect(relationWords("overtakingToPort")).toBe("overtaking to port");
    expect(relationWords("atDangerousHeadOnSectorOf")).toBe("at dangerous head on sector of");
    expect(relationWords("inCOLREGSSituationWith")).toBe("in COLREGS situation with");
    expect(relationWords("is_parent_of")).toBe("is parent of");
    expect(relationWords("fs::containsFile")).toBe("contains file");
    expect(relationWords("x")).toBe("x");
  });

  it("says a link, a two-way pair and a possible link", () => {
    expect(describeLink({ relation: "overtakingToPort", source: "ts1", target: "os", possible: false, twoWay: false })).toBe("ts1 overtaking to port os");
    expect(describeLink({ relation: "headOn", source: "os", target: "ts1", possible: false, twoWay: true })).toBe("os and ts1 head on");
    expect(describeLink({ relation: "owners", source: "report", target: "bob", possible: true, twoWay: false })).toBe("report owners bob (possibly)");
  });
});
