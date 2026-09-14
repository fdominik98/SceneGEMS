import { Line } from "@react-three/drei";
import { useMemo } from "react";
import type { ManeuveringDomain, SituationContextData } from "../../../domain/simulation/types";

const DOMAIN_Z = 0;
export const MANEUVERING_DOMAIN_KITE_COLOR = "#f5d76e";

type Point3 = [number, number, number];

export interface ManeuveringDomainDrawing {
  key: string;
  actorId: string;
  color: string;
  kite: [number, number][];
  hold: [number, number][];
  holdHeadingChangeDeg?: number;
}

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
  return [...domain.vertices, domain.vertices[0]];
}

interface Props {
  situationContexts: SituationContextData[];
  origin: { x: number; y: number };
  colorByActorId: Record<string, string>;
  stream?: "animation" | "simulation";
}

/** Planner corridor A-B-C-D. Gold kite is the full envelope; actor-colored line is the hold course A-B-C-D. */
export function ManeuveringDomainsLayer({
  situationContexts,
  origin,
  colorByActorId,
  stream = "animation",
}: Props) {
  const isSimulation = stream === "simulation";
  const drawings = useMemo(
    () => collectManeuveringDomainDrawings(situationContexts, colorByActorId),
    [colorByActorId, situationContexts]
  );

  const shifted = useMemo(
    () =>
      drawings.map((drawing) => ({
        ...drawing,
        kite3: drawing.kite.map(
          ([x, y]) => [x - origin.x, y - origin.y, DOMAIN_Z] as Point3
        ),
        hold3: drawing.hold.map(
          ([x, y]) => [x - origin.x, y - origin.y, DOMAIN_Z] as Point3
        ),
      })),
    [drawings, origin.x, origin.y]
  );

  return (
    <>
      {shifted.map((drawing) => (
        <group key={drawing.key}>
          {drawing.kite3.length > 1 && (
            <Line
              points={drawing.kite3}
              color={MANEUVERING_DOMAIN_KITE_COLOR}
              lineWidth={isSimulation ? 2.2 : 1.8}
              dashed
              dashScale={28}
              depthTest={false}
              depthWrite={false}
              renderOrder={isSimulation ? 8 : 7}
              transparent
              opacity={0.95}
            />
          )}
          {drawing.hold3.length > 1 && (
            <Line
              points={drawing.hold3}
              color={drawing.color}
              lineWidth={isSimulation ? 3 : 2.4}
              depthTest={false}
              depthWrite={false}
              renderOrder={isSimulation ? 9 : 8}
              transparent
              opacity={0.95}
            />
          )}
        </group>
      ))}
    </>
  );
}
