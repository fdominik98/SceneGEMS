import type { ActorStaticInfo, SituationContextData } from "../../../domain/simulation/types";
import { renderRelationId } from "./renderRelationId";
import { GeneralMonitorList } from "./GeneralMonitorList";
import { fmtNum } from "./monitorFormat";
import { looksLikeSituationContexts } from "./monitorFieldShapes";
import { SITUATION_CONTEXT_HINTS } from "./monitorHints";
import { ActorTag, Chip, DirectionBadge, HintTh, MonitorSection } from "./monitorPrimitives";

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
        <span className="mon-card-sub meta" title={SITUATION_CONTEXT_HINTS.timeInContext}>
          {fmtNum(ctx.timeSpentInCurrentContext)} s in context
        </span>
      </div>
      <table className="mon-actor-table">
        <thead>
          <tr>
            <th scope="col">Vessel</th>
            <HintTh label="Avoidance" hint={SITUATION_CONTEXT_HINTS.avoidance} />
            <HintTh label="Judged" hint={SITUATION_CONTEXT_HINTS.judged} />
            <HintTh label="Role" hint={SITUATION_CONTEXT_HINTS.role} />
            <HintTh label="Global avoid." hint={SITUATION_CONTEXT_HINTS.globalAvoidance} />
            <HintTh label="Global role" hint={SITUATION_CONTEXT_HINTS.globalRole} />
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
                <DirectionBadge
                  dir={
                    ctx.effectiveAvoidanceDirectionByActorId?.[id] ??
                    ctx.avoidanceDirectionByActorId?.[id]
                  }
                />
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
  persistKey,
  contexts,
  actors,
}: {
  persistKey: string;
  contexts: SituationContextData[];
  actors: ActorStaticInfo[];
}) {
  if (contexts.length === 0) {
    return null;
  }
  if (!looksLikeSituationContexts(contexts)) {
    return <GeneralMonitorList persistKey={persistKey} title="Situation contexts" items={contexts} />;
  }
  return (
    <MonitorSection persistKey={persistKey} title="Situation contexts" badge={contexts.length}>
      <div className="frame-list-stack">
        {contexts.map((ctx, i) => (
          <ContextCard key={`${ctx.relationId}-${i}`} ctx={ctx} actors={actors} />
        ))}
      </div>
    </MonitorSection>
  );
}
