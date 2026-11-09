import { encounterTagsByVessel } from "../monitor/encounterPairs";
import type { CanvasSettings } from "./canvasSettings";
import { anchorOf, ownShipOf, primaryStream, type DrawnStream } from "./canvasStreams";
import {
  chooseRingSpacing,
  courseDeg,
  formatDegrees,
  formatNm,
  rangeBetween,
  trueBearingDeg,
  worldToScreen,
  type Point,
  type ViewTransform,
} from "./encounterGeometry";
import { useTheme } from "../../../app/theme";
import { CANVAS_COLORS } from "./encounterPalette";
import { ownShipColor } from "./shipColors";
import { actorTracksFor, cpaMarks, splitTrack, type ActorTrack } from "./encounterScene";
import {
  BearingScale,
  CanvasLegend,
  CpaLayer,
  DomainLayer,
  HullLayer,
  NorthArrow,
  RangeRings,
  SafetyRadiusLayer,
  ScaleBar,
  SelectionLine,
  TrackLayer,
  VesselLabels,
  VesselOverlay,
  WorldGroup,
  type TrackDrawing,
  type VesselScreenInfo,
} from "./nauticalLayers";

const HISTORY_DOT_SECONDS = 60;

function historyDots(track: ActorTrack | undefined, t: number, view: ViewTransform, speed: number): Point[] {
  if (!track || speed * HISTORY_DOT_SECONDS * view.scale < 6) {
    return [];
  }
  const out: Point[] = [];
  for (let i = 0; i < track.t.length && track.t[i]! <= t; i += 1) {
    if (track.t[i]! % HISTORY_DOT_SECONDS === 0 && track.t[i]! > 0) {
      out.push(worldToScreen(view, track.points[i]!));
    }
  }
  return out;
}

interface EncounterLayersProps {
  /** The streams to draw, each with its frame. */
  streams: DrawnStream[];
  view: ViewTransform;
  settings: CanvasSettings;
  headUp: boolean;
  selectedRelationId: string | null;
  onVesselClick?: (actorId: string) => void;
  /** The north arrow; the map leaves it out (north is up there). */
  northArrow?: boolean;
  /** Room kept free along the bottom (the map's attribution) under the scale bar and the legend. */
  bottomInset?: number;
}

/**
 * The drawing of an encounter in screen pixels of `view`, for an `<svg>` of the view's size:
 * range rings and the bearing scale around the own ship, each stream's domains, tracks, hulls
 * and vectors, the CPA marks, the selected pair, labels, the scale bar, the north arrow and the
 * legend. The encounter canvas and the nautical map both draw with it.
 */
export function EncounterLayers({
  streams,
  view,
  settings,
  headUp,
  selectedRelationId,
  onVesselClick,
  northArrow = true,
  bottomInset = 0,
}: EncounterLayersProps) {
  const theme = useTheme();
  const primary = primaryStream(streams);
  const frame = primary?.frame ?? null;
  const own = ownShipOf(frame);
  const anchor = anchorOf(frame);

  const marks = settings.cpa ? cpaMarks(frame, { selectedRelationId }) : [];
  const tags = encounterTagsByVessel(frame);
  const minSide = Math.min(view.width, view.height);
  const ringCenter = worldToScreen(view, anchor);
  const ringSpacing = chooseRingSpacing(minSide / 2 / view.scale);
  const vectorSeconds = settings.vectorMinutes * 60;
  const footer = { ...view, height: view.height - bottomInset };

  const streamLayers = streams.map((stream) => {
    const streamFrame = stream.frame;
    const tracks = actorTracksFor(stream.frames);
    const vessels: VesselScreenInfo[] = streamFrame.actors
      .map((actor) => {
        const state = streamFrame.statesByActorId[actor.id];
        return state ? { actor, state, screen: worldToScreen(view, state) } : null;
      })
      .filter((v): v is VesselScreenInfo => v !== null);
    const trackDrawings: TrackDrawing[] = stream.layers.trajectory
      ? streamFrame.actors.map((actor) => {
          const state = streamFrame.statesByActorId[actor.id];
          const { past, ahead } = splitTrack(
            tracks[actor.id],
            streamFrame.timestamp,
            state ? { x: state.x, y: state.y } : null,
            streamFrame.trajectoriesByActorId?.[actor.id]
          );
          return { actorId: actor.id, past, ahead };
        })
      : [];
    const dots: Record<string, Point[]> = {};
    if (stream.layers.trajectory && !stream.secondary) {
      for (const vessel of vessels) {
        dots[vessel.actor.id] = historyDots(tracks[vessel.actor.id], streamFrame.timestamp, view, vessel.state.speed);
      }
    }
    return { stream, streamFrame, vessels, trackDrawings, dots };
  });

  const primaryLayer = streamLayers.find((layer) => layer.stream === primary) ?? null;
  const selectedPair = (() => {
    if (!selectedRelationId || !frame) return null;
    const [aId, bId] = selectedRelationId.split("->");
    const a = aId ? frame.statesByActorId[aId] : undefined;
    const b = bId ? frame.statesByActorId[bId] : undefined;
    if (!a || !b) return null;
    return {
      a: worldToScreen(view, a),
      b: worldToScreen(view, b),
      label: `${formatNm(rangeBetween(a, b))} · ${formatDegrees(trueBearingDeg(a, b))}`,
    };
  })();

  const bearingTargets =
    own && frame
      ? frame.actors
          .filter((actor) => actor.id !== own.actor.id && frame.statesByActorId[actor.id])
          .map((actor) => ({
            key: actor.id,
            bearing: trueBearingDeg(own.state, frame.statesByActorId[actor.id]!),
            color: primary?.colorByActorId[actor.id] ?? CANVAS_COLORS.fallback,
          }))
      : [];

  return (
    <>
      {settings.rings ? <RangeRings center={ringCenter} spacing={ringSpacing} view={view} /> : null}
      {settings.rings && own ? (
        <BearingScale
          center={ringCenter}
          radius={minSide * 0.46}
          view={view}
          ownCourse={courseDeg(own.state.heading)}
          ownColor={primary?.colorByActorId[own.actor.id] ?? ownShipColor(theme)}
          targets={bearingTargets}
        />
      ) : null}
      <WorldGroup view={view}>
        {streamLayers.map(({ stream, streamFrame }) => (
          <DomainLayer
            key={`domains-${stream.key}`}
            frame={streamFrame}
            colorByActorId={stream.colorByActorId}
            showSafety={stream.layers.safetyDomain}
            showStatic={stream.layers.staticAvoidanceDomain}
            showManeuvering={stream.layers.maneuveringDomain}
            dim={Boolean(stream.secondary)}
          />
        ))}
        {streamLayers.map(({ stream, streamFrame }) =>
          stream.layers.safetyRadius ? (
            <SafetyRadiusLayer key={`radius-${stream.key}`} frame={streamFrame} colorByActorId={stream.colorByActorId} />
          ) : null
        )}
        {streamLayers.map(({ stream, trackDrawings }) => (
          <TrackLayer
            key={`tracks-${stream.key}`}
            tracks={trackDrawings}
            colorByActorId={stream.colorByActorId}
            secondary={Boolean(stream.secondary)}
          />
        ))}
        {streamLayers.map(({ stream, streamFrame }) =>
          stream.layers.dot ? (
            <HullLayer
              key={`hulls-${stream.key}`}
              frame={streamFrame}
              colorByActorId={stream.colorByActorId}
              secondary={Boolean(stream.secondary)}
            />
          ) : null
        )}
      </WorldGroup>
      {primary && marks.length > 0 ? (
        <CpaLayer marks={marks} view={view} colorByActorId={primary.colorByActorId} selectedRelationId={selectedRelationId} />
      ) : null}
      {streamLayers.map(({ stream, vessels, dots }) => (
        <VesselOverlay
          key={`overlay-${stream.key}`}
          vessels={vessels}
          view={view}
          colorByActorId={stream.colorByActorId}
          showSymbols={stream.layers.dot}
          showVectors={stream.layers.velocity}
          vectorSeconds={vectorSeconds}
          historyDots={dots}
          secondary={Boolean(stream.secondary)}
          onVesselClick={stream === primary ? onVesselClick : undefined}
        />
      ))}
      {selectedPair ? <SelectionLine a={selectedPair.a} b={selectedPair.b} label={selectedPair.label} /> : null}
      {settings.labels && primaryLayer ? (
        <VesselLabels
          vessels={primaryLayer.vessels}
          colorByActorId={primaryLayer.stream.colorByActorId}
          tagsByVessel={tags}
          bounds={{ x: 4, y: 52, width: view.width - 8, height: footer.height - 56 }}
        />
      ) : null}
      <ScaleBar view={footer} />
      {northArrow ? <NorthArrow view={view} headUp={headUp} /> : null}
      {settings.legend && footer.height >= 300 && view.width >= 420 ? (
        <CanvasLegend
          view={footer}
          vectorMinutes={settings.vectorMinutes}
          streams={streams.map((stream) => ({
            key: stream.key,
            label: stream.label,
            color: own ? (stream.colorByActorId[own.actor.id] ?? CANVAS_COLORS.fallback) : CANVAS_COLORS.fallback,
            secondary: Boolean(stream.secondary),
          }))}
        />
      ) : null}
    </>
  );
}
