import { Line } from "@react-three/drei";
import type { ActorKinematicState, ActorStaticInfo } from "../../../domain/simulation/types";
import { getVelocityComponents } from "../shipKinematics";
import { getVesselMarkerScale } from "./vesselMarkerScale";

const VECTOR_LENGTH_FACTOR = 0.7;

interface Props {
  actors: ActorStaticInfo[];
  statesByActorId: Record<string, ActorKinematicState>;
  origin: { x: number; y: number };
  colorByActorId: Record<string, string>;
  zoomScale: number;
  stream?: "animation" | "simulation";
}

export function VelocityVectorsLayer({
  actors,
  statesByActorId,
  origin,
  colorByActorId,
  zoomScale,
  stream = "animation",
}: Props) {
  const isSimulation = stream === "simulation";
  const lineWidth = isSimulation ? 2.15 : 1.6;
  return (
    <>
      {actors.map((actor) => {
        const state = statesByActorId[actor.id];
        if (!state) {
          return null;
        }

        const speed = Math.max(0, state.speed);
        if (speed < 1e-9) {
          return null;
        }

        const markerLength = getVesselMarkerScale(actor.length, actor.breadth, zoomScale)[0];
        const velocityScale = VECTOR_LENGTH_FACTOR * markerLength * 0.3;
        const { dx, dy } = getVelocityComponents(state, velocityScale);
        const len = Math.hypot(dx, dy);
        const tipScale = Math.max(0.05, len * 0.01);

        const endX = state.x + dx - origin.x;
        const endY = state.y + dy - origin.y;
        return (
          <group key={actor.id} renderOrder={isSimulation ? 13 : 11}>
            <Line
              points={[
                [state.x - origin.x, state.y - origin.y, 0],
                [endX, endY, 0],
              ]}
              color={colorByActorId[actor.id] ?? "#f97316"}
              lineWidth={lineWidth}
            />
            <mesh
              position={[endX, endY, 0]}
              rotation={[0, 0, state.heading - Math.PI / 2]}
              renderOrder={12}
            >
              <coneGeometry args={[2.4 * tipScale, 6 * tipScale, 14]} />
              <meshBasicMaterial color={colorByActorId[actor.id] ?? "#f97316"} />
            </mesh>
          </group>
        );
      })}
    </>
  );
}
