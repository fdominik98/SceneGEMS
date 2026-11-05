import { useEffect, useMemo, useState } from "react";
import { useTheme } from "../../app/theme";
import type { OverlayVisibility } from "../../app/uiStore";
import { usePersistedState } from "../../app/usePersistedState";
import type { SimulationFrame } from "../../domain/simulation/types";
import { buildActorNameMap } from "../workbench/monitor/actorNames";
import { buildPairModels } from "../workbench/monitor/encounterPairs";
import { PairCardList } from "../workbench/monitor/PairCards";
import { RuleTimeline } from "../workbench/monitor/RuleTimeline";
import { buildRuleTimeline } from "../workbench/monitor/ruleTimelineModel";
import { EncounterCanvas, type EncounterCanvasStream } from "../workbench/scene/EncounterCanvas";
import type { LayerColumn } from "../workbench/scene/LayerMenu";
import { buildShipColorsByActorId } from "../workbench/scene/shipColors";
import { PlaybackBar } from "./PlaybackBar";
import { useEncounterPlayback } from "./useEncounterPlayback";
import "./encounterView.css";

export interface EncounterViewProps {
  frames: SimulationFrame[];              // frames in the workbench's frame wire format, as domain/simulation/protocol.ts parses them
  timeStep?: number | null;               // seconds between frames, when known
  live?: boolean;                         // frames keep arriving: follow the latest until the user scrubs
  title?: string;
  initialTimestamp?: number;
  onTimestampChange?: (timestamp: number) => void;
}

const ENCOUNTER_VIEW_DEFAULT_LAYERS: OverlayVisibility = {
  dot: true,
  velocity: true,
  safetyRadius: false,
  trajectory: true,
  safetyDomain: true,
  staticAvoidanceDomain: false,
  maneuveringDomain: true,
};

function sortedByTime(frames: SimulationFrame[]): SimulationFrame[] {
  for (let i = 1; i < frames.length; i += 1) {
    if (frames[i]!.timestamp < frames[i - 1]!.timestamp) {
      return [...frames].sort((a, b) => a.timestamp - b.timestamp);
    }
  }
  return frames;
}

/**
 * A recorded or live run as an encounter: the nautical canvas, a card per vessel pair, the
 * playback bar and the rule timeline. Driven by its props only; it owns its playback (play
 * head, play and pause, speed, following the latest frame while `live`).
 */
export function EncounterView({
  frames,
  timeStep = null,
  live = false,
  title,
  initialTimestamp,
  onTimestampChange,
}: EncounterViewProps) {
  const sorted = useMemo(() => sortedByTime(frames), [frames]);
  const { state, frame, range, actions } = useEncounterPlayback(sorted, { live, initialTimestamp, timeStep });
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(null);
  const [layers, setLayers] = usePersistedState<OverlayVisibility>("encounter-view-layers", ENCOUNTER_VIEW_DEFAULT_LAYERS);

  const actors = frame?.actors;
  const actorKey = actors?.map((actor) => `${actor.id}:${actor.name}`).join("|") ?? "";
  const theme = useTheme();
  // Colors and names change only when the cast changes, not with every frame.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const colorByActorId = useMemo(() => buildShipColorsByActorId(actors ?? [], theme), [actorKey, theme]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const names = useMemo(() => buildActorNameMap(actors), [actorKey]);

  const timeline = useMemo(() => buildRuleTimeline(sorted, timeStep), [sorted, timeStep]);
  const pairs = useMemo(() => buildPairModels(frame, timeline), [frame, timeline]);

  const frameTimestamp = frame?.timestamp;
  useEffect(() => {
    if (frameTimestamp !== undefined) {
      onTimestampChange?.(frameTimestamp);
    }
    // Only a change of the shown frame is reported, not a new callback identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameTimestamp]);

  const layerColumns: LayerColumn[] = [
    {
      key: "run",
      label: title ?? "Run",
      layers: { ...ENCOUNTER_VIEW_DEFAULT_LAYERS, ...layers },
      onChange: (key, value) => setLayers((prev) => ({ ...ENCOUNTER_VIEW_DEFAULT_LAYERS, ...prev, [key]: value })),
    },
  ];

  const streams = useMemo<EncounterCanvasStream[]>(
    () => [
      {
        key: "run",
        label: title ?? "Run",
        frame,
        frames: sorted,
        colorByActorId,
        layers: { ...ENCOUNTER_VIEW_DEFAULT_LAYERS, ...layers },
      },
    ],
    [colorByActorId, frame, layers, sorted, title]
  );

  const empty = sorted.length === 0;
  return (
    <section className="enc-view" aria-label={title ?? "Encounter view"}>
      {title ? (
        <header className="enc-view-head">
          <h3>{title}</h3>
          <span className="enc-view-meta">
            {live ? <span className="enc-view-live">live</span> : null}
            {sorted.length} frame{sorted.length === 1 ? "" : "s"}
          </span>
        </header>
      ) : null}
      <div className="enc-view-body">
        <div className="enc-view-canvas">
          <EncounterCanvas
            streams={streams}
            layerColumns={layerColumns}
            selectedRelationId={selectedRelationId}
            onSelectRelation={setSelectedRelationId}
            emptyMessage={live ? "Waiting for the first frame." : "No frames to show."}
          />
        </div>
        <aside className="enc-view-cards" aria-label="Vessel pairs">
          <PairCardList
            pairs={pairs}
            colorByActorId={colorByActorId}
            selectedRelationId={selectedRelationId}
            onSelectRelation={setSelectedRelationId}
            emptyMessage={empty ? "No frames yet." : "No vessel pairs in this frame."}
          />
        </aside>
      </div>
      <PlaybackBar
        start={range.start}
        end={range.end}
        current={state.cursor}
        playing={state.playing}
        speed={state.speed}
        live={live}
        following={state.following}
        disabled={empty}
        onTogglePlay={actions.togglePlay}
        onSeek={actions.seek}
        onStep={actions.step}
        onSpeed={actions.setSpeed}
        onFollowLive={actions.followLive}
      />
      <div className="enc-view-timeline">
        <RuleTimeline
          groups={[{ key: "run", label: title ?? "Run", model: timeline, names }]}
          currentTime={state.cursor}
          onSeek={actions.seek}
          selectedRelationId={selectedRelationId}
          onSelectRelation={setSelectedRelationId}
        />
      </div>
    </section>
  );
}
