import { Fragment, type ReactNode } from "react";

export function formatRelationId(relationId: string): string {
  return relationId.replace(/->/g, " - ");
}

export function renderRelationId(relationId: string): ReactNode {
  if (!relationId.includes("->")) {
    return renderActorName(relationId);
  }
  const parts = relationId.split("->");
  return parts.map((part, index) => (
    <Fragment key={index}>
      {index > 0 ? " - " : null}
      {renderActorName(part)}
    </Fragment>
  ));
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
