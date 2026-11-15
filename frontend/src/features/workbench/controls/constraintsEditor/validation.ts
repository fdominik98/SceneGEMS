/**
 * Checks on the values of the field model. They flag problems (an issue on the field) and never block an
 * edit: the YAML always keeps what the user wrote. Most checks go by the words of a key, its comment or
 * its unit; the few keys the backend checks by name have their choices and ranges listed here.
 */

import type { ScalarFieldModel, TableColumn } from "./fieldModel";
import { isMagnitudeUnit } from "./units";
import { isYaml11BooleanWord, pyYamlReadsNumber, pyYamlReadsOctal } from "./yamlValues";

export interface FieldIssue {
  severity: "error" | "warning";
  message: string;
}

/** The lower-case words of a key: `min_length`, `MIN_LENGTH` and `minLength` all give `min`, `length`. */
export function keyWords(key: string): string[] {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .split(/[\s_\-.]+/)
    .map((word) => word.toLowerCase())
    .filter((word) => word.length > 0);
}

const NON_NEGATIVE_KEY_WORDS = new Set([
  "min",
  "max",
  "minimum",
  "maximum",
  "time",
  "duration",
  "length",
  "beam",
  "speed",
  "radius",
  "distance",
  "acceleration",
  "persistence",
  "period",
  "size",
  "mass",
  "width",
  "height",
  "depth",
  "draft",
  "count",
  "interval",
  "timeout",
  "delay",
]);

const NON_NEGATIVE_COMMENT_WORDS = /\b(minimum|maximum|duration|distance|length|radius|size|persist)\b/i;

/** True where the name, the comment or the unit says the value is a size, a time, a rate or a limit. */
export function impliesNonNegative(field: Pick<ScalarFieldModel, "key" | "comment" | "unit">): boolean {
  if (field.unit !== null && isMagnitudeUnit(field.unit)) {
    return true;
  }
  if (keyWords(field.key).some((word) => NON_NEGATIVE_KEY_WORDS.has(word))) {
    return true;
  }
  return NON_NEGATIVE_COMMENT_WORDS.test(field.comment);
}

/**
 * What the backend accepts for the few keys it checks by name when it loads the vessel types
 * (`backend/src/logical_level/mapping/vessel_type.py`); it rejects the file otherwise. Keys are
 * matched by their words, so `steering_type` and `steeringType` are the same key.
 */
const CHOICES_BY_KEY: Readonly<Record<string, readonly string[]>> = {
  steering_type: ["rudder", "skid", "vectored_thrust"],
};

interface KeyRange {
  /** The value is greater than this. */
  above: number;
  /** The value is at most this; null for no upper limit. */
  upTo: number | null;
}

// Dimensionless hull ratios: they carry no unit, only a range.
const RANGES_BY_KEY: Readonly<Record<string, KeyRange>> = {
  block_coefficient: { above: 0, upTo: 1 },
  length_to_beam: { above: 0, upTo: null },
  beam_to_draft: { above: 0, upTo: null },
};

function knownKey(key: string): string {
  return keyWords(key).join("_");
}

/** The values a key can take, for the keys the backend reads as a fixed choice; null for any other key. */
export function choicesOf(key: string): readonly string[] | null {
  return CHOICES_BY_KEY[knownKey(key)] ?? null;
}

function listInWords(items: readonly string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} or ${items[items.length - 1]}`;
}

function rangeIssue(key: string, value: number): FieldIssue | null {
  const range = RANGES_BY_KEY[knownKey(key)];
  if (!range || (value > range.above && (range.upTo === null || value <= range.upTo))) {
    return null;
  }
  const limits = range.upTo === null ? `greater than ${range.above}` : `greater than ${range.above} and at most ${range.upTo}`;
  return { severity: "error", message: `The backend accepts only a ${key} ${limits}.` };
}

/** Issues of one value on its own. */
export function validateFieldValue(field: ScalarFieldModel): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const choices = choicesOf(field.key);
  if (choices && field.kind !== "null" && !choices.includes(String(field.value))) {
    issues.push({ severity: "error", message: `The backend accepts only ${listInWords(choices)} as ${field.key}.` });
  }
  if (field.kind === "number" || field.kind === "integer") {
    const value = field.value as number;
    const outOfRange = Number.isFinite(value) ? rangeIssue(field.key, value) : null;
    if (!Number.isFinite(value)) {
      issues.push({ severity: "error", message: "The value is not a finite number." });
    } else if (outOfRange) {
      issues.push(outOfRange);
    } else if (value < 0 && impliesNonNegative(field)) {
      issues.push({ severity: "warning", message: "The name, comment or unit says this cannot be negative." });
    }
    if (!pyYamlReadsNumber(field.source) && Number.isFinite(value)) {
      issues.push({
        severity: "warning",
        message: `The backend reads ${field.source} as text, not as a number. Write it with a dot and a signed exponent, for example 1.0e-3.`,
      });
    } else if (pyYamlReadsOctal(field.source)) {
      issues.push({
        severity: "warning",
        message: `The backend reads ${field.source} as an octal number. Remove the leading zero.`,
      });
    }
  } else if (field.kind === "string" && isYaml11BooleanWord(String(field.value))) {
    issues.push({ severity: "warning", message: `The backend reads ${field.value} as a boolean, not as text.` });
  }
  return issues;
}

type MinMaxRole = "min" | "max";

function minMaxRole(key: string): { role: MinMaxRole; stem: string } | null {
  const words = keyWords(key);
  if (words.length < 2) {
    return null;
  }
  const roleOf = (word: string): MinMaxRole | null => {
    if (word === "min" || word === "minimum") {
      return "min";
    }
    if (word === "max" || word === "maximum") {
      return "max";
    }
    return null;
  };
  const leading = roleOf(words[0]);
  if (leading) {
    return { role: leading, stem: words.slice(1).join("_") };
  }
  const trailing = roleOf(words[words.length - 1]);
  if (trailing) {
    return { role: trailing, stem: words.slice(0, -1).join("_") };
  }
  return null;
}

/** Flags a `min_x` that is greater than its `max_x` among sibling fields, on both of them. */
export function validateMinMaxPairs(fields: ScalarFieldModel[]): void {
  const lows = new Map<string, ScalarFieldModel>();
  const highs = new Map<string, ScalarFieldModel>();
  for (const field of fields) {
    const role = minMaxRole(field.key);
    if (!role) {
      continue;
    }
    (role.role === "min" ? lows : highs).set(role.stem, field);
  }
  for (const [stem, low] of lows) {
    const high = highs.get(stem);
    if (!high || typeof low.value !== "number" || typeof high.value !== "number") {
      continue;
    }
    if (low.value > high.value) {
      low.issues.push({ severity: "warning", message: `${low.key} is greater than ${high.key}.` });
      high.issues.push({ severity: "warning", message: `${high.key} is smaller than ${low.key}.` });
    }
  }
}

function category(kind: TableColumn["kind"]): string {
  return kind === "integer" ? "number" : kind;
}

/** Flags cells whose kind differs from the rest of their column, such as text among numbers. */
export function validateTableColumn(column: TableColumn, cells: (ScalarFieldModel | null)[]): void {
  const expected = category(column.kind);
  for (const cell of cells) {
    if (cell && category(cell.kind) !== expected && cell.kind !== "null") {
      cell.issues.push({
        severity: "error",
        message: `The other rows hold ${expected === "number" ? "numbers" : expected} in ${column.key}; this one holds ${category(cell.kind)}.`,
      });
    }
  }
}
