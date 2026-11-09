import { describe, expect, it } from "vitest";
import {
  buildConstraintsModel,
  findParseFailure,
  flattenScalarFields,
  humanizeKey,
  type FieldModel,
  type GroupModel,
  type ScalarFieldModel,
  type TableModel,
} from "./fieldModel";
import {
  ALL_DOMAIN_FILES,
  GENERAL_COLREGS,
  OBSTACLE_TYPES,
  VESSEL_DYNAMICS,
  VESSEL_TYPES,
  WARA_PS_COLREGS,
} from "./domainFiles.fixture";

function rootOf(text: string, options = {}): FieldModel {
  const model = buildConstraintsModel(text, options);
  if (!model.ok || !model.root) {
    throw new Error("expected a model");
  }
  return model.root;
}

function scalar(text: string, key: string): ScalarFieldModel {
  const found = flattenScalarFields(rootOf(text)).find((field) => field.key === key);
  if (!found) {
    throw new Error(`no field ${key}`);
  }
  return found;
}

describe("the domain configuration files", () => {
  it.each(Object.entries(ALL_DOMAIN_FILES))("%s parses into a model", (_name, text) => {
    const model = buildConstraintsModel(text, { tableMinRows: 1 });
    expect(model.ok).toBe(true);
    expect(findParseFailure(text)).toBeNull();
  });

  it("COLREGS constants are one group of nine typed fields in two sections named by their comments", () => {
    const root = rootOf(GENERAL_COLREGS) as GroupModel;
    expect(root.nodeType).toBe("group");
    expect(root.sections.map((section) => section.title)).toEqual([
      "COLREGS maneuver detection parameters",
      "Speed change detection parameters",
    ]);
    expect(root.sections.map((section) => section.items.length)).toEqual([6, 3]);
    const fields = flattenScalarFields(root);
    expect(fields).toHaveLength(9);
    expect(fields.map((field) => field.key)).toEqual([
      "READILY_APPARENT_COURSE_CHANGE_TIME",
      "READILY_APPARENT_HEADING_CHANGE",
      "UNDETECTABLE_HEADING_CHANGE",
      "HEADING_PERSISTENCE_TIME",
      "IMMEDIATE_HEADING_CHANGE_TIME",
      "UNDETECTABLE_HEADING_PERSISTENCE_TIME",
      "READILY_APPARENT_SPEED_CHANGE",
      "UNDETECTABLE_SPEED_CHANGE",
      "SAFE_TEMPORAL_DISTANCE",
    ]);
  });

  it("types the COLREGS fields and takes units from the comments", () => {
    const time = scalar(GENERAL_COLREGS, "READILY_APPARENT_COURSE_CHANGE_TIME");
    expect(time).toMatchObject({ kind: "integer", value: 70, unit: "seconds", label: "Readily apparent course change time" });
    expect(time.description).toBe("Time for a course change to be readily apparent");

    const heading = scalar(GENERAL_COLREGS, "READILY_APPARENT_HEADING_CHANGE");
    expect(heading).toMatchObject({ kind: "number", unit: "radians" });
    expect(heading.value).toBe(0.5235987755982988);

    expect(scalar(GENERAL_COLREGS, "READILY_APPARENT_SPEED_CHANGE")).toMatchObject({ kind: "number", unit: "m/s", value: 1 });
    expect(scalar(GENERAL_COLREGS, "SAFE_TEMPORAL_DISTANCE")).toMatchObject({ kind: "integer", unit: "seconds", value: 1200 });
    expect(scalar(WARA_PS_COLREGS, "SAFE_TEMPORAL_DISTANCE")).toMatchObject({ unit: "seconds", value: 600 });
  });

  it("every COLREGS field has a unit, a description and no issue", () => {
    for (const text of [GENERAL_COLREGS, WARA_PS_COLREGS]) {
      for (const field of flattenScalarFields(rootOf(text))) {
        expect(field.unit, field.key).not.toBeNull();
        expect(field.description, field.key).not.toBe("");
        expect(field.issues, field.key).toEqual([]);
      }
    }
  });

  it("vessel types are a table with eleven rows and seven columns", () => {
    const table = rootOf(VESSEL_TYPES) as TableModel;
    expect(table.nodeType).toBe("table");
    expect(table.rows).toHaveLength(11);
    expect(table.rows[0].key).toBe("UnspecifiedVesselType");
    expect(table.columns.map((column) => column.key)).toEqual([
      "min_length",
      "max_length",
      "min_beam",
      "max_beam",
      "max_speed",
      "max_angular_speed",
      "max_acceleration",
    ]);
  });

  it("table columns take their unit and description from the commented row", () => {
    const table = rootOf(VESSEL_TYPES) as TableModel;
    const byKey = Object.fromEntries(table.columns.map((column) => [column.key, column]));
    expect(byKey.min_length).toMatchObject({ unit: "meters", kind: "number" });
    expect(byKey.max_beam.unit).toBe("meters");
    expect(byKey.max_speed.unit).toBe("m/s");
    expect(byKey.max_angular_speed.unit).toBe("rad/s");
    expect(byKey.max_acceleration.unit).toBe("m/s²");
    expect(byKey.max_angular_speed.description).toBe("Maximum angular speed");
  });

  it("table cells without their own comment inherit the column unit", () => {
    const table = rootOf(VESSEL_TYPES) as TableModel;
    const cargo = table.rows.find((row) => row.key === "CargoShip");
    expect(cargo?.cells[4]).toMatchObject({ key: "max_speed", unit: "m/s", value: 12.8611175 });
    expect(cargo?.cells[0]).toMatchObject({ kind: "integer", value: 50, unit: "meters" });
  });

  it("the shipped vessel and obstacle types raise no issue", () => {
    for (const text of [VESSEL_TYPES, OBSTACLE_TYPES]) {
      const model = buildConstraintsModel(text);
      expect(model.ok && model.issueCount).toBe(0);
    }
  });

  it("obstacle types are a table, and a one-row map is one only with tableMinRows 1", () => {
    const table = rootOf(OBSTACLE_TYPES) as TableModel;
    expect(table.nodeType).toBe("table");
    expect(table.rows.map((row) => row.key)).toEqual([
      "UnspecifiedObstacleType",
      "TinyObstacleType",
      "SmallObstacle",
      "MediumObstacle",
      "LargeObstacle",
    ]);
    const single = "Only:\n  min_radius: 1\n  max_radius: 2\n";
    expect(rootOf(single).nodeType).toBe("group");
    expect(rootOf(single, { tableMinRows: 1 }).nodeType).toBe("table");
  });

  it("vessel dynamics render generically: a header, and two empty maps", () => {
    const model = buildConstraintsModel(VESSEL_DYNAMICS);
    expect(model.ok).toBe(true);
    if (!model.ok) {
      return;
    }
    expect(model.header).toContain("Overrides of the parametric Gazebo vessel model");
    const root = model.root as GroupModel;
    expect(root.nodeType).toBe("group");
    expect(root.sections[0].items.map((item) => item.nodeType)).toEqual(["empty", "empty"]);
  });
});

describe("generic fields", () => {
  const sample = [
    "# Section one",
    "alpha: 1 # Alpha (seconds)",
    "beta: 2.5",
    "flag: true",
    "name: hello",
    "",
    "# Section two",
    "gamma: 3",
    "",
  ].join("\n");

  it("gives every scalar kind a typed field", () => {
    const kinds = Object.fromEntries(flattenScalarFields(rootOf(sample)).map((field) => [field.key, field.kind]));
    expect(kinds).toEqual({ alpha: "integer", beta: "number", flag: "boolean", name: "string", gamma: "integer" });
  });

  it("a whole number written with a dot is a number, not an integer", () => {
    expect(scalar("x: 10.0\n", "x").kind).toBe("number");
    expect(scalar("x: 10\n", "x").kind).toBe("integer");
    expect(scalar("x: 1.0e+3\n", "x").kind).toBe("number");
  });

  it("starts a section at each comment above a key", () => {
    const root = rootOf(sample) as GroupModel;
    expect(root.sections.map((section) => [section.title, section.items.length])).toEqual([
      ["Section one", 4],
      ["Section two", 1],
    ]);
  });

  it("a new key added to the text appears as a field without any code change", () => {
    const extended = sample.replace("gamma: 3", "gamma: 3\nBRAND_NEW_LIMIT: 0.25 # A limit nobody coded for (meters)");
    const added = scalar(extended, "BRAND_NEW_LIMIT");
    expect(added).toMatchObject({ kind: "number", value: 0.25, unit: "meters", label: "Brand new limit" });
    expect(added.description).toBe("A limit nobody coded for");
  });

  it("a new key added to the shipped COLREGS file appears with its unit", () => {
    const extended = `${GENERAL_COLREGS.trimEnd()}\r\nNEW_WARNING_TIME: 45  # Time (seconds) before a warning\r\n`;
    const model = buildConstraintsModel(extended);
    expect(model.ok && flattenScalarFields(model.root).map((field) => field.key)).toContain("NEW_WARNING_TIME");
    expect(scalar(extended, "NEW_WARNING_TIME")).toMatchObject({ unit: "seconds", value: 45 });
  });

  it("a new key in every table row becomes a column", () => {
    const text = "A:\n  x: 1\n  extra: 5\nB:\n  x: 2\n  extra: 6\n";
    const table = rootOf(text) as TableModel;
    expect(table.columns.map((column) => column.key)).toEqual(["x", "extra"]);
  });

  it("a new column added to the vessel types appears", () => {
    const extended = VESSEL_TYPES.replace(/(\r?\n)(\s+max_acceleration: [^\r\n]*)/g, "$1$2$1    max_draft: 3.5");
    const table = rootOf(extended) as TableModel;
    expect(table.columns.map((column) => column.key)).toContain("max_draft");
  });

  it("renders nested maps as groups and lists as lists", () => {
    const text = "outer:\n  inner:\n    a: 1\n  items:\n    - 1\n    - 2\n  cases:\n    - name: x\n      v: 1\n";
    const root = rootOf(text) as GroupModel;
    const outer = root.sections[0].items[0] as GroupModel;
    expect(outer.nodeType).toBe("group");
    const [inner, items, cases] = outer.sections[0].items;
    expect(inner.nodeType).toBe("group");
    expect(items.nodeType).toBe("list");
    expect(cases.nodeType).toBe("list");
    expect((cases as { items: FieldModel[] }).items[0].nodeType).toBe("group");
  });

  it("keeps unknown shapes as raw text instead of dropping them", () => {
    const aliasText = "base: &anchor 5\nalias: *anchor\n";
    const root = rootOf(aliasText) as GroupModel;
    const alias = root.sections[0].items[1];
    expect(alias.nodeType).toBe("raw");
    expect((alias as { source: string }).source).toBe("*anchor");

    const complexKey = "? [complex, key]\n: value\n";
    expect(rootOf(complexKey).nodeType).toBe("raw");
  });

  it("shows a null value as a null field", () => {
    expect(scalar("a:\nb: 1\n", "a")).toMatchObject({ kind: "null", value: null });
  });

  it("an empty text has no root", () => {
    expect(buildConstraintsModel("")).toMatchObject({ ok: true, root: null });
    expect(buildConstraintsModel("# only a comment\n")).toMatchObject({ ok: true, root: null });
  });

  it("a text that is a single number is a field", () => {
    expect(rootOf("5\n")).toMatchObject({ nodeType: "scalar", kind: "integer", value: 5 });
  });
});

describe("table detection", () => {
  it("does not make a table of maps with different keys", () => {
    const text = "A:\n  x: 1\n  y: 2\nB:\n  p: 3\n  q: 4\n";
    expect(rootOf(text).nodeType).toBe("group");
  });

  it("does not make a table when a cell is itself a map", () => {
    const text = "A:\n  x:\n    deep: 1\nB:\n  x:\n    deep: 2\n";
    expect(rootOf(text).nodeType).toBe("group");
  });

  it("shows a missing cell of a table row as null", () => {
    const text = "A:\n  x: 1\n  y: 2\nB:\n  x: 3\n  y: 4\nC:\n  x: 5\n";
    const table = rootOf(text) as TableModel;
    expect(table.nodeType).toBe("table");
    expect(table.rows[2].cells[1]).toBeNull();
  });

  it("marks protected rows and reports a missing one", () => {
    const text = "A:\n  x: 1\nB:\n  x: 2\n";
    const table = rootOf(text, { protectedRows: ["A", "Z"] }) as TableModel;
    expect(table.rows.map((row) => row.protected)).toEqual([true, false]);
    expect(table.issues[0].message).toContain("Z");
  });

  it("keeps the comment above a row as its note", () => {
    const text = "A:\n  x: 1\n# Fast craft\nB:\n  x: 2\n";
    const table = rootOf(text) as TableModel;
    expect(table.rows[1].note).toBe("Fast craft");
  });
});

describe("parse errors", () => {
  it("reports the position of the first error", () => {
    const text = "a: 1\nb: [1, 2\nc: 3\n";
    const failure = findParseFailure(text);
    expect(failure).not.toBeNull();
    expect(failure?.line).toBeGreaterThan(0);
    expect(failure?.message).not.toMatch(/at line/);
    expect(buildConstraintsModel(text).ok).toBe(false);
  });

  it("treats a duplicate key as a parse error", () => {
    expect(findParseFailure("a: 1\na: 2\n")?.message).toMatch(/unique|duplicate/i);
  });
});

describe("humanizeKey", () => {
  it("makes readable labels from snake, upper and camel case", () => {
    expect(humanizeKey("min_length")).toBe("Min length");
    expect(humanizeKey("SAFE_TEMPORAL_DISTANCE")).toBe("Safe temporal distance");
    expect(humanizeKey("UnspecifiedVesselType")).toBe("Unspecified vessel type");
    expect(humanizeKey("maxSpeed")).toBe("Max speed");
  });
});
