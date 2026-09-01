import type { ActorStaticInfo, ManeuverStateData } from "../../domain/simulation/types";
import { GeneralMonitorList } from "./GeneralMonitorList";
import { directionWord, fmtNum, humanizeEnum } from "./monitorFormat";
import { looksLikeManeuverStates } from "./monitorFieldShapes";
import { ActorTag, BoolChip, Chip, MiniBar, MonitorSection, StatTile } from "./monitorPrimitives";

function hasSpeedChange(row: ManeuverStateData): boolean {
  return (
    row.speedDiffSincePrevious !== undefined ||
    row.speedDiffSinceStart !== undefined ||
    row.speedDiffSinceReadilyApparent !== undefined
  );
}

function ManeuverCard({
  row,
  actors,
}: {
  row: ManeuverStateData;
  actors: ActorStaticInfo[];
}) {
  const changed = row.previousManeuverType && row.previousManeuverType !== row.maneuverType;
  const turn = directionWord(row.headingChangeDirection);
  return (
    <div className="mon-card">
      <div className="mon-card-head">
        <span className="mon-card-title">
          <ActorTag actors={actors} id={row.actorId} />
        </span>
        <Chip label={humanizeEnum(row.maneuverType)} tone="info" />
        {changed ? (
          <span className="mon-card-sub meta">was {humanizeEnum(row.previousManeuverType)}</span>
        ) : null}
        {row.maneuverCount > 0 ? <span className="mon-badge">x{row.maneuverCount}</span> : null}
      </div>

      <div className="mon-tile-row">
        <StatTile label="Turn" value={turn} tone={turn === "-" ? "neutral" : "info"} />
        <StatTile label="Δ heading (prev)" value={fmtNum(row.headingDiffSincePreviousDeg)} unit="deg" />
        <StatTile label="Δ heading (start)" value={fmtNum(row.headingDiffSinceStartDeg)} unit="deg" />
        <StatTile
          label="Δ heading (RA)"
          value={fmtNum(row.headingDiffSinceReadilyApparentDeg)}
          unit="deg"
        />
      </div>

      {hasSpeedChange(row) ? (
        <div className="mon-tile-row">
          <StatTile label="Δ speed (prev)" value={fmtNum(row.speedDiffSincePrevious)} unit="m/s" />
          <StatTile label="Δ speed (start)" value={fmtNum(row.speedDiffSinceStart)} unit="m/s" />
          <StatTile
            label="Δ speed (RA)"
            value={fmtNum(row.speedDiffSinceReadilyApparent)}
            unit="m/s"
          />
        </div>
      ) : null}

      <MiniBar
        label="Distance made"
        value={row.distanceMade}
        max={row.totalDistanceMade}
        valueText={`${fmtNum(row.distanceMade)} / ${fmtNum(row.totalDistanceMade)} m`}
      />

      <div className="mon-chip-row">
        <BoolChip label="Just started" value={row.justStarted} tone="neutral" />
        <BoolChip
          label="Readily apparent time passed"
          value={row.readilyApparentTimePassed}
          tone="good"
        />
        <span className="meta">timespan {fmtNum(row.timespan)} s</span>
      </div>

      {row.suggestedManeuvers.length > 0 ? (
        <div className="mon-chip-row mon-chip-row--wrap">
          <span className="mon-micro mon-micro--inline">Suggested</span>
          {row.suggestedManeuvers.map((m) => (
            <Chip key={m} label={humanizeEnum(m)} tone="neutral" />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ManeuversSection({
  maneuvers,
  actors,
}: {
  maneuvers: ManeuverStateData[];
  actors: ActorStaticInfo[];
}) {
  if (maneuvers.length === 0) {
    return null;
  }
  if (!looksLikeManeuverStates(maneuvers)) {
    return <GeneralMonitorList title="Maneuvers" items={maneuvers} />;
  }
  return (
    <MonitorSection title="Maneuvers" badge={maneuvers.length}>
      <div className="frame-list-stack">
        {maneuvers.map((row, i) => (
          <ManeuverCard key={`${row.actorId}-${i}`} row={row} actors={actors} />
        ))}
      </div>
    </MonitorSection>
  );
}
