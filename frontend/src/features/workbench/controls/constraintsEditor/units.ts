/**
 * Units and descriptions are read from the inline comment of a YAML value, for example
 * `# Time (seconds) for a course change to be readily apparent` or
 * `# Maximum vessel speed: 50.0 knots in m/s`.
 */

export type UnitId =
  | "seconds"
  | "minutes"
  | "radians"
  | "degrees"
  | "m/s"
  | "knots"
  | "meters"
  | "rad/s"
  | "deg/s"
  | "m/s²";

interface UnitDefinition {
  id: UnitId;
  symbol: string;
  /** Spellings recognised in a comment, as a regular expression source. */
  pattern: string;
  /** The unit shown next to this one, and how many of it make one of this unit. */
  alternate: { unit: UnitId; factor: number } | null;
  /** Physical magnitudes that cannot be negative. */
  magnitude: boolean;
}

const KNOT_IN_MPS = 1852 / 3600;
const DEGREES_PER_RADIAN = 180 / Math.PI;

// Longer phrases come first, so that "radians per second" is not read as "radians".
const UNIT_DEFINITIONS: readonly UnitDefinition[] = [
  {
    id: "m/s²",
    symbol: "m/s²",
    pattern: "(?:meters?|metres?) per second squared|m\\/s(?:\\^2|²|2)",
    alternate: null,
    magnitude: true,
  },
  {
    id: "rad/s",
    symbol: "rad/s",
    pattern: "radians? per second|rad\\/s",
    alternate: { unit: "deg/s", factor: DEGREES_PER_RADIAN },
    magnitude: true,
  },
  {
    id: "deg/s",
    symbol: "deg/s",
    pattern: "degrees? per second|deg\\/s|°\\/s",
    alternate: { unit: "rad/s", factor: 1 / DEGREES_PER_RADIAN },
    magnitude: true,
  },
  {
    id: "m/s",
    symbol: "m/s",
    pattern: "(?:meters?|metres?) per second|m\\/s",
    alternate: { unit: "knots", factor: 1 / KNOT_IN_MPS },
    magnitude: true,
  },
  {
    id: "knots",
    symbol: "kn",
    pattern: "knots?|kn|kts?",
    alternate: { unit: "m/s", factor: KNOT_IN_MPS },
    magnitude: true,
  },
  {
    id: "seconds",
    symbol: "s",
    pattern: "seconds?|secs?",
    alternate: { unit: "minutes", factor: 1 / 60 },
    magnitude: true,
  },
  {
    id: "minutes",
    symbol: "min",
    pattern: "minutes?|mins?",
    alternate: { unit: "seconds", factor: 60 },
    magnitude: true,
  },
  {
    id: "radians",
    symbol: "rad",
    pattern: "radians?|rad",
    alternate: { unit: "degrees", factor: DEGREES_PER_RADIAN },
    magnitude: false,
  },
  {
    id: "degrees",
    symbol: "deg",
    pattern: "degrees?|deg|°",
    alternate: { unit: "radians", factor: 1 / DEGREES_PER_RADIAN },
    magnitude: false,
  },
  {
    id: "meters",
    symbol: "m",
    pattern: "meters?|metres?",
    alternate: null,
    magnitude: true,
  },
];

const UNITS_BY_ID = new Map<UnitId, UnitDefinition>(UNIT_DEFINITIONS.map((unit) => [unit.id, unit]));

const ANY_UNIT_SOURCE = UNIT_DEFINITIONS.map((unit) => unit.pattern).join("|");
const UNIT_REGEX = new RegExp(`(?<![A-Za-z/])(?:${ANY_UNIT_SOURCE})(?![A-Za-z/²])`, "giu");
const UNIT_PHRASES = UNIT_DEFINITIONS.map((unit) => ({
  id: unit.id,
  regex: new RegExp(`^(?:${unit.pattern})$`, "iu"),
}));

export function unitSymbol(unit: UnitId): string {
  return UNITS_BY_ID.get(unit)?.symbol ?? unit;
}

export function isMagnitudeUnit(unit: UnitId): boolean {
  return UNITS_BY_ID.get(unit)?.magnitude ?? false;
}

export interface UnitAlternate {
  unit: UnitId;
  symbol: string;
}

/** The unit a value is also shown in and edited in (radians and degrees), or null. */
export function alternateUnit(unit: UnitId): UnitAlternate | null {
  const alternate = UNITS_BY_ID.get(unit)?.alternate;
  return alternate ? { unit: alternate.unit, symbol: unitSymbol(alternate.unit) } : null;
}

export function toAlternateUnit(unit: UnitId, value: number): number {
  const alternate = UNITS_BY_ID.get(unit)?.alternate;
  return alternate ? value * alternate.factor : value;
}

export function fromAlternateUnit(unit: UnitId, alternateValue: number): number {
  const alternate = UNITS_BY_ID.get(unit)?.alternate;
  return alternate ? alternateValue / alternate.factor : alternateValue;
}

/** Significant digits of a converted value (knots, degrees): enough to read it off, short enough for a table cell. */
export const CONVERTED_DIGITS = 6;

/** A number for display: ten significant digits (or `digits`), no trailing zeros, no exponent for ordinary sizes. */
export function formatDisplayNumber(value: number, digits = 10): string {
  if (!Number.isFinite(value)) {
    return String(value);
  }
  const rounded = Number(value.toPrecision(digits));
  if (rounded === 0) {
    return "0";
  }
  const magnitude = Math.abs(rounded);
  if (magnitude >= 1e-6 && magnitude < 1e15) {
    return rounded.toFixed(Math.min(20, Math.max(0, digits - 1 - Math.floor(Math.log10(magnitude))))).replace(/\.?0+$/, "");
  }
  return String(rounded);
}

export interface ParsedComment {
  /** The description without the parts that the unit chip and the converted value already show. */
  description: string;
  /** A conversion that the comment itself spells out, such as `~1.7 deg/s`. */
  hint: string | null;
  unit: UnitId | null;
  /** How certain the unit is: 3 explicit (in parentheses or after "in"), 2 plain, 1 a conversion, 0 none. */
  unitScore: number;
  raw: string;
}

interface UnitMention {
  unit: UnitId;
  start: number;
  end: number;
  score: number;
}

function unitFromPhrase(phrase: string): UnitId | null {
  for (const candidate of UNIT_PHRASES) {
    if (candidate.regex.test(phrase)) {
      return candidate.id;
    }
  }
  return null;
}

function findUnitMentions(text: string): UnitMention[] {
  const mentions: UnitMention[] = [];
  for (const match of text.matchAll(UNIT_REGEX)) {
    const unit = unitFromPhrase(match[0]);
    if (!unit) {
      continue;
    }
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const before = text.slice(0, start);
    const after = text.slice(end);
    let score = 2;
    if (/\(\s*$/.test(before) && /^\s*\)/.test(after)) {
      score = 3;
    } else if (/\bin\s+$/i.test(before)) {
      score = 3;
    } else if (/[~\d.]\s*$/.test(before)) {
      score = 1;
    }
    mentions.push({ unit, start, end, score });
  }
  return mentions;
}

function collapseSpaces(text: string): string {
  return text.replace(/\s{2,}/g, " ").trim();
}

function trimPunctuation(text: string): string {
  return text.replace(/^[\s.,;:-]+/, "").replace(/[\s.,;:-]+$/, "");
}

const NUMBER_SOURCE = "~?[-+]?\\d+(?:\\.\\d+)?";

/** Splits an inline comment into a description and a unit. */
export function parseFieldComment(comment: string | null | undefined): ParsedComment {
  const raw = (comment ?? "").trim();
  if (!raw) {
    return { description: "", hint: null, unit: null, unitScore: 0, raw };
  }
  const mentions = findUnitMentions(raw);
  let primary: UnitMention | null = null;
  for (const mention of mentions) {
    if (!primary || mention.score > primary.score) {
      primary = mention;
    }
  }

  let description = raw;
  let hint: string | null = null;

  // A leading conversion such as "~1.7 deg/s. Maximum angular speed in radians per second".
  const leading = new RegExp(`^(${NUMBER_SOURCE}\\s*(?:${ANY_UNIT_SOURCE}))\\s*[.;:,]\\s+`, "iu").exec(description);
  if (leading) {
    hint = leading[1].trim();
    description = description.slice(leading[0].length);
  } else {
    const onlyHint = new RegExp(`^${NUMBER_SOURCE}\\s*(?:${ANY_UNIT_SOURCE})[.;]?$`, "iu").exec(description);
    if (onlyHint) {
      return { description: "", hint: description.replace(/[.;]$/, ""), unit: primary?.unit ?? null, unitScore: primary?.score ?? 0, raw };
    }
  }

  if (primary) {
    // "(seconds)" next to the quantity it measures.
    description = description.replace(new RegExp(`\\s*\\(\\s*(?:${ANY_UNIT_SOURCE})\\s*\\)`, "giu"), "");
    // A trailing conversion: ": 30.0 degrees" or ": 20 minutes in seconds".
    description = description.replace(
      new RegExp(`\\s*[:,;]\\s*${NUMBER_SOURCE}\\s*(?:${ANY_UNIT_SOURCE})(?:\\s+in\\s+(?:${ANY_UNIT_SOURCE}))?\\s*$`, "iu"),
      ""
    );
    // "in meters" at the end of the description.
    description = description.replace(new RegExp(`\\s+in\\s+(?:${ANY_UNIT_SOURCE})\\s*$`, "iu"), "");
  }

  return {
    description: collapseSpaces(trimPunctuation(description)),
    hint,
    unit: primary?.unit ?? null,
    unitScore: primary?.score ?? 0,
    raw,
  };
}
