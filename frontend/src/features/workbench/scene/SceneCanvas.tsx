import { IconButton } from "../../../components/IconButton";
import { DownloadIcon, MapIcon, PanelRightOpenIcon, RadarIcon } from "../../../components/icons";
import { PopoverMenu } from "../../../components/PopoverMenu";
import { Fragment, useMemo, useRef, useState } from "react";
import {
  captureSvgScreenshot,
  exportFramesAsCsv,
  exportFramesAsGeoJson,
} from "./sceneExport";
import type { SimulationFrame } from "../../../domain/simulation/types";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
} from "../../../domain/playback/playbackStore";
import { useShownPlayback } from "../../../domain/playback/playbackContext";
import { useTheme } from "../../../app/theme";
import { useUiStore } from "../../../app/uiStore";
import { useConnectionStore } from "../connection/connectionStore";
import { useEncounterSelectionStore } from "../monitor/encounterSelectionStore";
import { buildShipColorsByActorId, getShipColor, getSimulationStreamColor } from "./shipColors";
import { samePositions } from "./canvasStreams";
import { EncounterCanvas, type EncounterCanvasStream } from "./EncounterCanvas";
import type { LayerColumn } from "./LayerMenu";
import { NauticalMapView } from "./NauticalMapView";

interface SceneCanvasProps {
  /** When provided, visualizes this generated scene instead of playback preview frames. */
  generatedScene?: SimulationFrame | null;
  /** What the canvas says while it has nothing to draw: what the page needs first. */
  emptyMessage?: string;
}

/**
 * The workbench's scene view: the encounter canvas (or the nautical map) fed from the global
 * playback store, with the preview stream and the simulation stream overlaid, the layer
 * menu with a column per stream, the export menu, the map switch and, while the monitoring
 * panel is hidden, the button that shows it again.
 */
export function SceneCanvas({ generatedScene, emptyMessage: pageEmptyMessage }: SceneCanvasProps = {}) {
  const isGeneratedMode = generatedScene !== undefined;
  const frames = useShownPlayback((s) => s.frames);
  const simulationFrames = useShownPlayback((s) => s.simulationFrames);
  const playbackFrame = useShownPlayback((s) => getCurrentFrame(s));
  const previewFrame = isGeneratedMode ? generatedScene : playbackFrame;
  const simulationFrame = useShownPlayback((s) => getCurrentSimulationFrame(s));
  const hasTrajectoryChunk = useShownPlayback((s) => s.hasTrajectoryChunk);
  const hasSimulationTrajectoryChunk = useShownPlayback((s) => s.hasSimulationTrajectoryChunk);
  const autoFitPending = useShownPlayback((s) => s.autoFitPending);
  const consumeAutoFit = useShownPlayback((s) => s.consumeAutoFit);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const previewOverlays = useUiStore((s) => s.previewOverlays);
  const simulationOverlays = useUiStore((s) => s.simulationOverlays);
  const setPreviewOverlay = useUiStore((s) => s.setPreviewOverlay);
  const setSimulationOverlay = useUiStore((s) => s.setSimulationOverlay);
  const hidePreviewStream = useUiStore((s) => s.hidePreviewStream);
  const hideSimulationStream = useUiStore((s) => s.hideSimulationStream);
  const setHidePreviewStream = useUiStore((s) => s.setHidePreviewStream);
  const setHideSimulationStream = useUiStore((s) => s.setHideSimulationStream);
  const sceneViewMode = useUiStore((s) => s.sceneViewMode);
  const setSceneViewMode = useUiStore((s) => s.setSceneViewMode);
  const rightPaneVisible = useUiStore((s) => s.rightPaneVisible);
  const setRightPaneVisible = useUiStore((s) => s.setRightPaneVisible);
  // The geofence the runs use (kept per browser by the Connections page), also after a reload.
  const referenceGeofence = useConnectionStore((s) => s.geofence);
  const selectedRelationId = useEncounterSelectionStore((s) => s.selectedRelationId);
  const setSelectedRelationId = useEncounterSelectionStore((s) => s.setSelectedRelationId);

  const [fitSignal, setFitSignal] = useState(0);

  // The preview can be hidden only beside a simulation: alone it is the page's only picture, and
  // the flag is shared by the pages (hiding it on the simulation page must not blank the trajectory page).
  const previewHideable = !isGeneratedMode && hasSimulationTrajectoryChunk && simulationFrames.length > 0;
  const showPreview = isGeneratedMode
    ? generatedScene != null
    : (!hidePreviewStream || !previewHideable) && hasTrajectoryChunk && frames.length > 0;
  const showSimulation =
    !isGeneratedMode &&
    !hideSimulationStream &&
    hasSimulationTrajectoryChunk &&
    simulationFrames.length > 0;

  const generatedFrames = useMemo(() => (generatedScene ? [generatedScene] : []), [generatedScene]);
  const previewFrames = isGeneratedMode ? generatedFrames : frames;
  const actors = useMemo(() => previewFrame?.actors ?? [], [previewFrame]);
  const simActors = useMemo(() => simulationFrame?.actors ?? [], [simulationFrame]);

  const theme = useTheme();
  const colorByActorId = useMemo(
    () =>
      isGeneratedMode
        ? buildShipColorsByActorId(actors, theme)
        : (Object.fromEntries(actors.map((actor) => [actor.id, getShipColor(actor, theme)])) as Record<string, string>),
    [actors, isGeneratedMode, theme]
  );
  const simulationStreamColorByActorId = useMemo(
    () =>
      Object.fromEntries(simActors.map((actor) => [actor.id, getSimulationStreamColor(actor, theme)])) as Record<
        string,
        string
      >,
    [simActors, theme]
  );

  const streams = useMemo<EncounterCanvasStream[]>(() => {
    const out: EncounterCanvasStream[] = [];
    if (showPreview) {
      out.push({
        key: "preview",
        label: isGeneratedMode ? "Scene" : "Preview",
        frame: previewFrame ?? null,
        frames: previewFrames,
        colorByActorId,
        layers: previewOverlays,
      });
    }
    if (showSimulation) {
      out.push({
        key: "simulation",
        label: "Simulation",
        frame: simulationFrame,
        frames: simulationFrames,
        colorByActorId: simulationStreamColorByActorId,
        layers: simulationOverlays,
        secondary: showPreview,
      });
    }
    return out;
  }, [
    colorByActorId,
    isGeneratedMode,
    previewFrame,
    previewFrames,
    previewOverlays,
    showPreview,
    showSimulation,
    simulationFrame,
    simulationFrames,
    simulationOverlays,
    simulationStreamColorByActorId,
  ]);

  // A generated scene has one stream that is always shown; playback has the preview and, once a
  // simulation sent frames, the simulation, each of which can be hidden.
  const layerColumns: LayerColumn[] = isGeneratedMode
    ? [{ key: "preview", label: "Scene", layers: previewOverlays, onChange: setPreviewOverlay }]
    : [
        {
          key: "preview",
          label: "Preview",
          layers: previewOverlays,
          onChange: setPreviewOverlay,
          ...(previewHideable ? { shown: !hidePreviewStream, onShownChange: (shown: boolean) => setHidePreviewStream(!shown) } : {}),
        },
        ...(hasSimulationTrajectoryChunk
          ? [
              {
                key: "simulation",
                label: "Simulation",
                layers: simulationOverlays,
                onChange: setSimulationOverlay,
                shown: !hideSimulationStream,
                onShownChange: (shown: boolean) => setHideSimulationStream(!shown),
              },
            ]
          : []),
      ];

  // Fit when a new generated scene is shown or the store asks for it (a new trajectory);
  // derived from the previous values while rendering. The samples of a generation, the scene
  // that ends it and a scene coming back with the monitor's verdicts only follow: they keep a
  // view the user zoomed or panned.
  const wantsAutoFit = !isGeneratedMode && autoFitPending && hasTrajectoryChunk && playbackFrame !== null;
  const generating = useShownPlayback((s) => s.activeSceneGenerationRequestId !== null);
  const [followSignal, setFollowSignal] = useState(0);
  const [seen, setSeen] = useState({ scene: generatedScene, wantsAutoFit, generating });
  if (seen.scene !== generatedScene || seen.wantsAutoFit !== wantsAutoFit || seen.generating !== generating) {
    const newScene = isGeneratedMode && generatedScene != null && seen.scene !== generatedScene;
    const follows = newScene && seen.scene != null && (generating || seen.generating || samePositions(seen.scene, generatedScene));
    if (follows) {
      setFollowSignal((v) => v + 1);
    } else if (newScene || (wantsAutoFit && !seen.wantsAutoFit)) {
      setFitSignal((v) => v + 1);
    }
    setSeen({ scene: generatedScene, wantsAutoFit, generating });
  }

  // Every stream with frames can be exported; the menu names the stream once there are two.
  const exportStreams: { label: string; prefix: string; frames: SimulationFrame[] }[] = isGeneratedMode
    ? [{ label: "", prefix: "generated_scene", frames: generatedFrames }]
    : [
        { label: "Preview", prefix: "preview", frames },
        ...(simulationFrames.length > 0 ? [{ label: "Simulation", prefix: "simulation", frames: simulationFrames }] : []),
      ];
  const namedExports = exportStreams.length > 1;

  const onScreenshot = () => {
    if (svgRef.current) {
      captureSvgScreenshot(svgRef.current, `scene_${isGeneratedMode ? "generated_scene" : showSimulation ? "simulation" : "preview"}`);
    }
  };

  const onMap = sceneViewMode === "nautical";
  const actions = (
    <>
      <PopoverMenu label={<DownloadIcon />} iconLabel="Export" align="end" className="scene-export-menu">
        {!onMap ? (
          <button type="button" onClick={onScreenshot}>
            Screenshot (image)
          </button>
        ) : null}
        {exportStreams.map((stream) => (
          <Fragment key={stream.prefix}>
            <button type="button" disabled={stream.frames.length === 0} onClick={() => exportFramesAsCsv(stream.frames, stream.prefix)}>
              {namedExports ? `${stream.label}: table (CSV)` : "Table (CSV)"}
            </button>
            <button type="button" disabled={stream.frames.length === 0} onClick={() => exportFramesAsGeoJson(stream.frames, stream.prefix)}>
              {namedExports ? `${stream.label}: map data (GeoJSON)` : "Map data (GeoJSON)"}
            </button>
          </Fragment>
        ))}
      </PopoverMenu>
      <IconButton
        label={onMap ? "Show encounter canvas" : "Show nautical map"}
        icon={onMap ? <RadarIcon /> : <MapIcon />}
        onClick={() => setSceneViewMode(onMap ? "cartesian" : "nautical")}
      />
      {!isGeneratedMode && !rightPaneVisible ? (
        <IconButton label="Show monitoring panel" icon={<PanelRightOpenIcon />} onClick={() => setRightPaneVisible(true)} />
      ) : null}
    </>
  );

  const emptyMessage =
    !isGeneratedMode && hidePreviewStream && !showPreview && frames.length > 0
      ? "The preview is hidden: show it in the layer menu."
      : (pageEmptyMessage ?? (isGeneratedMode ? "No scene generated or loaded yet." : "Load a scenario to see the encounter."));

  return (
    <div className="scene-panel">
      {onMap ? (
        <NauticalMapView
          streams={streams}
          layerColumns={layerColumns}
          reference={referenceGeofence}
          fitSignal={fitSignal}
          followSignal={followSignal}
          onFit={isGeneratedMode ? undefined : consumeAutoFit}
          selectedRelationId={isGeneratedMode ? null : selectedRelationId}
          onSelectRelation={isGeneratedMode ? undefined : setSelectedRelationId}
          emptyMessage={emptyMessage}
        >
          {actions}
        </NauticalMapView>
      ) : (
        <EncounterCanvas
          streams={streams}
          layerColumns={layerColumns}
          fitSignal={fitSignal}
          followSignal={followSignal}
          onFit={isGeneratedMode ? undefined : consumeAutoFit}
          selectedRelationId={isGeneratedMode ? null : selectedRelationId}
          onSelectRelation={isGeneratedMode ? undefined : setSelectedRelationId}
          svgRef={(element) => {
            svgRef.current = element;
          }}
          emptyMessage={emptyMessage}
        >
          {actions}
        </EncounterCanvas>
      )}
    </div>
  );
}
