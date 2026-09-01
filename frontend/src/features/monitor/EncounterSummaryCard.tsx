import type {
  ActorStaticInfo,
  ColregsMonitorStateData,
  ManeuverStateData,
  RuleResultData,
  SituationContextData,
} from "../../domain/simulation/types";
import { renderRelationId } from "./actorNameFormat";
import { humanizeEnum, resolveActorLabel } from "./monitorFormat";
import { Chip, MonitorSection } from "./monitorPrimitives";

interface EncounterSummaryCardProps {
  situationContexts: SituationContextData[];
  colregsStates: ColregsMonitorStateData[];
  ruleResults: RuleResultData[];
  maneuverStates: ManeuverStateData[];
  actors: ActorStaticInfo[];
}

function giveWayLabel(
  ctx: SituationContextData | undefined,
  actors: ActorStaticInfo[],
): string | null {
  if (!ctx) {
    return null;
  }
  const map = ctx.globalGiveWayByActorId ?? ctx.isGiveWayByActorId ?? {};
  const giver = Object.keys(map).find((id) => map[id]);
  return giver ? resolveActorLabel(actors, giver) : null;
}

/** Maneuver whose relation or actor matches this relation's first actor. */
function maneuverFor(
  relationId: string,
  maneuvers: ManeuverStateData[],
): ManeuverStateData | undefined {
  const firstActor = relationId.split("->")[0];
  return (
    maneuvers.find((m) => m.relationId === relationId) ??
    maneuvers.find((m) => m.actorId === firstActor)
  );
}

export function EncounterSummaryCard({
  situationContexts,
  colregsStates,
  ruleResults,
  maneuverStates,
  actors,
}: EncounterSummaryCardProps) {
  const relationIds = [
    ...new Set([
      ...situationContexts.map((c) => c.relationId),
      ...colregsStates.map((c) => c.relationId),
      ...ruleResults.map((r) => r.relationId),
    ]),
  ];

  if (relationIds.length === 0) {
    return null;
  }

  const rows = relationIds.map((relationId) => {
    const ctx = situationContexts.find((c) => c.relationId === relationId);
    const col = colregsStates.find((c) => c.relationId === relationId);
    const rr = ruleResults.find((r) => r.relationId === relationId);
    const man = maneuverFor(relationId, maneuverStates);
    const risky = Boolean(
      col?.actorsOnCollisionCourse || col?.actorsViolateSafetyDomain || col?.actorsHaveLowTcpa,
    );
    const failed = rr?.overallStatus === "FAILED";
    return { relationId, ctx, col, rr, man, risky, failed };
  });

  const anyAlert = rows.some((r) => r.risky || r.failed);

  return (
    <MonitorSection
      title="Encounter summary"
      badge={rows.length}
      defaultOpen
      tone={anyAlert ? "bad" : undefined}
    >
      <div className="mon-enc-list">
        {rows.map(({ relationId, ctx, col, rr, man }) => {
          const giver = giveWayLabel(ctx, actors);
          return (
            <div className="mon-enc-row" key={relationId}>
              <span className="mon-enc-relation">{renderRelationId(relationId)}</span>
              {ctx ? <Chip label={ctx.situationLabel || ctx.situationType} tone="info" /> : null}
              {giver ? <Chip label={`${giver} gives way`} tone="warn" /> : null}
              {col?.actorsOnCollisionCourse ? <Chip label="collision course" tone="danger" /> : null}
              {col?.actorsViolateSafetyDomain ? <Chip label="safety domain" tone="danger" /> : null}
              {col?.actorsHaveLowTcpa ? <Chip label="low TCPA" tone="danger" /> : null}
              {rr ? (
                rr.overallStatus === "FAILED" ? (
                  <Chip
                    label={`${rr.failedRules.length} rule${rr.failedRules.length === 1 ? "" : "s"} failed`}
                    tone="danger"
                  />
                ) : (
                  <Chip label="rules ok" tone="good" />
                )
              ) : null}
              {man && man.maneuverType ? (
                <Chip label={humanizeEnum(man.maneuverType)} tone="neutral" />
              ) : null}
            </div>
          );
        })}
      </div>
    </MonitorSection>
  );
}
