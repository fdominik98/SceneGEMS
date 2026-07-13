import type { ActorKinematicState, ActorStaticInfo } from "../../../domain/simulation/types";

interface Props {
  actors: ActorStaticInfo[];
  statesByActorId: Record<string, ActorKinematicState>;
  origin: { x: number; y: number };
  colorByActorId: Record<string, string>;
  stream?: "animation" | "simulation";
}

export function DomainsLayer({
  actors,
  statesByActorId,
  origin,
  colorByActorId,
  stream = "animation",
}: Props) {
  const isSimulation = stream === "simulation";
  return (
    <>
      {actors.map((actor) => {
        const state = statesByActorId[actor.id];
        if (!state) {
          return null;
        }
        return (
          <mesh
            key={actor.id}
            position={[state.x - origin.x, state.y - origin.y, 0]}
            renderOrder={isSimulation ? 3 : 2}
          >
            <ringGeometry
              args={[Math.max(0.1, actor.safetyRadius - 8), actor.safetyRadius, 64]}
            />
            <meshBasicMaterial
              color={colorByActorId[actor.id] ?? "#ef4444"}
              transparent
              opacity={isSimulation ? 0.32 : 0.28}
              depthWrite={false}
            />
          </mesh>
        );
      })}
    </>
  );
}
