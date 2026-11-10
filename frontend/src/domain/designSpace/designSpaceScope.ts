/**
 * The scope of a design space exploration (the campaign config's `design_space_exploration.scope`):
 * how many objects of each class a generated model has. Entries are comma separated, each
 * `Type = n` or `Type = a..b` with whole numbers and a <= b, as the master checks them. The
 * workbench page and the wizard check the scope with this module as it is typed.
 */

export const SCOPE_PLACEHOLDER = "TS = 2, StaticObstacle = 0";

export const SCOPE_FORM = "Type = n or Type = a..b, separated by commas";

export interface ScopeEntry {
  type: string;
  min: number;
  max: number;
}

export type ScopeCheck = { ok: true; entries: ScopeEntry[] } | { ok: false; message: string };

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const WHOLE = /^\d+$/;
const RANGE = /^(\d+)\s*\.\.\s*(\d+)$/;

function ordinal(index: number): string {
  return `entry ${index + 1}`;
}

/** Parses a scope; the message says which entry is wrong and the form it should have. */
export function parseDesignSpaceScope(text: string): ScopeCheck {
  if (text.trim().length === 0) {
    return { ok: false, message: `Enter a scope, for example ${SCOPE_PLACEHOLDER}.` };
  }
  const parts = text.split(",");
  const entries: ScopeEntry[] = [];
  const seen = new Set<string>();
  for (const [index, raw] of parts.entries()) {
    const part = raw.trim();
    const where = parts.length === 1 ? "The scope" : `The ${ordinal(index)}`;
    if (part.length === 0) {
      return { ok: false, message: `${where} is empty. Write ${SCOPE_FORM}.` };
    }
    const equals = part.indexOf("=");
    if (equals < 0) {
      return { ok: false, message: `${where} ("${part}") has no "=". Write ${SCOPE_FORM}.` };
    }
    const type = part.slice(0, equals).trim();
    const value = part.slice(equals + 1).trim();
    if (!IDENTIFIER.test(type)) {
      return {
        ok: false,
        message: `${where} ("${part}") does not start with a class name: ${type.length === 0 ? "it is missing" : `"${type}" is not one`}. Write ${SCOPE_FORM}.`,
      };
    }
    if (seen.has(type)) {
      return { ok: false, message: `${where} gives ${type} a second time. Give each class one entry.` };
    }
    let min: number;
    let max: number;
    const range = RANGE.exec(value);
    if (WHOLE.test(value)) {
      min = Number(value);
      max = min;
    } else if (range !== null) {
      min = Number(range[1]);
      max = Number(range[2]);
      if (min > max) {
        return { ok: false, message: `${where} ("${part}") is a range from ${min} down to ${max}. The lower bound comes first: ${type} = ${max}..${min}.` };
      }
    } else {
      return {
        ok: false,
        message: `${where} ("${part}") needs a whole number n or a range a..b after "=", for example ${type} = 2 or ${type} = 0..2.`,
      };
    }
    seen.add(type);
    entries.push({ type, min, max });
  }
  return { ok: true, entries };
}

/** The message of a scope that is not valid, null for a valid one. */
export function scopeProblem(text: string): string | null {
  const check = parseDesignSpaceScope(text);
  return check.ok ? null : check.message;
}

/** A scope as the config writes it: the entries in their order, `Type = n` or `Type = a..b`. */
export function formatDesignSpaceScope(entries: readonly ScopeEntry[]): string {
  return entries.map((entry) => `${entry.type} = ${entry.min === entry.max ? entry.min : `${entry.min}..${entry.max}`}`).join(", ");
}
