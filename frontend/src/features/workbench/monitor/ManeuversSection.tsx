import type { ActorStaticInfo, ManeuverStateData } from "../../../domain/simulation/types";
import { GeneralMonitorList } from "./GeneralMonitorList";
import { directionWord, fmtNum, humanizeEnum } from "./monitorFormat";
import { looksLikeManeuverStates } from "./monitorFieldShapes";
import { MANEUVER_HINTS } from "./monitorHints";
import { ActorTag, BoolChip, Chip, Hinted, MiniBar, MonitorSection, StatTile } from "./monitorPrimitives";

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
        {row.maneuverCount > 0 ? (
          <span className="mon-badge" title={MANEUVER_HINTS.maneuverCount}>
            x{row.maneuverCount}
          </span>
        ) : null}
      </div>

      <div className="mon-tile-row">
        <StatTile
          label="Turn"
          value={turn}
          tone={turn === "-" ? "neutral" : "info"}
          hint={MANEUVER_HINTS.turn}
        />
        <StatTile
          label="Δ heading (prev)"
          value={fmtNum(row.headingDiffSincePreviousDeg)}
          unit="deg"
          hint={MANEUVER_HINTS.headingPrev}
        />
        <StatTile
          label="Δ heading (start)"
          value={fmtNum(row.headingDiffSinceStartDeg)}
          unit="deg"
          hint={MANEUVER_HINTS.headingStart}
        />
        <StatTile
          label="Δ heading (RA)"
          value={fmtNum(row.headingDiffSinceReadilyApparentDeg)}
          unit="deg"
          hint={MANEUVER_HINTS.headingReadilyApparent}
        />
      </div>

      {hasSpeedChange(row) ? (
        <div className="mon-tile-row">
          <StatTile
            label="Δ speed (prev)"
            value={fmtNum(row.speedDiffSincePrevious)}
            unit="m/s"
            hint={MANEUVER_HINTS.speedPrev}
          />
          <StatTile
            label="Δ speed (start)"
            value={fmtNum(row.speedDiffSinceStart)}
            unit="m/s"
            hint={MANEUVER_HINTS.speedStart}
          />
          <StatTile
            label="Δ speed (RA)"
            value={fmtNum(row.speedDiffSinceReadilyApparent)}
            unit="m/s"
            hint={MANEUVER_HINTS.speedReadilyApparent}
          />
        </div>
      ) : null}

      <MiniBar
        label="Distance made"
        value={row.distanceMade}
        max={row.totalDistanceMade}
        valueText={`${fmtNum(row.distanceMade)} / ${fmtNum(row.totalDistanceMade)} m`}
        hint={MANEUVER_HINTS.distanceMade}
      />

      <div className="mon-chip-row">
        <BoolChip
          label="Just started"
          value={row.justStarted}
          tone="neutral"
          hint={MANEUVER_HINTS.justStarted}
        />
        <BoolChip
          label="Readily apparent time passed"
          value={row.readilyApparentTimePassed}
          tone="good"
          hint={MANEUVER_HINTS.readilyApparentTimePassed}
        />
        <span className="meta">
          <Hinted hint={MANEUVER_HINTS.timespan}>timespan</Hinted> {fmtNum(row.timespan)} s
        </span>
      </div>

      {row.suggestedManeuvers.length > 0 ? (
        <div className="mon-chip-row mon-chip-row--wrap">
          <span className="mon-micro mon-micro--inline">
            <Hinted hint={MANEUVER_HINTS.suggested}>Suggested</Hinted>
          </span>
          {row.suggestedManeuvers.map((m) => (
            <Chip key={m} label={humanizeEnum(m)} tone="neutral" />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ManeuversSection({
  persistKey,
  maneuvers,
  actors,
}: {
  persistKey: string;
  maneuvers: ManeuverStateData[];
  actors: ActorStaticInfo[];
}) {
  if (maneuvers.length === 0) {
    return null;
  }
  if (!looksLikeManeuverStates(maneuvers)) {
    return <GeneralMonitorList persistKey={persistKey} title="Maneuvers" items={maneuvers} />;
  }
  return (
    <MonitorSection persistKey={persistKey} title="Maneuvers" badge={maneuvers.length}>
      <div className="frame-list-stack">
        {maneuvers.map((row, i) => (
          <ManeuverCard key={`${row.actorId}-${i}`} row={row} actors={actors} />
        ))}
      </div>
    </MonitorSection>
  );
}
