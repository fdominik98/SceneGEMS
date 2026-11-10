/**
 * The relations of an explored FEC in words. A generated model is a complete `.problem` text: the
 * metamodel and constraints, then a `declare` line with the objects and their facts. The COLREGS
 * relations between the vessels, and the obstacles in a dangerous sector, are the facts after the
 * last `declare` line; `default` lines and negated facts (`!`) say what does not hold and are left out.
 */

export const FEC_RELATIONS = ["headOn", "overtakingToPort", "overtakingToStarboard", "crossingFromPort", "atDangerousHeadOnSectorOf"] as const;
export type FecRelationName = (typeof FEC_RELATIONS)[number];

export interface FecRelation {
  relation: FecRelationName;
  from: string;
  to: string;
}

const FACT = /^([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\.\s*(?:\/\/.*|%.*)?$/;

function isRelation(name: string): name is FecRelationName {
  return (FEC_RELATIONS as readonly string[]).includes(name);
}

/** The relation facts of a FEC's text in their order; headOn, which holds in both directions, once. */
export function parseFecRelations(text: string): FecRelation[] {
  const lines = text.split(/\r?\n/);
  let start = -1;
  for (const [index, line] of lines.entries()) {
    if (/^\s*declare\b/.test(line)) {
      start = index + 1;
    }
  }
  if (start < 0) {
    return [];
  }
  const relations: FecRelation[] = [];
  const seen = new Set<string>();
  for (const raw of lines.slice(start)) {
    const line = raw.trim();
    if (line.length === 0 || line.startsWith("default") || line.startsWith("!")) {
      continue;
    }
    const match = FACT.exec(line);
    if (match === null || !isRelation(match[1])) {
      continue;
    }
    const [, relation, from, to] = match as unknown as [string, FecRelationName, string, string];
    const key = relation === "headOn" ? `${relation}:${[from, to].sort().join(",")}` : `${relation}:${from},${to}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    relations.push({ relation, from, to });
  }
  return relations;
}

/** One relation in words. */
export function describeFecRelation({ relation, from, to }: FecRelation): string {
  switch (relation) {
    case "headOn":
      return `${from} and ${to} head-on`;
    case "overtakingToPort":
      return `${from} overtakes ${to} to port`;
    case "overtakingToStarboard":
      return `${from} overtakes ${to} to starboard`;
    case "crossingFromPort":
      return `${from} crosses ${to} from port`;
    case "atDangerousHeadOnSectorOf":
      return `${from} in the dangerous head-on sector of ${to}`;
  }
}

/** Every relation of a FEC's text in words, separated by semicolons; "no relations" when it has none. */
export function fecRelationSummary(text: string): string {
  const relations = parseFecRelations(text);
  return relations.length === 0 ? "no relations" : relations.map(describeFecRelation).join("; ");
}
