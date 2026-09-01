import type { ActorStaticInfo, SituationContextData } from "../../domain/simulation/types";
import { renderRelationId } from "./actorNameFormat";
import { GeneralMonitorList } from "./GeneralMonitorList";
import { fmtNum } from "./monitorFormat";
import { looksLikeSituationContexts } from "./monitorFieldShapes";
import { ActorTag, Chip, DirectionBadge, MonitorSection } from "./monitorPrimitives";

function RoleChip({ giveWay }: { giveWay: boolean }) {
  return giveWay ? <Chip label="give-way" tone="warn" /> : <Chip label="stand-on" tone="good" />;
}

function ContextCard({
  ctx,
  actors,
}: {
  ctx: SituationContextData;
  actors: ActorStaticInfo[];
}) {
  const ids = [ctx.actor1Id, ctx.actor2Id];
  return (
    <div className="mon-card">
      <div className="mon-card-head">
        <span className="mon-card-title">{renderRelationId(ctx.relationId)}</span>
        <Chip label={ctx.situationLabel || ctx.situationType} tone="info" />
        <span className="mon-card-sub meta">
          {fmtNum(ctx.timeSpentInCurrentContext)} s in context
        </span>
      </div>
      <table className="mon-actor-table">
        <thead>
          <tr>
            <th>Vessel</th>
            <th>Avoidance</th>
            <th>Role</th>
            <th>Global avoid.</th>
            <th>Global role</th>
          </tr>
        </thead>
        <tbody>
          {ids.map((id) => (
            <tr key={id}>
              <td>
                <ActorTag actors={actors} id={id} />
              </td>
              <td>
                <DirectionBadge dir={ctx.avoidanceDirectionByActorId?.[id]} />
              </td>
              <td>
                <RoleChip giveWay={Boolean(ctx.isGiveWayByActorId?.[id])} />
              </td>
              <td>
                <DirectionBadge dir={ctx.globalAvoidanceDirectionByActorId?.[id]} />
              </td>
              <td>
                <RoleChip giveWay={Boolean(ctx.globalGiveWayByActorId?.[id])} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SituationContextsSection({
  contexts,
  actors,
}: {
  contexts: SituationContextData[];
  actors: ActorStaticInfo[];
}) {
  if (contexts.length === 0) {
    return null;
  }
  if (!looksLikeSituationContexts(contexts)) {
    return <GeneralMonitorList title="Situation contexts" items={contexts} />;
  }
  return (
    <MonitorSection title="Situation contexts" badge={contexts.length}>
      <div className="frame-list-stack">
        {contexts.map((ctx, i) => (
          <ContextCard key={`${ctx.relationId}-${i}`} ctx={ctx} actors={actors} />
        ))}
      </div>
    </MonitorSection>
  );
}
