import { renderRelationId } from "./actorNameFormat";
import { GeneralMonitorObject } from "./GeneralMonitorList";
import { fmtNum, type Tone } from "./monitorFormat";
import { looksLikeMetrics } from "./monitorFieldShapes";
import { MonitorSection, StatTile } from "./monitorPrimitives";

type NumMap = Record<string, number>;

interface RelationThresholds {
  safetyDistance?: number;
  visibilityDistance?: number;
}

function numMap(v: unknown): NumMap {
  if (typeof v !== "object" || v === null) {
    return {};
  }
  const out: NumMap = {};
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (typeof val === "number" && Number.isFinite(val)) {
      out[k] = val;
    }
  }
  return out;
}

/** danger below `safety`, warn below `visibility`, good above; neutral if no thresholds. */
function distanceTone(value: number | undefined, t: RelationThresholds): Tone {
  if (typeof value !== "number") {
    return "neutral";
  }
  if (t.safetyDistance === undefined && t.visibilityDistance === undefined) {
    return "neutral";
  }
  if (t.safetyDistance !== undefined && value < t.safetyDistance) {
    return "danger";
  }
  if (t.visibilityDistance !== undefined && value < t.visibilityDistance) {
    return "warn";
  }
  return "good";
}

function dsIndexTone(value: number | undefined): Tone {
  if (typeof value !== "number") {
    return "neutral";
  }
  if (value >= 0.66) {
    return "danger";
  }
  if (value >= 0.33) {
    return "warn";
  }
  return "good";
}

export function MonitorMetricsSection({ metrics }: { metrics: unknown }) {
  if (metrics === undefined || metrics === null) {
    return null;
  }
  if (!looksLikeMetrics(metrics)) {
    return <GeneralMonitorObject title="Metrics" data={metrics} />;
  }

  const m = metrics as Record<string, unknown>;
  const scene = (typeof m.scene === "object" && m.scene !== null ? m.scene : {}) as Record<
    string,
    unknown
  >;
  const relations = (
    typeof m.relations === "object" && m.relations !== null ? m.relations : {}
  ) as Record<string, Record<string, unknown>>;

  const distanceById = numMap(m.distanceByRelationId);
  const dcpaById = numMap(m.dcpaByRelationId);
  const tcpaById = numMap(m.tcpaByRelationId);
  const dsById = numMap(m.dsIndexByRelationId);

  const relationIds = [
    ...new Set([
      ...Object.keys(relations),
      ...Object.keys(distanceById),
      ...Object.keys(dcpaById),
      ...Object.keys(tcpaById),
      ...Object.keys(dsById),
    ]),
  ].sort((a, b) => a.localeCompare(b));

  const sceneDcpa = typeof scene.dcpa === "number" ? scene.dcpa : undefined;
  const sceneTcpa = typeof scene.tcpa === "number" ? scene.tcpa : undefined;
  const sceneDanger = typeof scene.dangerSector === "number" ? scene.dangerSector : undefined;
  const sceneProx = typeof scene.proximityIndex === "number" ? scene.proximityIndex : undefined;
  const hasScene =
    sceneDcpa !== undefined ||
    sceneTcpa !== undefined ||
    sceneDanger !== undefined ||
    sceneProx !== undefined;

  return (
    <MonitorSection title="Metrics" badge={relationIds.length || undefined}>
      {hasScene ? (
        <>
          <p className="mon-micro">Scene</p>
          <div className="mon-tile-row">
            <StatTile label="DCPA" value={fmtNum(sceneDcpa)} unit="m" />
            <StatTile label="TCPA" value={fmtNum(sceneTcpa)} unit="s" />
            <StatTile
              label="Danger sector"
              value={fmtNum(sceneDanger, 3)}
              tone={dsIndexTone(sceneDanger)}
            />
            <StatTile
              label="Proximity idx"
              value={fmtNum(sceneProx, 3)}
              tone={dsIndexTone(sceneProx)}
            />
          </div>
        </>
      ) : null}

      {relationIds.length > 0 ? (
        <>
          <p className="mon-micro">Per relation</p>
          <div className="frame-list-stack">
            {relationIds.map((relId) => {
              const rel = relations[relId] ?? {};
              const t: RelationThresholds = {
                safetyDistance:
                  typeof rel.safetyDistance === "number" ? rel.safetyDistance : undefined,
                visibilityDistance:
                  typeof rel.visibilityDistance === "number" ? rel.visibilityDistance : undefined,
              };
              const distance =
                distanceById[relId] ??
                (typeof rel.distance === "number" ? rel.distance : undefined);
              const dcpa =
                dcpaById[relId] ?? (typeof rel.dcpa === "number" ? rel.dcpa : undefined);
              const tcpa =
                tcpaById[relId] ?? (typeof rel.tcpa === "number" ? rel.tcpa : undefined);
              const ds = dsById[relId];
              return (
                <div className="mon-card" key={relId}>
                  <div className="mon-card-head">
                    <span className="mon-card-title">{renderRelationId(relId)}</span>
                  </div>
                  <div className="mon-tile-row">
                    <StatTile
                      label="Distance"
                      value={fmtNum(distance)}
                      unit="m"
                      tone={distanceTone(distance, t)}
                    />
                    <StatTile
                      label="DCPA"
                      value={fmtNum(dcpa)}
                      unit="m"
                      tone={distanceTone(dcpa, t)}
                    />
                    <StatTile label="TCPA" value={fmtNum(tcpa)} unit="s" />
                    <StatTile label="DS index" value={fmtNum(ds, 3)} tone={dsIndexTone(ds)} />
                  </div>
                  {t.safetyDistance !== undefined || t.visibilityDistance !== undefined ? (
                    <p className="meta mon-thresh">
                      thresholds: safety {fmtNum(t.safetyDistance)} m
                      {t.visibilityDistance !== undefined
                        ? ` · visibility ${fmtNum(t.visibilityDistance)} m`
                        : ""}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      ) : null}
    </MonitorSection>
  );
}
