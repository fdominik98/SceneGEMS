import type { ActorKinematicState, ActorStaticInfo } from "../../../domain/simulation/types";
import { getRenderHeading } from "../shipKinematics";
import { getVesselMarkerScale } from "./vesselMarkerScale";

interface Props {
  actors: ActorStaticInfo[];
  statesByActorId: Record<string, ActorKinematicState>;
  origin: { x: number; y: number };
  zoomScale: number;
  colorByActorId: Record<string, string>;
  stream?: "animation" | "simulation";
}

export function VesselMarkerLayer({
  actors,
  statesByActorId,
  origin,
  zoomScale,
  colorByActorId,
  stream = "animation",
}: Props) {
  const renderOrder = stream === "simulation" ? 21 : 20;
  return (
    <>
      {actors.map((actor) => {
        const state = statesByActorId[actor.id];
        if (!state) {
          return null;
        }
        const renderHeading = getRenderHeading(state);
        return (
          <mesh
            key={`${actor.id}-marker`}
            position={[state.x - origin.x, state.y - origin.y, 0]}
            rotation={[0, 0, renderHeading]}
            scale={getVesselMarkerScale(actor.length, actor.breadth, zoomScale)}
            renderOrder={renderOrder}
          >
            <circleGeometry args={[1, 36]} />
            <meshBasicMaterial
              color={colorByActorId[actor.id] ?? "#f59e0b"}
              depthTest={false}
              depthWrite={false}
              opacity={1}
              transparent
            />
          </mesh>
        );
      })}
    </>
  );
}
