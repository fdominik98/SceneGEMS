import { IconButton } from "../../../components/IconButton";
import { DownloadIcon, MapIcon, PanelRightOpenIcon, RadarIcon } from "../../../components/icons";
import { PopoverMenu } from "../../../components/PopoverMenu";
import { useMemo, useRef, useState } from "react";
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
import { useUiStore } from "../../../app/uiStore";
import { useEncounterSelectionStore } from "../monitor/encounterSelectionStore";
import { buildShipColorsByActorId, getShipColor, getSimulationStreamColor } from "./shipColors";
import { EncounterCanvas, type EncounterCanvasStream } from "./EncounterCanvas";
import type { LayerColumn } from "./LayerMenu";
import { NauticalMapView } from "./NauticalMapView";

interface SceneCanvasProps {
  /** When provided, visualizes this generated scene instead of playback preview frames. */
  generatedScene?: SimulationFrame | null;
}

/**
 * The workbench's scene view: the encounter canvas (or the nautical map) fed from the global
 * playback store, with the preview stream and the simulation stream overlaid, the layer
 * menu with a column per stream, the export menu, the map switch and, while the monitoring
 * panel is hidden, the button that shows it again.
 */
export function SceneCanvas({ generatedScene }: SceneCanvasProps = {}) {
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

  const controlPanelMode = useUiStore((s) => s.controlPanelMode);
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
  const referenceGeofence = useUiStore((s) => s.referenceGeofence);
  const selectedRelationId = useEncounterSelectionStore((s) => s.selectedRelationId);
  const setSelectedRelationId = useEncounterSelectionStore((s) => s.setSelectedRelationId);

  const [fitSignal, setFitSignal] = useState(0);

  const showPreview = isGeneratedMode
    ? generatedScene != null
    : !hidePreviewStream && hasTrajectoryChunk && frames.length > 0;
  const showSimulation =
    !isGeneratedMode &&
    !hideSimulationStream &&
    hasSimulationTrajectoryChunk &&
    simulationFrames.length > 0;

  const generatedFrames = useMemo(() => (generatedScene ? [generatedScene] : []), [generatedScene]);
  const previewFrames = isGeneratedMode ? generatedFrames : frames;
  const actors = useMemo(() => previewFrame?.actors ?? [], [previewFrame]);
  const simActors = useMemo(() => simulationFrame?.actors ?? [], [simulationFrame]);

  const colorByActorId = useMemo(
    () =>
      isGeneratedMode
        ? buildShipColorsByActorId(actors)
        : (Object.fromEntries(actors.map((actor) => [actor.id, getShipColor(actor)])) as Record<string, string>),
    [actors, isGeneratedMode]
  );
  const simulationStreamColorByActorId = useMemo(
    () =>
      Object.fromEntries(simActors.map((actor) => [actor.id, getSimulationStreamColor(actor)])) as Record<
        string,
        string
      >,
    [simActors]
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
          shown: !hidePreviewStream,
          onShownChange: (shown) => setHidePreviewStream(!shown),
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
  // derived from the previous values while rendering.
  const wantsAutoFit = !isGeneratedMode && autoFitPending && hasTrajectoryChunk && playbackFrame !== null;
  const [seen, setSeen] = useState({ scene: generatedScene, wantsAutoFit });
  if (seen.scene !== generatedScene || seen.wantsAutoFit !== wantsAutoFit) {
    const newScene = isGeneratedMode && generatedScene != null && seen.scene !== generatedScene;
    if (newScene || (wantsAutoFit && !seen.wantsAutoFit)) {
      setFitSignal((v) => v + 1);
    }
    setSeen({ scene: generatedScene, wantsAutoFit });
  }

  const exportActiveFrames = isGeneratedMode
    ? generatedFrames
    : controlPanelMode === "simulation"
      ? simulationFrames
      : frames;
  const exportPrefix = isGeneratedMode
    ? "generated_scene"
    : controlPanelMode === "simulation"
      ? "simulation"
      : "preview";

  const onScreenshot = () => {
    if (svgRef.current) {
      captureSvgScreenshot(svgRef.current, `scene_${exportPrefix}`);
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
        <button
          type="button"
          disabled={exportActiveFrames.length === 0}
          onClick={() => exportFramesAsCsv(exportActiveFrames, exportPrefix)}
        >
          Table (CSV)
        </button>
        <button
          type="button"
          disabled={exportActiveFrames.length === 0}
          onClick={() => exportFramesAsGeoJson(exportActiveFrames, exportPrefix)}
        >
          Map data (GeoJSON)
        </button>
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

  const emptyMessage = isGeneratedMode ? "No scene generated or loaded yet." : "Load a scenario to see the encounter.";

  return (
    <div className="scene-panel">
      {onMap ? (
        <NauticalMapView
          streams={streams}
          layerColumns={layerColumns}
          reference={referenceGeofence}
          fitSignal={fitSignal}
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
