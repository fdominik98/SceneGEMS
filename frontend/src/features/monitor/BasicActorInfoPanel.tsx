import { Fragment } from "react";
import type { TrajectoryStream } from "../../app/uiStore";
import type { SimulationFrame } from "../../domain/simulation/types";
import { getActorPanelDotColor } from "../scene/shipColors";
import { ActorNamesProvider, renderActorName } from "./actorNameFormat";
import { ColregsMonitorStateSection } from "./ColregsMonitorStateSection";
import { EncounterSummaryCard } from "./EncounterSummaryCard";
import {
  ACTOR_FIELD_PRIORITY,
  asRecord,
  DynamicFieldGrid,
  DynamicValue,
  FRAME_STRUCTURE_KEYS,
  humanizeKey,
  KINEMATIC_FIELD_PRIORITY,
} from "./frameDataDisplay";
import { ManeuversSection } from "./ManeuversSection";
import { MonitorMetricsSection } from "./MonitorMetricsSection";
import { RuleResultsPanel } from "./RuleResultsPanel";
import { SituationContextsSection } from "./SituationContextsSection";
import { monitorSectionKey, PersistedDetails } from "./monitorPrimitives";
import { useMonitorFrameForKind } from "./useMonitorFrame";

interface BasicActorInfoPanelProps {
  stream: TrajectoryStream;
  /** Shown instead of the stream's current playback frame (scene generation monitor preview). */
  frame?: SimulationFrame | null;
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

export function BasicActorInfoPanel({ stream, frame: frameOverride }: BasicActorInfoPanelProps) {
  const { frame: streamFrame, panelKind } = useMonitorFrameForKind(stream);
  const frame = frameOverride !== undefined ? frameOverride : streamFrame;
  const frameDataKey = monitorSectionKey(stream, "frame-data");

  if (!frame) {
    return (
      <PersistedDetails persistKey={frameDataKey} className="panel panel-collapsible frame-data-root">
        <summary>
          <h3>Frame data</h3>
        </summary>
        <p className="meta">No frame data available.</p>
      </PersistedDetails>
    );
  }

  const rawFrame = frame as unknown as Record<string, unknown>;
  const extraFrameKeys = Object.keys(rawFrame).filter((k) => !FRAME_STRUCTURE_KEYS.has(k));

  return (
    <ActorNamesProvider actors={frame.actors}>
    <PersistedDetails persistKey={frameDataKey} className="panel panel-collapsible frame-data-root">
      <summary>
        <h3>Frame data</h3>
      </summary>
      <p className="meta frame-data-lead">
        Snapshot at <strong>{frame.timestamp}s</strong> · Δt <strong>{frame.timeStep}s</strong>
      </p>

      <div className="frame-data-stack">
        <PersistedDetails persistKey={monitorSectionKey(stream, "vessels")} className="frame-subpanel">
          <summary className="frame-subpanel-summary">
            <span>Vessels &amp; actors</span>
            <span className="frame-subpanel-badge">{frame.actors.length}</span>
          </summary>
          <div className="frame-actor-stack">
            {frame.actors.map((actor) => {
              const actorRec = asRecord(actor) ?? {};
              const state = asRecord(frame.statesByActorId[actor.id]);
              return (
                <PersistedDetails
                  key={actor.id}
                  persistKey={monitorSectionKey(stream, `actor:${actor.id}`)}
                  className="frame-actor-block"
                >
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
                </PersistedDetails>
              );
            })}
          </div>
        </PersistedDetails>

        <EncounterSummaryCard
          persistKey={monitorSectionKey(stream, "encounter-summary")}
          situationContexts={frame.situationContexts}
          colregsStates={frame.colregsStates}
          ruleResults={frame.ruleResults}
          maneuverStates={frame.maneuverStates}
          actors={frame.actors}
        />

        <SituationContextsSection
          persistKey={monitorSectionKey(stream, "situation-contexts")}
          contexts={frame.situationContexts}
          actors={frame.actors}
        />

        <ColregsMonitorStateSection
          persistKey={monitorSectionKey(stream, "colregs-monitor-state")}
          states={frame.colregsStates}
          actors={frame.actors}
        />

        <RuleResultsPanel
          persistKey={monitorSectionKey(stream, "colregs-rules")}
          ruleResults={frame.ruleResults}
          situationContexts={frame.situationContexts}
        />

        <ManeuversSection
          persistKey={monitorSectionKey(stream, "maneuvers")}
          maneuvers={frame.maneuverStates}
          actors={frame.actors}
        />

        <MonitorMetricsSection persistKey={monitorSectionKey(stream, "metrics")} metrics={frame.metrics} />

        {frame.trajectoriesByActorId && Object.keys(frame.trajectoriesByActorId).length > 0 ? (
          <PersistedDetails persistKey={monitorSectionKey(stream, "trajectory-samples")} className="frame-subpanel">
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
          </PersistedDetails>
        ) : null}

        {extraFrameKeys.length > 0 ? (
          <PersistedDetails persistKey={monitorSectionKey(stream, "additional-fields")} className="frame-subpanel">
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
          </PersistedDetails>
        ) : null}
      </div>
    </PersistedDetails>
    </ActorNamesProvider>
  );
}
