import type { ActorStaticInfo, ColregsMonitorStateData } from "../../domain/simulation/types";
import { renderRelationId } from "./actorNameFormat";
import { GeneralMonitorList } from "./GeneralMonitorList";
import { looksLikeColregsStates } from "./monitorFieldShapes";
import { ActorTag, BoolChip, BoolDot, MonitorSection } from "./monitorPrimitives";

const PER_ACTOR_COLUMNS: { key: keyof ColregsMonitorStateData; label: string }[] = [
  { key: "rightOfStartStateByActorId", label: "Right of start" },
  { key: "leftOfStartStateByActorId", label: "Left of start" },
  { key: "haveBeenInRightManeuverByActorId", label: "Was in right man." },
  { key: "haveBeenInLeftManeuverByActorId", label: "Was in left man." },
  { key: "passedPotentialCollisionDomainByActorId", label: "Passed coll. domain" },
  { key: "inFrontOfPotentialCollisionDomainByActorId", label: "In front of domain" },
];

function actorIdsOf(row: ColregsMonitorStateData): string[] {
  const ids = new Set<string>();
  for (const { key } of PER_ACTOR_COLUMNS) {
    const map = row[key] as Record<string, boolean> | undefined;
    if (map) {
      Object.keys(map).forEach((id) => ids.add(id));
    }
  }
  return [...ids];
}

function StateCard({
  row,
  actors,
}: {
  row: ColregsMonitorStateData;
  actors: ActorStaticInfo[];
}) {
  const ids = actorIdsOf(row);
  const anyRisk =
    row.actorsViolateSafetyDomain || row.actorsOnCollisionCourse || row.actorsHaveLowTcpa;
  return (
    <div className={`mon-card${anyRisk ? " mon-card--alert" : ""}`}>
      <div className="mon-card-head">
        <span className="mon-card-title">{renderRelationId(row.relationId)}</span>
      </div>

      <p className="mon-micro">Perception</p>
      <div className="mon-chip-row">
        <BoolChip label="See each other" value={row.actorsSeeEachOther} tone="neutral" />
        <BoolChip label="Passed each other" value={row.actorsPassedEachOther} tone="neutral" />
      </div>

      <p className="mon-micro">Risk</p>
      <div className="mon-chip-row">
        <BoolChip label="Collision course" value={row.actorsOnCollisionCourse} tone="danger" />
        <BoolChip
          label="Safety domain violated"
          value={row.actorsViolateSafetyDomain}
          tone="danger"
        />
        <BoolChip label="Low TCPA" value={row.actorsHaveLowTcpa} tone="danger" />
      </div>

      {ids.length > 0 ? (
        <>
          <p className="mon-micro">Per vessel</p>
          <div className="mon-table-scroll">
            <table className="mon-actor-table mon-actor-table--dense">
              <thead>
                <tr>
                  <th>Vessel</th>
                  {PER_ACTOR_COLUMNS.map((c) => (
                    <th key={String(c.key)}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ids.map((id) => (
                  <tr key={id}>
                    <td>
                      <ActorTag actors={actors} id={id} />
                    </td>
                    {PER_ACTOR_COLUMNS.map((c) => {
                      const map = row[c.key] as Record<string, boolean> | undefined;
                      return (
                        <td key={String(c.key)} className="mon-dot-cell">
                          <BoolDot value={Boolean(map?.[id])} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function ColregsMonitorStateSection({
  states,
  actors,
}: {
  states: ColregsMonitorStateData[];
  actors: ActorStaticInfo[];
}) {
  if (states.length === 0) {
    return null;
  }
  if (!looksLikeColregsStates(states)) {
    return <GeneralMonitorList title="COLREGS monitor state" items={states} />;
  }
  const anyRisk = states.some(
    (s) => s.actorsViolateSafetyDomain || s.actorsOnCollisionCourse || s.actorsHaveLowTcpa,
  );
  return (
    <MonitorSection
      title="COLREGS monitor state"
      badge={states.length}
      tone={anyRisk ? "bad" : undefined}
    >
      <div className="frame-list-stack">
        {states.map((row, i) => (
          <StateCard key={`${row.relationId}-${i}`} row={row} actors={actors} />
        ))}
      </div>
    </MonitorSection>
  );
}
