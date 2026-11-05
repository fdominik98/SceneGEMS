import type {
  ManeuveringDomain,
  SafetyDomainShape,
  SituationContextData,
  StaticAvoidanceDomain,
} from "../../../domain/simulation/types";

/** Gold of the give-way corridor (A-B-C-D kite), on the canvas and the nautical map. */
export const MANEUVERING_DOMAIN_KITE_COLOR = "var(--canvas-kite)";

export interface ManeuveringDomainDrawing {
  key: string;
  actorId: string;
  color: string;
  kite: [number, number][];
  hold: [number, number][];
  holdHeadingChangeDeg?: number;
}

/** One corridor per give-way actor (the union over its encounters, sent once per context). */
export function collectManeuveringDomainDrawings(
  situationContexts: SituationContextData[],
  colorByActorId: Record<string, string>
): ManeuveringDomainDrawing[] {
  const drawings: ManeuveringDomainDrawing[] = [];
  const seen = new Set<string>();
  for (const context of situationContexts) {
    const domains = context.maneuveringDomainsByActorId;
    if (!domains) {
      continue;
    }
    for (const [actorId, domain] of Object.entries(domains)) {
      if (seen.has(actorId)) {
        continue;
      }
      seen.add(actorId);
      drawings.push({
        key: actorId,
        actorId,
        color: colorByActorId[actorId] ?? MANEUVERING_DOMAIN_KITE_COLOR,
        kite: closedKite(domain),
        hold: domain.holdPolyline,
        holdHeadingChangeDeg: domain.holdHeadingChangeDeg,
      });
    }
  }
  return drawings;
}

function closedKite(domain: ManeuveringDomain): [number, number][] {
  if (domain.vertices.length === 0) {
    return [];
  }
  return [...domain.vertices, domain.vertices[0]!];
}

export interface SafetyDomainDrawing {
  key: string;
  actorId: string;
  domain: SafetyDomainShape;
}

export interface StaticAvoidanceDrawing {
  key: string;
  actorId: string;
  disc: StaticAvoidanceDomain;
}

/** Safety domains per encounter and actor: a vessel in two encounters has two outlines. */
export function collectSafetyDomains(situationContexts: SituationContextData[]): SafetyDomainDrawing[] {
  const out: SafetyDomainDrawing[] = [];
  for (const context of situationContexts) {
    for (const [actorId, domain] of Object.entries(context.safetyDomainsByActorId ?? {})) {
      out.push({ key: `${context.relationId}:${actorId}`, actorId, domain });
    }
  }
  return out;
}

export function collectStaticAvoidanceDomains(
  situationContexts: SituationContextData[]
): StaticAvoidanceDrawing[] {
  const out: StaticAvoidanceDrawing[] = [];
  for (const context of situationContexts) {
    for (const [actorId, discs] of Object.entries(context.staticAvoidanceDomainsByActorId ?? {})) {
      discs.forEach((disc, index) => {
        out.push({ key: `${context.relationId}:${actorId}:${index}`, actorId, disc });
      });
    }
  }
  return out;
}
