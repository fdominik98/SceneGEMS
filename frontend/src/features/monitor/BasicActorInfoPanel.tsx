import { Fragment } from "react";
import type { TrajectoryStream } from "../../app/uiStore";
import type { SimulationFrame } from "../../domain/simulation/types";
import { getActorPanelDotColor } from "../scene/shipColors";
import { renderActorName, renderRelationId } from "./actorNameFormat";
import {
  ACTOR_FIELD_PRIORITY,
  asRecord,
  DynamicFieldGrid,
  DynamicValue,
  FRAME_STRUCTURE_KEYS,
  humanizeKey,
  KINEMATIC_FIELD_PRIORITY,
} from "./frameDataDisplay";
import { useMonitorFrameForKind } from "./useMonitorFrame";

interface BasicActorInfoPanelProps {
  stream: TrajectoryStream;
}

function trajectorySummary(frame: SimulationFrame): string | null {
  const t = frame.trajectoriesByActorId;
  if (!t || Object.keys(t).length === 0) {
    return null;
  }
  const n = Object.keys(t).length;
  const pts = Object.values(t).reduce((acc, path) => acc + path.length, 0);
  return `${n} actor${n === 1 ? "" : "s"} · ${pts} points`;
}

export function BasicActorInfoPanel({ stream }: BasicActorInfoPanelProps) {
  const { frame, panelKind } = useMonitorFrameForKind(stream);

  if (!frame) {
    return (
      <details className="panel panel-collapsible frame-data-root" open>
        <summary>
          <h3>Frame data</h3>
        </summary>
        <p className="meta">No frame data available.</p>
      </details>
    );
  }

  const rawFrame = frame as unknown as Record<string, unknown>;
  const extraFrameKeys = Object.keys(rawFrame).filter((k) => !FRAME_STRUCTURE_KEYS.has(k));

  return (
    <details className="panel panel-collapsible frame-data-root" open>
      <summary>
        <h3>Frame data</h3>
      </summary>
      <p className="meta frame-data-lead">
        Snapshot at <strong>{frame.timestamp}s</strong> · Δt <strong>{frame.timeStep}s</strong>
      </p>

      <div className="frame-data-stack">
        <details className="frame-subpanel" open>
          <summary className="frame-subpanel-summary">
            <span>Vessels &amp; actors</span>
            <span className="frame-subpanel-badge">{frame.actors.length}</span>
          </summary>
          <div className="frame-actor-stack">
            {frame.actors.map((actor, index) => {
              const actorRec = asRecord(actor) ?? {};
              const state = asRecord(frame.statesByActorId[actor.id]);
              const defaultOpen = frame.actors.length <= 2 || index < 2;
              return (
                <details key={actor.id} className="frame-actor-block" open={defaultOpen}>
                  <summary className="frame-actor-summary">
                    <span
                      className="actor-color-dot frame-actor-dot"
                      style={{ backgroundColor: getActorPanelDotColor(actor, panelKind) }}
                    />
                    <span className="frame-actor-name">{renderActorName(actor.name)}</span>
                    <span className="frame-actor-meta meta">
                      {actor.isOwnShip ? "Own ship" : "Other"} · {actor.type}
                    </span>
                  </summary>
                  <div className="frame-actor-body">
                    <p className="frame-micro-heading">Static &amp; limits</p>
                    <DynamicFieldGrid data={actorRec} priorityKeys={ACTOR_FIELD_PRIORITY} />
                    {state ? (
                      <>
                        <p className="frame-micro-heading">Kinematics</p>
                        <DynamicFieldGrid
                          data={state}
                          priorityKeys={KINEMATIC_FIELD_PRIORITY}
                        />
                      </>
                    ) : (
                      <p className="meta">No kinematic state for this actor.</p>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
        </details>

        {frame.situationContexts.length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Situation contexts</span>
              <span className="frame-subpanel-badge">{frame.situationContexts.length}</span>
            </summary>
            <div className="frame-list-stack">
              {frame.situationContexts.map((ctx, i) => {
                const rec = asRecord(ctx) ?? {};
                return (
                  <details key={`${ctx.relationId}-${i}`} className="frame-item-card">
                    <summary className="frame-item-summary">
                      Relation {renderRelationId(ctx.relationId)}
                      <span className="meta"> · {ctx.situationLabel}</span>
                    </summary>
                    <DynamicFieldGrid data={rec} />
                  </details>
                );
              })}
            </div>
          </details>
        ) : null}

        {frame.colregsStates.length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>COLREGS monitor</span>
              <span className="frame-subpanel-badge">{frame.colregsStates.length}</span>
            </summary>
            <div className="frame-list-stack">
              {frame.colregsStates.map((row, i) => {
                const rec = asRecord(row) ?? {};
                return (
                  <details key={`${row.relationId}-col-${i}`} className="frame-item-card">
                    <summary className="frame-item-summary">{renderRelationId(row.relationId)}</summary>
                    <DynamicFieldGrid data={rec} />
                  </details>
                );
              })}
            </div>
          </details>
        ) : null}

        {frame.ruleResults.length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Rule results</span>
              <span className="frame-subpanel-badge">{frame.ruleResults.length}</span>
            </summary>
            <div className="frame-list-stack">
              {frame.ruleResults.map((row, i) => {
                const rec = asRecord(row) ?? {};
                return (
                  <details key={`${row.relationId}-rules-${i}`} className="frame-item-card">
                    <summary className="frame-item-summary">
                      {renderRelationId(row.relationId)}{" "}
                      <span
                        className={
                          row.overallStatus === "FAILED" ? "status-bad" : "status-ok"
                        }
                      >
                        {row.overallStatus}
                      </span>
                    </summary>
                    <DynamicFieldGrid data={rec} />
                  </details>
                );
              })}
            </div>
          </details>
        ) : null}

        {frame.maneuverStates.length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Maneuvers</span>
              <span className="frame-subpanel-badge">{frame.maneuverStates.length}</span>
            </summary>
            <div className="frame-list-stack">
              {frame.maneuverStates.map((row, i) => {
                const rec = asRecord(row) ?? {};
                return (
                  <details key={`${row.actorId}-man-${i}`} className="frame-item-card">
                    <summary className="frame-item-summary">
                      {row.actorId} · {row.maneuverType}
                    </summary>
                    <DynamicFieldGrid data={rec} />
                  </details>
                );
              })}
            </div>
          </details>
        ) : null}

        {frame.metrics && Object.keys(frame.metrics).length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Metrics</span>
              <span className="frame-subpanel-badge">{Object.keys(frame.metrics).length}</span>
            </summary>
            <DynamicFieldGrid data={asRecord(frame.metrics) ?? {}} />
          </details>
        ) : null}

        {frame.trajectoriesByActorId && Object.keys(frame.trajectoriesByActorId).length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Trajectory samples</span>
              <span className="frame-subpanel-badge">
              {trajectorySummary(frame) ?? "paths"}
            </span>
            </summary>
            <ul className="frame-traj-list">
              {Object.entries(frame.trajectoriesByActorId).map(([actorId, path]) => (
                <li key={actorId}>
                  <span className="frame-kv-label">{actorId}</span>{" "}
                  <span className="meta">{path.length} samples</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {extraFrameKeys.length > 0 ? (
          <details className="frame-subpanel">
            <summary className="frame-subpanel-summary">
              <span>Additional frame fields</span>
              <span className="frame-subpanel-badge">{extraFrameKeys.length}</span>
            </summary>
            <dl className="frame-kv-grid">
              {extraFrameKeys.map((key) => (
                <Fragment key={key}>
                  <dt className="frame-kv-label">{humanizeKey(key)}</dt>
                  <dd className="frame-kv-value">
                    <DynamicValue value={rawFrame[key]} depth={0} />
                  </dd>
                </Fragment>
              ))}
            </dl>
          </details>
        ) : null}
      </div>
    </details>
  );
}
