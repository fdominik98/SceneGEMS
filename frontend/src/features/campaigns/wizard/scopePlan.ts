import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import type { ScopeEntryDraft } from "./wizardState";

/**
 * Which catalog classes a scope entry selects, and how many cases a campaign plans, worked out in
 * the browser from the class catalog the same way the master does (`ClassCatalog.expand`: a pattern
 * without a slash matches folders, one with a slash matches class ids, shell wildcards). The master
 * has the last word: the review step validates the config on the server.
 */

/** Translates a shell pattern (`*`, `?`, `[seq]`, `[!seq]`) into a regular expression that matches the whole text. */
export function globToRegExp(pattern: string): RegExp {
  let source = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    if (char === "*") {
      source += ".*";
    } else if (char === "?") {
      source += ".";
    } else if (char === "[") {
      const close = pattern.indexOf("]", index + 2);
      if (close === -1) {
        source += "\\[";
      } else {
        let body = pattern.slice(index + 1, close);
        const negate = body.startsWith("!");
        if (negate) {
          body = body.slice(1);
        }
        source += `[${negate ? "^" : ""}${body.replace(/\\/g, "\\\\").replace(/\]/g, "\\]")}]`;
        index = close;
      }
    } else {
      source += char.replace(/[.+^${}()|\\/]/g, "\\$&");
    }
  }
  return new RegExp(`^${source}$`, "s");
}

/** The classes a pattern names, in catalog order. */
export function expandPattern(pattern: string, classes: readonly CatalogClass[]): CatalogClass[] {
  const expression = globToRegExp(pattern);
  const byClassId = pattern.includes("/");
  return classes.filter((entry) => expression.test(byClassId ? entry.fec_id : entry.folder));
}

export interface ScopeEntryPlan {
  /** The classes the entry brings in that no earlier entry has. */
  classes: CatalogClass[];
  /** Class ids named by the entry that are not in the catalog. */
  unknownClasses: string[];
  /** Patterns that match no class. */
  emptyPatterns: string[];
  /** Classes the entry names that an earlier entry has already. */
  duplicates: string[];
  casesPlanned: number;
}

export interface ScopePlan {
  entries: ScopeEntryPlan[];
  classes: number;
  casesPlanned: number;
}

/** The plan of the scope: each class counts once, for the first entry that names it (as the master resolves it). */
export function planScope(scope: readonly ScopeEntryDraft[], catalog: readonly CatalogClass[]): ScopePlan {
  const byId = new Map(catalog.map((entry) => [entry.fec_id, entry]));
  const taken = new Set<string>();
  const entries: ScopeEntryPlan[] = [];
  for (const entry of scope) {
    const named: CatalogClass[] = [];
    const unknownClasses: string[] = [];
    const emptyPatterns: string[] = [];
    for (const classId of entry.classes) {
      const found = byId.get(classId);
      if (found) {
        named.push(found);
      } else {
        unknownClasses.push(classId);
      }
    }
    for (const pattern of entry.patterns) {
      const matched = expandPattern(pattern, catalog);
      if (matched.length === 0) {
        emptyPatterns.push(pattern);
      }
      named.push(...matched);
    }
    const classes: CatalogClass[] = [];
    const duplicates: string[] = [];
    const own = new Set<string>();
    for (const found of named) {
      if (own.has(found.fec_id)) {
        continue;
      }
      own.add(found.fec_id);
      if (taken.has(found.fec_id)) {
        duplicates.push(found.fec_id);
      } else {
        classes.push(found);
      }
    }
    for (const found of classes) {
      taken.add(found.fec_id);
    }
    entries.push({ classes, unknownClasses, emptyPatterns, duplicates, casesPlanned: classes.length * (entry.quota ?? 0) });
  }
  return { entries, classes: taken.size, casesPlanned: entries.reduce((total, entry) => total + entry.casesPlanned, 0) };
}

export interface FolderSummary {
  folder: string;
  classes: number;
  vessels: number[];
  obstacles: number[];
}

/** The catalog's folders in catalog order with their class counts, and the vessel and obstacle counts they hold. */
export function summarizeFolders(catalog: readonly CatalogClass[]): FolderSummary[] {
  const folders = new Map<string, FolderSummary>();
  for (const entry of catalog) {
    let summary = folders.get(entry.folder);
    if (!summary) {
      summary = { folder: entry.folder, classes: 0, vessels: [], obstacles: [] };
      folders.set(entry.folder, summary);
    }
    summary.classes += 1;
    if (!summary.vessels.includes(entry.vessel_count)) {
      summary.vessels.push(entry.vessel_count);
    }
    if (!summary.obstacles.includes(entry.obstacle_count)) {
      summary.obstacles.push(entry.obstacle_count);
    }
  }
  return [...folders.values()];
}
