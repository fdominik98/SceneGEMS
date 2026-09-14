import { createContext, Fragment, useContext, useMemo, type ReactNode } from "react";
import type { ActorStaticInfo } from "../../domain/simulation/types";

/** Actor id to display name, so relation ids like "0->1" render as "OS_0 - TS_1". */
export type ActorNameMap = Readonly<Record<string, string>>;

const ActorNamesContext = createContext<ActorNameMap>({});

export function ActorNamesProvider({
  actors,
  children,
}: {
  actors: ActorStaticInfo[] | undefined;
  children: ReactNode;
}) {
  const names = useMemo(() => buildActorNameMap(actors), [actors]);
  return <ActorNamesContext.Provider value={names}>{children}</ActorNamesContext.Provider>;
}

export function useActorNames(): ActorNameMap {
  return useContext(ActorNamesContext);
}

export function buildActorNameMap(actors: ActorStaticInfo[] | undefined): ActorNameMap {
  const out: Record<string, string> = {};
  for (const actor of actors ?? []) {
    out[actor.id] = actor.name || actor.id;
  }
  return out;
}

function relationParts(relationId: string, names: ActorNameMap): string[] {
  return relationId.split("->").map((id) => names[id] ?? id);
}

export function formatRelationId(relationId: string, names: ActorNameMap = {}): string {
  return relationParts(relationId, names).join(" - ");
}

function RelationLabel({ relationId }: { relationId: string }) {
  const names = useActorNames();
  const parts = relationParts(relationId, names);
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? " - " : null}
          {renderActorName(part)}
        </Fragment>
      ))}
    </>
  );
}

export function renderRelationId(relationId: string): ReactNode {
  return <RelationLabel relationId={relationId} />;
}

export function renderActorName(name: string): ReactNode {
  const match = name.match(/^(.*)_(\d+)$/);
  if (!match) {
    return name;
  }
  const [, base, index] = match;
  return (
    <>
      {base}
      <sub>{index}</sub>
    </>
  );
}
