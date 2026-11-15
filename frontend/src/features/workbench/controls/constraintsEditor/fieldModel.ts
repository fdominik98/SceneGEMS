/**
 * The field model of a constraints YAML text: what the form shows, built generically from whatever the
 * document holds. Nothing here knows a key by name (the few keys the backend checks by name are listed in
 * validation.ts, which gives a field its choices). Scalars become typed fields, maps become groups
 * (comment lines above a key start a new section with that title), maps of similar maps become tables,
 * lists become lists, and anything else is shown as read-only raw text, so no data is ever dropped.
 */

import { isAlias, isMap, isNode, isScalar, isSeq, parseDocument, type Document, type Pair, type Scalar, type YAMLMap, type YAMLSeq } from "yaml";
import { parseFieldComment, type UnitId } from "./units";
import { choicesOf, validateFieldValue, validateMinMaxPairs, validateTableColumn, type FieldIssue } from "./validation";

export type YamlPath = ReadonlyArray<string | number>;

export type FieldKind = "number" | "integer" | "boolean" | "string" | "null";

export interface ScalarFieldModel {
  nodeType: "scalar";
  path: YamlPath;
  /** The key as written in the YAML, or the position for a list item. */
  key: string;
  label: string;
  kind: FieldKind;
  value: number | boolean | string | null;
  /** The value as written in the YAML. */
  source: string;
  description: string;
  /** A conversion the comment spells out, such as `~1.7 deg/s`. */
  hint: string | null;
  /** The comment as written, without the leading hash. */
  comment: string;
  unit: UnitId | null;
  /** The values the backend accepts, for a key it reads as a fixed choice (validation.ts); null otherwise. */
  choices: readonly string[] | null;
  issues: FieldIssue[];
}

export interface GroupSection {
  title: string | null;
  note: string | null;
  items: FieldModel[];
}

export interface GroupModel {
  nodeType: "group";
  path: YamlPath;
  key: string;
  label: string;
  description: string;
  sections: GroupSection[];
}

export interface TableColumn {
  key: string;
  label: string;
  kind: FieldKind;
  unit: UnitId | null;
  description: string;
}

export interface TableRow {
  key: string;
  path: YamlPath;
  /** Comment lines above the row. */
  note: string | null;
  /** Rows the backend looks up by name; they cannot be removed or renamed. */
  protected: boolean;
  /** One cell per column; null where this row has no such key. */
  cells: (ScalarFieldModel | null)[];
}

export interface TableModel {
  nodeType: "table";
  path: YamlPath;
  key: string;
  label: string;
  description: string;
  columns: TableColumn[];
  rows: TableRow[];
  issues: FieldIssue[];
}

export interface ListModel {
  nodeType: "list";
  path: YamlPath;
  key: string;
  label: string;
  description: string;
  items: FieldModel[];
}

/** `{}` or `[]` in the YAML: nothing to edit in the form. */
export interface EmptyModel {
  nodeType: "empty";
  path: YamlPath;
  key: string;
  label: string;
  description: string;
  flow: "{}" | "[]";
}

/** A node the form cannot edit: an alias, a tagged value, a map with complex keys. */
export interface RawModel {
  nodeType: "raw";
  path: YamlPath;
  key: string;
  label: string;
  description: string;
  source: string;
}

export type FieldModel = ScalarFieldModel | GroupModel | TableModel | ListModel | EmptyModel | RawModel;

export interface ParseFailure {
  message: string;
  line: number | null;
  column: number | null;
}

export type ConstraintsModel =
  | {
      ok: true;
      /** Comment lines at the top of the document. */
      header: string | null;
      root: FieldModel | null;
      issueCount: number;
    }
  | { ok: false; error: ParseFailure };

export interface ModelOptions {
  /** Rows of a table that the backend looks up by name, such as `UnspecifiedVesselType`. */
  protectedRows?: readonly string[];
  /** How many entries a map of maps needs to be a table (default 2). */
  tableMinRows?: number;
}

const DEFAULT_TABLE_MIN_ROWS = 2;

interface BuildContext {
  text: string;
  options: ModelOptions;
}

export function humanizeKey(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/[_\-.]+/g, " ")
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function commentLines(comment: string | null | undefined): string[] {
  if (!comment) {
    return [];
  }
  return comment
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function keyToString(key: unknown): string | null {
  if (isScalar(key)) {
    return key.value === null ? "null" : String(key.value);
  }
  return null;
}

function rawKeyValue(key: unknown): string | number {
  if (isScalar(key) && (typeof key.value === "number" || typeof key.value === "string")) {
    return key.value;
  }
  return String(isScalar(key) ? key.value : key);
}

function sourceOf(node: Scalar): string {
  const source = (node as { source?: string }).source;
  return source ?? (node.value === null ? "null" : String(node.value));
}

function scalarKindOf(node: Scalar): FieldKind | null {
  const value = node.value;
  if (typeof value === "number") {
    return Number.isInteger(value) && !/[.eE]|inf|nan/i.test(sourceOf(node)) ? "integer" : "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  if (typeof value === "string") {
    return "string";
  }
  if (value === null || value === undefined) {
    return "null";
  }
  return null;
}

function rawModel(ctx: BuildContext, node: unknown, path: YamlPath, key: string): RawModel {
  let source = "";
  const range = isNode(node) ? node.range : null;
  if (range) {
    source = ctx.text.slice(range[0], range[1]).trim();
  }
  if (!source && isScalar(node)) {
    source = String(node.value);
  }
  return { nodeType: "raw", path, key, label: humanizeKey(key), description: "", source };
}

function buildScalar(ctx: BuildContext, node: Scalar | null, path: YamlPath, key: string, comment: string | null): ScalarFieldModel | RawModel {
  const kind = node ? scalarKindOf(node) : "null";
  if (node && (kind === null || node.tag)) {
    return rawModel(ctx, node, path, key);
  }
  const parsed = parseFieldComment(comment ?? node?.comment);
  const field: ScalarFieldModel = {
    nodeType: "scalar",
    path,
    key,
    label: humanizeKey(key),
    kind: kind ?? "null",
    value: node ? (node.value as ScalarFieldModel["value"]) ?? null : null,
    source: node ? sourceOf(node) : "null",
    description: parsed.description,
    hint: parsed.hint,
    comment: parsed.raw,
    unit: parsed.unit,
    choices: choicesOf(key),
    issues: [],
  };
  field.issues = validateFieldValue(field);
  return field;
}

/** A map of maps with mostly the same scalar keys is a table: one row per entry, one column per key. */
function tableColumnKeys(map: YAMLMap, minRows: number): string[] | null {
  if (map.items.length < minRows || map.items.length === 0) {
    return null;
  }
  const columns: string[] = [];
  let present = 0;
  const counts = new Map<string, number>();
  for (const pair of map.items) {
    const inner = pair.value;
    if (keyToString(pair.key) === null || !isMap(inner) || inner.items.length === 0) {
      return null;
    }
    for (const cell of inner.items) {
      const cellKey = keyToString(cell.key);
      if (cellKey === null || !isScalar(cell.value)) {
        return null;
      }
      present += 1;
      if (!counts.has(cellKey)) {
        columns.push(cellKey);
      }
      counts.set(cellKey, (counts.get(cellKey) ?? 0) + 1);
    }
  }
  const rows = map.items.length;
  const everyColumnCommon = columns.every((column) => (counts.get(column) ?? 0) * 2 >= rows);
  const coverage = present / (rows * columns.length);
  return everyColumnCommon && coverage >= 0.75 ? columns : null;
}

function dominantKind(kinds: FieldKind[]): FieldKind {
  const tally = new Map<FieldKind, number>();
  for (const kind of kinds) {
    const normalized = kind === "integer" ? "number" : kind;
    tally.set(normalized, (tally.get(normalized) ?? 0) + 1);
  }
  let best: FieldKind = kinds[0] ?? "string";
  let bestCount = -1;
  for (const [kind, count] of tally) {
    if (count > bestCount) {
      best = kind;
      bestCount = count;
    }
  }
  if (best === "number" && kinds.every((kind) => kind === "integer")) {
    return "integer";
  }
  return best;
}

function buildTable(
  ctx: BuildContext,
  map: YAMLMap,
  path: YamlPath,
  key: string,
  columnKeys: string[],
  description: string
): TableModel {
  const protectedRows = new Set(ctx.options.protectedRows ?? []);
  const rows: TableRow[] = [];
  const cellsByColumn = new Map<string, ScalarFieldModel[]>();

  for (const pair of map.items) {
    const rowKey = keyToString(pair.key) ?? "";
    const rowPath = [...path, rawKeyValue(pair.key)];
    const inner = pair.value as YAMLMap;
    const cells: (ScalarFieldModel | null)[] = columnKeys.map((columnKey) => {
      const cellPair = inner.items.find((item) => keyToString(item.key) === columnKey);
      if (!cellPair || !isScalar(cellPair.value)) {
        return null;
      }
      const built = buildScalar(ctx, cellPair.value, [...rowPath, rawKeyValue(cellPair.key)], columnKey, null);
      if (built.nodeType !== "scalar") {
        return null;
      }
      const column = cellsByColumn.get(columnKey) ?? [];
      column.push(built);
      cellsByColumn.set(columnKey, column);
      return built;
    });
    const note = commentLines(isScalar(pair.key) ? pair.key.commentBefore : null).join(" ");
    rows.push({ key: rowKey, path: rowPath, note: note || null, protected: protectedRows.has(rowKey), cells });
  }

  const columns: TableColumn[] = columnKeys.map((columnKey) => {
    const cells = cellsByColumn.get(columnKey) ?? [];
    let best = parseFieldComment(null);
    for (const cell of cells) {
      const parsed = parseFieldComment(cell.comment);
      const better =
        parsed.unitScore > best.unitScore ||
        (parsed.unitScore === best.unitScore && parsed.description.length > best.description.length);
      if (better) {
        best = parsed;
      }
    }
    return {
      key: columnKey,
      label: humanizeKey(columnKey),
      kind: dominantKind(cells.map((cell) => cell.kind)),
      unit: best.unit,
      description: best.description,
    };
  });

  // A cell without a comment of its own takes the unit of its column.
  columns.forEach((column, index) => {
    for (const row of rows) {
      const cell = row.cells[index];
      if (cell && cell.unit === null && column.unit !== null) {
        cell.unit = column.unit;
        cell.issues = validateFieldValue(cell);
      }
    }
  });

  columns.forEach((column, index) => {
    validateTableColumn(
      column,
      rows.map((row) => row.cells[index])
    );
  });
  for (const row of rows) {
    validateMinMaxPairs(row.cells.filter((cell): cell is ScalarFieldModel => cell !== null));
  }

  const issues: FieldIssue[] = [];
  const present = new Set(rows.map((row) => row.key));
  for (const required of protectedRows) {
    if (!present.has(required)) {
      issues.push({ severity: "error", message: `The row ${required} is missing; the backend looks it up by name.` });
    }
  }

  return { nodeType: "table", path, key, label: humanizeKey(key), description, columns, rows, issues };
}

function buildMapField(ctx: BuildContext, map: YAMLMap, path: YamlPath, key: string, description: string): FieldModel {
  if (map.items.length === 0) {
    return { nodeType: "empty", path, key, label: humanizeKey(key), description, flow: "{}" };
  }
  if (map.items.some((pair) => keyToString(pair.key) === null)) {
    return rawModel(ctx, map, path, key);
  }
  const columnKeys = tableColumnKeys(map, ctx.options.tableMinRows ?? DEFAULT_TABLE_MIN_ROWS);
  if (columnKeys) {
    return buildTable(ctx, map, path, key, columnKeys, description);
  }

  const sections: GroupSection[] = [];
  let current: GroupSection | null = null;
  for (const pair of map.items) {
    const childKey = keyToString(pair.key) ?? "";
    const heading = commentLines(isScalar(pair.key) ? pair.key.commentBefore : null);
    if (!current || heading.length > 0) {
      current = { title: heading[0] ?? null, note: heading.length > 1 ? heading.slice(1).join(" ") : null, items: [] };
      sections.push(current);
    }
    current.items.push(buildChild(ctx, pair, [...path, rawKeyValue(pair.key)], childKey));
  }
  for (const section of sections) {
    validateMinMaxPairs(section.items.filter((item): item is ScalarFieldModel => item.nodeType === "scalar"));
  }
  // min and max keys may sit in different sections.
  if (sections.length > 1) {
    validateMinMaxPairs(sections.flatMap((section) => section.items).filter((item): item is ScalarFieldModel => item.nodeType === "scalar"));
  }
  return { nodeType: "group", path, key, label: humanizeKey(key), description, sections };
}

function buildSeqField(ctx: BuildContext, seq: YAMLSeq, path: YamlPath, key: string, description: string): FieldModel {
  if (seq.items.length === 0) {
    return { nodeType: "empty", path, key, label: humanizeKey(key), description, flow: "[]" };
  }
  const items = seq.items.map((item, index) => {
    const itemPath = [...path, index];
    const itemKey = String(index + 1);
    return buildValue(ctx, item, itemPath, itemKey, null, `Item ${index + 1}`);
  });
  validateMinMaxPairs(items.filter((item): item is ScalarFieldModel => item.nodeType === "scalar"));
  return { nodeType: "list", path, key, label: humanizeKey(key), description, items };
}

function buildValue(
  ctx: BuildContext,
  node: unknown,
  path: YamlPath,
  key: string,
  comment: string | null,
  label?: string
): FieldModel {
  let built: FieldModel;
  if (node === null || node === undefined) {
    built = buildScalar(ctx, null, path, key, comment);
  } else if (isScalar(node)) {
    built = buildScalar(ctx, node, path, key, comment);
  } else if (isMap(node)) {
    built = buildMapField(ctx, node, path, key, commentLines(node.commentBefore).join(" "));
  } else if (isSeq(node)) {
    built = buildSeqField(ctx, node, path, key, commentLines(node.commentBefore).join(" "));
  } else if (isAlias(node)) {
    built = rawModel(ctx, node, path, key);
  } else {
    built = rawModel(ctx, node, path, key);
  }
  if (label !== undefined) {
    built.label = label;
  }
  return built;
}

function buildChild(ctx: BuildContext, pair: Pair, path: YamlPath, key: string): FieldModel {
  const value = pair.value;
  return buildValue(ctx, value, path, key, isScalar(value) ? (value.comment ?? null) : null);
}

function failureFrom(doc: Document.Parsed): ParseFailure {
  const error = doc.errors[0];
  const position = error.linePos?.[0];
  return {
    // The first line of a pretty error ends with its position, which is shown separately.
    message: error.message
      .split("\n")[0]
      .replace(/\s+at line \d+, column \d+:?$/, "")
      .trim(),
    line: position?.line ?? null,
    column: position?.col ?? null,
  };
}

function countIssues(field: FieldModel | null): number {
  if (!field) {
    return 0;
  }
  switch (field.nodeType) {
    case "scalar":
      return field.issues.length;
    case "group":
      return field.sections.reduce((sum, section) => sum + section.items.reduce((inner, item) => inner + countIssues(item), 0), 0);
    case "list":
      return field.items.reduce((sum, item) => sum + countIssues(item), 0);
    case "table":
      return (
        field.issues.length +
        field.rows.reduce((sum, row) => sum + row.cells.reduce((inner, cell) => inner + (cell ? cell.issues.length : 0), 0), 0)
      );
    default:
      return 0;
  }
}

export function parseConstraintsDocument(text: string): Document.Parsed {
  return parseDocument(text, { keepSourceTokens: false, prettyErrors: true });
}

/** The first parse error of a YAML text, or null when it parses. */
export function findParseFailure(text: string): ParseFailure | null {
  const doc = parseConstraintsDocument(text);
  return doc.errors.length > 0 ? failureFrom(doc) : null;
}

/** Builds the field model of a YAML text, or the parse failure when it is not valid YAML. */
export function buildConstraintsModel(text: string, options: ModelOptions = {}): ConstraintsModel {
  const doc = parseConstraintsDocument(text);
  if (doc.errors.length > 0) {
    return { ok: false, error: failureFrom(doc) };
  }
  const ctx: BuildContext = { text, options };
  const contents = doc.contents;
  const header = commentLines(doc.commentBefore).join("\n") || null;
  if (contents === null || (isScalar(contents) && contents.value === null && text.trim() === "")) {
    return { ok: true, header, root: null, issueCount: 0 };
  }
  const root = buildValue(ctx, contents, [], "", isScalar(contents) ? (contents.comment ?? null) : null, "Value");
  if (root.nodeType !== "scalar") {
    root.label = "";
  }
  return { ok: true, header, root, issueCount: countIssues(root) };
}

/** Every scalar field of a model, in document order. */
export function flattenScalarFields(field: FieldModel | null): ScalarFieldModel[] {
  if (!field) {
    return [];
  }
  switch (field.nodeType) {
    case "scalar":
      return [field];
    case "group":
      return field.sections.flatMap((section) => section.items.flatMap(flattenScalarFields));
    case "list":
      return field.items.flatMap(flattenScalarFields);
    case "table":
      return field.rows.flatMap((row) => row.cells.filter((cell): cell is ScalarFieldModel => cell !== null));
    default:
      return [];
  }
}
