import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { buildConstraintsModel, flattenScalarFields, type TableModel } from "./fieldModel";
import { ALL_DOMAIN_FILES, GENERAL_COLREGS, OBSTACLE_TYPES, VESSEL_TYPES } from "./domainFiles.fixture";
import { applyEdit, suggestRowName, validateRowName, type YamlEdit } from "./yamlEdit";
import { formatYamlNumber, formatYamlScalar, parseTypedNumber, pyYamlReadsNumber } from "./yamlValues";

function edit(text: string, change: YamlEdit): string {
  const result = applyEdit(text, change);
  if (!result.ok) {
    throw new Error(result.error);
  }
  return result.text;
}

/** Changes one line of a text, to compare it with an edit. */
function replaceOnce(text: string, from: string, to: string): string {
  expect(text.split(from).length - 1).toBe(1);
  return text.replace(from, to);
}

const CRLF = String.fromCharCode(13, 10);

function commentsOf(text: string): string[] {
  return text.split(/\r?\n/).flatMap((line) => {
    const index = line.indexOf("#");
    return index < 0 ? [] : [line.slice(index).trim()];
  });
}

describe("round trip", () => {
  it.each(Object.entries(ALL_DOMAIN_FILES))("%s: setting every value to itself leaves the text byte-identical", (_name, text) => {
    // Without an edit the form hands the text back untouched; a value written over itself changes nothing either.
    const model = buildConstraintsModel(text);
    expect(model.ok).toBe(true);
    for (const field of flattenScalarFields(model.ok ? model.root : null)) {
      const result = applyEdit(text, { kind: "set", path: field.path, value: field.value, asFloat: field.kind === "number" });
      expect(result, field.key).toEqual({ ok: true, text });
    }
  });

  it.each(Object.entries(ALL_DOMAIN_FILES))("%s: a row added and removed again differs only in whitespace", (_name, text) => {
    const model = buildConstraintsModel(text, { tableMinRows: 1 });
    const root = model.ok ? model.root : null;
    if (!root || root.nodeType !== "table") {
      return;
    }
    const added = edit(text, { kind: "addRow", path: [], templateKey: root.rows[0].key, newKey: "TemporaryRow" });
    const removed = edit(added, { kind: "removeRow", path: [], key: "TemporaryRow" });
    const squash = (value: string) => value.replace(/\s+/g, " ").trim();
    expect(squash(removed)).toBe(squash(text));
  });

  it("a value edit changes only that value, byte for byte", () => {
    const edited = edit(GENERAL_COLREGS, { kind: "set", path: ["READILY_APPARENT_COURSE_CHANGE_TIME"], value: 45 });
    expect(edited).toBe(replaceOnce(GENERAL_COLREGS, "READILY_APPARENT_COURSE_CHANGE_TIME: 70 ", "READILY_APPARENT_COURSE_CHANGE_TIME: 45 "));
    expect(edited).toContain("\r\n");
    expect(commentsOf(edited)).toEqual(commentsOf(GENERAL_COLREGS));
  });

  it("keeps the spacing before a comment, blank lines and the missing final newline", () => {
    const edited = edit(OBSTACLE_TYPES, { kind: "set", path: ["LargeObstacle", "max_radius"], value: 500 });
    expect(edited.endsWith("max_radius: 500")).toBe(true);
    expect(edited).toBe(OBSTACLE_TYPES.replace(/max_radius: 400$/, "max_radius: 500"));
  });

  it("editing a value in a table row keeps every comment and the key order", () => {
    const edited = edit(VESSEL_TYPES, { kind: "set", path: ["CargoShip", "max_speed"], value: 13 });
    const before = VESSEL_TYPES.split(CRLF);
    const after = edited.split(CRLF);
    expect(after).toHaveLength(before.length);
    const changed = after.flatMap((line, index) => (line === before[index] ? [] : [index]));
    expect(changed).toHaveLength(1);
    expect(after[changed[0]]).toBe("    max_speed: 13");
    expect((parse(edited) as Record<string, Record<string, number>>).ContainerShip.max_speed).toBe(12.8611175);
    expect(commentsOf(edited)).toEqual(commentsOf(VESSEL_TYPES));
  });

  it("an edit keeps a float a float", () => {
    const edited = edit(VESSEL_TYPES, { kind: "set", path: ["UnspecifiedVesselType", "min_length"], value: 12, asFloat: true });
    expect(edited).toContain("min_length: 12.0 # Minimum vessel length in meters");
  });

  it("the edited text still reads back as the edited values", () => {
    let text = VESSEL_TYPES;
    text = edit(text, { kind: "set", path: ["MiniUSV", "max_speed"], value: 2.5, asFloat: true });
    text = edit(text, { kind: "set", path: ["MiniUSV", "min_length"], value: 1.5, asFloat: true });
    const data = parse(text) as Record<string, Record<string, number>>;
    expect(data.MiniUSV.max_speed).toBe(2.5);
    expect(data.MiniUSV.min_length).toBe(1.5);
    expect(data.CargoShip.max_speed).toBe(12.8611175);
  });

  it("writes a scalar of every kind", () => {
    const text = "a: 1\nb: x\nc: true\nd: 1.5\n";
    expect(edit(text, { kind: "set", path: ["b"], value: "123" })).toContain('b: "123"');
    expect(edit(text, { kind: "set", path: ["b"], value: "yes" })).toContain('b: "yes"');
    expect(edit(text, { kind: "set", path: ["b"], value: "plain text" })).toContain("b: plain text");
    expect(edit(text, { kind: "set", path: ["c"], value: false })).toContain("c: false");
    expect(edit(text, { kind: "set", path: ["a"], value: null })).toContain("a: null");
  });

  it("sets a missing key and a null value", () => {
    expect(parse(edit("a: 1\n", { kind: "set", path: ["b"], value: 2 }))).toEqual({ a: 1, b: 2 });
    expect(parse(edit("a:\nb: 1\n", { kind: "set", path: ["a"], value: 5 }))).toEqual({ a: 5, b: 1 });
  });

  it("a list item and a nested value can be set", () => {
    const text = "outer:\n  items:\n    - 1\n    - 2\n";
    expect(parse(edit(text, { kind: "set", path: ["outer", "items", 1], value: 9 }))).toEqual({ outer: { items: [1, 9] } });
  });

  it("refuses to edit text that does not parse", () => {
    expect(applyEdit("a: [1\n", { kind: "set", path: ["a"], value: 1 })).toEqual({ ok: false, error: "The YAML does not parse." });
  });
});

describe("table operations", () => {
  it("removes a row and keeps the others and their comments", () => {
    const edited = edit(VESSEL_TYPES, { kind: "removeRow", path: [], key: "Tanker" });
    expect(parse(edited)).not.toHaveProperty("Tanker");
    expect(Object.keys(parse(edited))).toHaveLength(10);
    // The comment of the removed row goes with it.
    expect(commentsOf(edited)).toEqual(commentsOf(VESSEL_TYPES).filter((comment) => comment !== "# ~0.34 deg/s"));
    expect(edited.split("\n").every((line) => line === "" || line.endsWith("\r"))).toBe(true);
  });

  it("duplicates a row right after the original, without its comments", () => {
    const edited = edit(VESSEL_TYPES, { kind: "duplicateRow", path: [], key: "CargoShip", newKey: "CargoShipCopy" });
    const data = parse(edited) as Record<string, unknown>;
    const keys = Object.keys(data);
    expect(keys.indexOf("CargoShipCopy")).toBe(keys.indexOf("CargoShip") + 1);
    expect(data.CargoShipCopy).toEqual(data.CargoShip);
  });

  it("duplicates the first row, which carries the comments, into a row without them", () => {
    const edited = edit(VESSEL_TYPES, { kind: "duplicateRow", path: [], key: "UnspecifiedVesselType", newKey: "Mine" });
    expect(commentsOf(edited).length).toBe(commentsOf(VESSEL_TYPES).length);
    expect(parse(edited).Mine).toEqual(parse(VESSEL_TYPES).UnspecifiedVesselType);
  });

  it("adds a row from a template at the end", () => {
    const edited = edit(OBSTACLE_TYPES, { kind: "addRow", path: [], templateKey: "SmallObstacle", newKey: "HugeObstacle" });
    const keys = Object.keys(parse(edited));
    expect(keys[keys.length - 1]).toBe("HugeObstacle");
    expect(parse(edited).HugeObstacle).toEqual({ min_radius: 10, max_radius: 50 });
    // Line endings stay CRLF, and the missing final newline of the file stays missing.
    expect(edited.split("\n").slice(0, -1).every((line) => line.endsWith("\r"))).toBe(true);
    expect(edited.endsWith("\n")).toBe(false);
  });

  it("the new row appears in the model and can be edited", () => {
    let text = edit(VESSEL_TYPES, { kind: "addRow", path: [], templateKey: "CargoShip", newKey: "Ferry" });
    text = edit(text, { kind: "set", path: ["Ferry", "max_speed"], value: 9 });
    const model = buildConstraintsModel(text);
    const table = (model.ok ? model.root : null) as TableModel;
    expect(table.rows.map((row) => row.key)).toContain("Ferry");
    expect(parse(text).Ferry.max_speed).toBe(9);
  });

  it("renames a row, keeping its place and values", () => {
    const edited = edit(VESSEL_TYPES, { kind: "renameRow", path: [], key: "Tanker", newKey: "OilTanker" });
    const before = Object.keys(parse(VESSEL_TYPES));
    const after = Object.keys(parse(edited));
    expect(after).toEqual(before.map((key) => (key === "Tanker" ? "OilTanker" : key)));
    expect(parse(edited).OilTanker).toEqual(parse(VESSEL_TYPES).Tanker);
  });

  it("refuses a name that exists or is not a plain name", () => {
    expect(applyEdit(VESSEL_TYPES, { kind: "renameRow", path: [], key: "Tanker", newKey: "CargoShip" }).ok).toBe(false);
    expect(applyEdit(VESSEL_TYPES, { kind: "duplicateRow", path: [], key: "Tanker", newKey: "no spaces" }).ok).toBe(false);
    expect(applyEdit(VESSEL_TYPES, { kind: "addRow", path: [], templateKey: "Tanker", newKey: "null" }).ok).toBe(true);
    expect(applyEdit(VESSEL_TYPES, { kind: "addRow", path: [], templateKey: "Nope", newKey: "X" }).ok).toBe(false);
    expect(applyEdit(VESSEL_TYPES, { kind: "removeRow", path: [], key: "Nope" }).ok).toBe(false);
  });

  it("validates row names", () => {
    expect(validateRowName("Good_name2", ["A"])).toBeNull();
    expect(validateRowName("2bad", [])).not.toBeNull();
    expect(validateRowName("A", ["A"])).toMatch(/exists/);
    expect(validateRowName("A", ["A"], "A")).toBeNull();
  });

  it("suggests unused names for copies", () => {
    expect(suggestRowName("Tanker", ["Tanker"])).toBe("TankerCopy");
    expect(suggestRowName("Tanker", ["Tanker", "TankerCopy"])).toBe("TankerCopy2");
    expect(suggestRowName("TankerCopy", ["Tanker", "TankerCopy"])).toBe("TankerCopy2");
  });

  it("works on a table below the root", () => {
    const text = "# top\nvessels:\n  A:\n    x: 1\n  B:\n    x: 2\nother: 3 # kept\n";
    const edited = edit(text, { kind: "duplicateRow", path: ["vessels"], key: "A", newKey: "C" });
    expect(parse(edited)).toEqual({ vessels: { A: { x: 1 }, C: { x: 1 }, B: { x: 2 } }, other: 3 });
    expect(commentsOf(edited)).toEqual(["# top", "# kept"]);
  });

  it("keeps the four space indent of the original", () => {
    const edited = edit(VESSEL_TYPES, { kind: "removeRow", path: [], key: "Tanker" });
    expect(edited).toContain("\r\n    min_length: 10.0");
  });

  it("adds and removes list items", () => {
    const text = "items:\n  - 1 # first\n  - 2\n";
    const added = edit(text, { kind: "addItem", path: ["items"] });
    expect(parse(added)).toEqual({ items: [1, 2, 2] });
    expect(commentsOf(added)).toEqual(["# first"]);
    expect(parse(edit(added, { kind: "removeItem", path: ["items"], index: 0 }))).toEqual({ items: [2, 2] });
    expect(applyEdit(text, { kind: "removeItem", path: ["items"], index: 5 }).ok).toBe(false);
    expect(applyEdit(text, { kind: "addItem", path: ["nope"] }).ok).toBe(false);
  });

  it("every cell of the edited vessel types stays a number", () => {
    const text = edit(VESSEL_TYPES, { kind: "duplicateRow", path: [], key: "MiniUSV", newKey: "Skiff" });
    const model = buildConstraintsModel(text);
    expect(model.ok && flattenScalarFields(model.root).every((field) => typeof field.value === "number")).toBe(true);
  });
});

describe("number formatting for the backend", () => {
  it("never writes an exponent PyYAML would read as text", () => {
    expect(formatYamlNumber(1e-7, true)).toBe("1.0e-7");
    expect(formatYamlNumber(1.5e-7, true)).toBe("1.5e-7");
    expect(formatYamlNumber(1e21, true)).toBe("1.0e+21");
    for (const text of ["1.0e-7", "1.5e-7", "1.0e+21"]) {
      expect(pyYamlReadsNumber(text)).toBe(true);
    }
    expect(pyYamlReadsNumber("1e-7")).toBe(false);
    expect(pyYamlReadsNumber("1.0e7")).toBe(false);
  });

  it("keeps whole floats floats and integers integers", () => {
    expect(formatYamlNumber(12, true)).toBe("12.0");
    expect(formatYamlNumber(12, false)).toBe("12");
    expect(formatYamlNumber(0.5235987755982988, true)).toBe("0.5235987755982988");
    expect(formatYamlNumber(-3, false)).toBe("-3");
  });

  it("formats special values and scalars", () => {
    expect(formatYamlNumber(Infinity, true)).toBe(".inf");
    expect(formatYamlNumber(-Infinity, true)).toBe("-.inf");
    expect(formatYamlNumber(NaN, true)).toBe(".nan");
    expect(formatYamlScalar("", false)).toBe('""');
    expect(formatYamlScalar(null, false)).toBe("null");
  });

  it("writes a tiny value so that the backend reads a float", () => {
    const edited = edit("a: 1.0\n", { kind: "set", path: ["a"], value: 0.0000001, asFloat: true });
    expect(edited).toBe("a: 1.0e-7\n");
  });

  it("parses typed numbers strictly", () => {
    expect(parseTypedNumber(" 12.5 ")).toBe(12.5);
    expect(parseTypedNumber("-.5")).toBe(-0.5);
    expect(parseTypedNumber("1e3")).toBe(1000);
    expect(parseTypedNumber("")).toBeNull();
    expect(parseTypedNumber("12abc")).toBeNull();
    expect(parseTypedNumber("0x10")).toBeNull();
    expect(parseTypedNumber("1,5")).toBeNull();
  });
});
