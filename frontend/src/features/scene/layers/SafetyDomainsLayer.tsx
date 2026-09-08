import { Line } from "@react-three/drei";
import { useMemo } from "react";
import type {
  SafetyDomainShape,
  SituationContextData,
  StaticAvoidanceDomain,
} from "../../../domain/simulation/types";

/** Same plane as the other overlays so nothing floats above the scene under perspective. */
const DOMAIN_Z = 0;
const CIRCLE_SEGMENTS = 72;

type Point3 = [number, number, number];

interface Props {
  situationContexts: SituationContextData[];
  origin: { x: number; y: number };
  colorByActorId: Record<string, string>;
  stream?: "animation" | "simulation";
  /** Per-encounter safety domain outlines (Rule-specific: head-on, crossing, overtaking). */
  showSafetyDomains: boolean;
  /** Domains frozen when the encounter started, which each vessel has to go around. */
  showStaticAvoidanceDomains: boolean;
}

/** Closed outline for a parametric safety domain, in world coordinates. */
function safetyDomainOutline(domain: SafetyDomainShape): [number, number][] {
  const [cx, cy] = domain.center;
  const cos = Math.cos(domain.heading);
  const sin = Math.sin(domain.heading);
  const rotate = (x: number, y: number): [number, number] => [
    cx + x * cos - y * sin,
    cy + x * sin + y * cos,
  ];

  if (domain.shape === "rectangle") {
    const a = domain.a ?? 0;
    const b = domain.b ?? 0;
    return [
      rotate(-a, -b),
      rotate(a, -b),
      rotate(a, b),
      rotate(-a, b),
      rotate(-a, -b),
    ];
  }

  // Circle is the degenerate ellipse with a === b === radius.
  const a = domain.shape === "circle" ? (domain.radius ?? 0) : (domain.a ?? 0);
  const b = domain.shape === "circle" ? (domain.radius ?? 0) : (domain.b ?? 0);
  const points: [number, number][] = [];
  for (let i = 0; i <= CIRCLE_SEGMENTS; i += 1) {
    const t = (i / CIRCLE_SEGMENTS) * Math.PI * 2;
    points.push(rotate(a * Math.cos(t), b * Math.sin(t)));
  }
  return points;
}

function circleOutline(center: [number, number], radius: number): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i <= CIRCLE_SEGMENTS; i += 1) {
    const t = (i / CIRCLE_SEGMENTS) * Math.PI * 2;
    points.push([center[0] + radius * Math.cos(t), center[1] + radius * Math.sin(t)]);
  }
  return points;
}

interface SafetyOutline {
  key: string;
  color: string;
  points: Point3[];
}

interface AvoidanceDisc {
  key: string;
  color: string;
  center: [number, number];
  radius: number;
  points: Point3[];
}

/**
 * Draws the COLREGS domains the monitor reports for the current frame: the
 * per-encounter safety domain of each vessel, and the static avoidance domains
 * (potential collision domains frozen at the start of the encounter).
 *
 * The backend sends shape parameters rather than polygons, so the curves are built
 * here. Domains are per encounter, so a vessel in two encounters has two outlines.
 */
export function SafetyDomainsLayer({
  situationContexts,
  origin,
  colorByActorId,
  stream = "animation",
  showSafetyDomains,
  showStaticAvoidanceDomains,
}: Props) {
  const isSimulation = stream === "simulation";

  const { safetyOutlines, avoidanceDiscs } = useMemo(() => {
    const outlines: SafetyOutline[] = [];
    const discs: AvoidanceDisc[] = [];
    const seenDiscs = new Set<string>();

    for (const context of situationContexts) {
      if (showSafetyDomains && context.safetyDomainsByActorId) {
        for (const [actorId, domain] of Object.entries(context.safetyDomainsByActorId)) {
          outlines.push({
            key: `${context.relationId}:${actorId}`,
            color: colorByActorId[actorId] ?? "#f97316",
            points: safetyDomainOutline(domain).map(
              ([x, y]) => [x - origin.x, y - origin.y, DOMAIN_Z] as Point3
            ),
          });
        }
      }

      if (showStaticAvoidanceDomains && context.staticAvoidanceDomainsByActorId) {
        for (const [actorId, domains] of Object.entries(
          context.staticAvoidanceDomainsByActorId
        )) {
          domains.forEach((domain: StaticAvoidanceDomain, index) => {
            // The collection unions overlapping encounters, so the same circle can be
            // listed more than once. Drawing it once keeps the fill from stacking up.
            const identity = `${actorId}:${domain.center[0].toFixed(2)}:${domain.center[1].toFixed(2)}:${domain.radius.toFixed(2)}`;
            if (seenDiscs.has(identity)) {
              return;
            }
            seenDiscs.add(identity);
            discs.push({
              key: `${context.relationId}:${actorId}:${index}`,
              color: colorByActorId[actorId] ?? "#f97316",
              center: [domain.center[0] - origin.x, domain.center[1] - origin.y],
              radius: domain.radius,
              points: circleOutline(domain.center, domain.radius).map(
                ([x, y]) => [x - origin.x, y - origin.y, DOMAIN_Z] as Point3
              ),
            });
          });
        }
      }
    }

    return { safetyOutlines: outlines, avoidanceDiscs: discs };
  }, [
    colorByActorId,
    origin.x,
    origin.y,
    showSafetyDomains,
    showStaticAvoidanceDomains,
    situationContexts,
  ]);

  return (
    <>
      {avoidanceDiscs.map((disc) => (
        <group key={disc.key}>
          <mesh
            position={[disc.center[0], disc.center[1], DOMAIN_Z]}
            renderOrder={isSimulation ? 1 : 0}
          >
            <circleGeometry args={[disc.radius, CIRCLE_SEGMENTS]} />
            <meshBasicMaterial
              color={disc.color}
              transparent
              opacity={isSimulation ? 0.14 : 0.11}
              depthWrite={false}
            />
          </mesh>
          <Line
            points={disc.points}
            color={disc.color}
            lineWidth={1}
            dashed
            dashScale={40}
            depthTest={false}
            depthWrite={false}
            renderOrder={isSimulation ? 5 : 4}
            transparent
            opacity={0.55}
          />
        </group>
      ))}

      {safetyOutlines.map((outline) => (
        <Line
          key={outline.key}
          points={outline.points}
          color={outline.color}
          lineWidth={isSimulation ? 2 : 1.6}
          depthTest={false}
          depthWrite={false}
          renderOrder={isSimulation ? 7 : 6}
          transparent
          opacity={isSimulation ? 0.9 : 0.8}
        />
      ))}
    </>
  );
}
