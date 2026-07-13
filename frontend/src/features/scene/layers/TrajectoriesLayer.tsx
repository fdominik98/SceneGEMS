import { Line } from "@react-three/drei";
import type { ActorKinematicState } from "../../../domain/simulation/types";

/** Same plane as vessel markers / domains / velocity (z=0) so layers stay aligned under perspective. */
const TRACE_Z = 0;

interface Props {
  trajectoriesByActorId: Record<string, ActorKinematicState[]>;
  origin: { x: number; y: number };
  colorByActorId: Record<string, string>;
  /** View zoom (from canvas); used to keep dash pattern readable. */
  zoomScale: number;
  /**
   * Animation stream: dashed traces. Simulation stream: solid traces + distinct styling
   * so the two overlays are easy to tell apart at a glance.
   */
  stream?: "animation" | "simulation";
}

export function TrajectoriesLayer({
  trajectoriesByActorId,
  origin,
  colorByActorId,
  zoomScale,
  stream = "animation",
}: Props) {
  const isSimulation = stream === "simulation";
  const dashScale = Math.max(0.25, 1.5 / Math.max(zoomScale, 0.05));
  const baseWidth = Math.min(4, Math.max(1, 1.2 * Math.min(zoomScale, 3.5)));
  const lineWidthPx = isSimulation ? Math.min(5, baseWidth + 0.85) : baseWidth;

  return (
    <>
      {Object.entries(trajectoriesByActorId).map(([actorId, points]) => {
        if (points.length < 2) {
          return null;
        }
        const color = colorByActorId[actorId] ?? "#94a3b8";
        return (
          <Line
            key={actorId}
            points={points.map(
              (p) => [p.x - origin.x, p.y - origin.y, TRACE_Z] as [number, number, number]
            )}
            color={color}
            lineWidth={lineWidthPx}
            dashed={!isSimulation}
            dashScale={dashScale}
            depthTest={false}
            depthWrite={false}
            renderOrder={isSimulation ? 9 : 8}
            transparent
            opacity={isSimulation ? 0.98 : 0.92}
          />
        );
      })}
    </>
  );
}
