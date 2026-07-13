import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  captureCanvasScreenshot,
  exportFramesAsCsv,
  exportFramesAsGeoJson,
} from "./sceneExport";
import { MOUSE } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { SimulationFrame } from "../../domain/simulation/types";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
  usePlaybackStore,
} from "../../domain/playback/playbackStore";
import { useUiStore } from "../../app/uiStore";
import { DomainsLayer } from "./layers/DomainsLayer";
import { TrajectoriesLayer } from "./layers/TrajectoriesLayer";
import { VelocityVectorsLayer } from "./layers/VelocityVectorsLayer";
import { VesselMarkerLayer } from "./layers/VesselMarkerLayer";
import { buildShipColorsByActorId, getShipColor, getSimulationStreamColor } from "./shipColors";
import { buildTrajectoryPathsByActor } from "./buildTrajectoryPaths";
import { NauticalMapView } from "./NauticalMapView";
import { RecenterControl } from "./RecenterControl";

const SEA_PLANE_SIZE = 2_000_000;
const BASE_HALF_WIDTH_FOR_ZOOM = 500;
const FIT_MARGIN_RATIO = 0.08;
const MIN_FIT_MARGIN_METERS = 20;

interface ViewInfo {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
  zoomScale: number;
}

interface SceneCanvasProps {
  /** When provided, visualizes this generated scene instead of playback preview frames. */
  generatedScene?: SimulationFrame | null;
}

export function SceneCanvas({ generatedScene }: SceneCanvasProps = {}) {
  const isGeneratedMode = generatedScene !== undefined;
  const frames = usePlaybackStore((s) => s.frames);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const playbackFrame = usePlaybackStore((s) => getCurrentFrame(s));
  const previewFrame = isGeneratedMode ? generatedScene : playbackFrame;
  const simulationFrame = usePlaybackStore((s) => getCurrentSimulationFrame(s));
  const hasTrajectoryChunk = usePlaybackStore((s) => s.hasTrajectoryChunk);
  const hasSimulationTrajectoryChunk = usePlaybackStore((s) => s.hasSimulationTrajectoryChunk);
  const autoFitPending = usePlaybackStore((s) => s.autoFitPending);
  const consumeAutoFit = usePlaybackStore((s) => s.consumeAutoFit);
  const scenePanelRef = useRef<HTMLDivElement | null>(null);

  const controlPanelMode = useUiStore((s) => s.controlPanelMode);
  const previewOverlays = useUiStore((s) => s.previewOverlays);
  const simulationOverlays = useUiStore((s) => s.simulationOverlays);
  const hidePreviewStream = useUiStore((s) => s.hidePreviewStream);
  const hideSimulationStream = useUiStore((s) => s.hideSimulationStream);
  const sceneViewMode = useUiStore((s) => s.sceneViewMode);
  const setSceneViewMode = useUiStore((s) => s.setSceneViewMode);
  const referenceGeofence = useUiStore((s) => s.referenceGeofence);

  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const prevSceneViewModeRef = useRef(sceneViewMode);
  const pendingCartesianFitRef = useRef(false);
  const [controlsMountVersion, setControlsMountVersion] = useState(0);
  const [nauticalRecenterSignal, setNauticalRecenterSignal] = useState(0);
  const [viewInfo, setViewInfo] = useState<ViewInfo>({
    xMin: -500,
    xMax: 500,
    yMin: -300,
    yMax: 300,
    zoomScale: 1,
  });

  const showPreview = isGeneratedMode
    ? generatedScene != null
    : !hidePreviewStream && hasTrajectoryChunk && frames.length > 0;
  const showSimulation =
    !isGeneratedMode &&
    !hideSimulationStream &&
    hasSimulationTrajectoryChunk &&
    simulationFrames.length > 0;

  /** Same world origin for both streams so geometry lines up (color/style distinguish streams). */
  const previewOrigin = useMemo(() => ({ x: 0, y: 0 }), []);
  const simulationOrigin = useMemo(() => ({ x: 0, y: 0 }), []);

  const trajectoriesByActorId = useMemo(
    () =>
      isGeneratedMode
        ? buildTrajectoryPathsByActor(generatedScene ? [generatedScene] : [], generatedScene)
        : buildTrajectoryPathsByActor(frames, playbackFrame),
    [frames, generatedScene, isGeneratedMode, playbackFrame]
  );
  const simulationTrajectoriesByActorId = useMemo(
    () => buildTrajectoryPathsByActor(simulationFrames, simulationFrame),
    [simulationFrames, simulationFrame]
  );

  const actors = useMemo(() => previewFrame?.actors ?? [], [previewFrame]);
  const statesByActorId = useMemo(() => previewFrame?.statesByActorId ?? {}, [previewFrame]);
  const simActors = useMemo(() => simulationFrame?.actors ?? [], [simulationFrame]);
  const simStatesByActorId = useMemo(
    () => simulationFrame?.statesByActorId ?? {},
    [simulationFrame]
  );

  const colorByActorId = useMemo(
    () =>
      isGeneratedMode
        ? buildShipColorsByActorId(actors)
        : (Object.fromEntries(actors.map((actor) => [actor.id, getShipColor(actor)])) as Record<
            string,
            string
          >),
    [actors, isGeneratedMode]
  );
  const simulationStreamColorByActorId = useMemo(
    () =>
      Object.fromEntries(
        simActors.map((actor) => [actor.id, getSimulationStreamColor(actor)])
      ) as Record<string, string>,
    [simActors]
  );

  const origin = useMemo(() => ({ x: 0, y: 0 }), []);
  const recenterTarget = useMemo(() => {
    const ownShip = actors.find((a) => a.isOwnShip);
    if (ownShip) {
      const os = statesByActorId[ownShip.id];
      if (os) {
        return { x: os.x - origin.x, y: os.y - origin.y };
      }
    }
    return { x: 0, y: 0 };
  }, [actors, origin.x, origin.y, statesByActorId]);
  const fitExtents = useMemo(() => {
    const points = actors
      .map((actor) => {
        const s = statesByActorId[actor.id];
        if (!s) return null;
        return {
          x: s.x - origin.x,
          y: s.y - origin.y,
          radius: Math.max(actor.safetyRadius, actor.length * 0.5, actor.breadth * 0.5, 1),
        };
      })
      .filter((p): p is { x: number; y: number; radius: number } => p !== null);

    if (points.length === 0) {
      return { halfWidth: 300, halfHeight: 300 };
    }

    let halfWidth = 0;
    let halfHeight = 0;
    for (const p of points) {
      halfWidth = Math.max(halfWidth, Math.abs(p.x - recenterTarget.x) + p.radius);
      halfHeight = Math.max(halfHeight, Math.abs(p.y - recenterTarget.y) + p.radius);
    }
    const margin = Math.max(Math.max(halfWidth, halfHeight) * FIT_MARGIN_RATIO, MIN_FIT_MARGIN_METERS);
    return {
      halfWidth: Math.max(120, halfWidth + margin),
      halfHeight: Math.max(120, halfHeight + margin),
    };
  }, [actors, origin.x, origin.y, recenterTarget.x, recenterTarget.y, statesByActorId]);
  const updateViewInfo = useCallback(() => {
    const controls = controlsRef.current;
    if (!controls) {
      return;
    }
    const camera = controls.object;
    const target = controls.target;
    const distance = camera.position.distanceTo(target);
    const fov = "fov" in camera ? camera.fov : 45;
    const aspect = "aspect" in camera ? camera.aspect : 1;
    const halfHeight = distance * Math.tan((fov * Math.PI) / 360);
    const halfWidth = halfHeight * aspect;
    const zoomScale = BASE_HALF_WIDTH_FOR_ZOOM / Math.max(halfWidth, 1);
    setViewInfo({
      xMin: target.x - halfWidth,
      xMax: target.x + halfWidth,
      yMin: target.y - halfHeight,
      yMax: target.y + halfHeight,
      zoomScale,
    });
  }, []);
  const fitToScenario = useCallback(() => {
    const controls = controlsRef.current;
    if (!controls) {
      return false;
    }
    const camera = controls.object;
    const fov = "fov" in camera ? camera.fov : 45;
    const aspect = "aspect" in camera ? Math.max(camera.aspect, 0.1) : 1;
    const halfFovRadians = (fov * Math.PI) / 360;
    const distanceForHeight = fitExtents.halfHeight / Math.tan(halfFovRadians);
    const distanceForWidth = fitExtents.halfWidth / (Math.tan(halfFovRadians) * aspect);
    const distance = Math.max(distanceForHeight, distanceForWidth, 60);
    controls.target.set(recenterTarget.x, recenterTarget.y, 0);
    camera.position.set(recenterTarget.x, recenterTarget.y, distance);
    controls.update();
    updateViewInfo();
    return true;
  }, [fitExtents.halfHeight, fitExtents.halfWidth, recenterTarget.x, recenterTarget.y, updateViewInfo]);

  const handleControlsRef = useCallback((controls: OrbitControlsImpl | null) => {
    controlsRef.current = controls;
    if (controls) {
      controls.enableDamping = false;
      controls.mouseButtons = {
        LEFT: MOUSE.PAN,
        MIDDLE: MOUSE.DOLLY,
        RIGHT: MOUSE.ROTATE,
      };
      setControlsMountVersion((v) => v + 1);
    }
  }, []);

  useEffect(() => {
    pendingCartesianFitRef.current = true;
    setNauticalRecenterSignal((v) => v + 1);
  }, []);

  useEffect(() => {
    const id = window.setTimeout(() => updateViewInfo(), 0);
    return () => window.clearTimeout(id);
  }, [updateViewInfo, previewFrame]);
  useEffect(() => {
    if (!isGeneratedMode || !generatedScene) {
      return;
    }
    pendingCartesianFitRef.current = true;
    setNauticalRecenterSignal((v) => v + 1);
  }, [isGeneratedMode, generatedScene]);
  useEffect(() => {
    if (prevSceneViewModeRef.current === "nautical" && sceneViewMode === "cartesian") {
      pendingCartesianFitRef.current = true;
    }
    prevSceneViewModeRef.current = sceneViewMode;
    if (sceneViewMode === "nautical") {
      setNauticalRecenterSignal((v) => v + 1);
    }
  }, [sceneViewMode]);
  useEffect(() => {
    if (!pendingCartesianFitRef.current || sceneViewMode !== "cartesian") {
      return;
    }
    if (fitToScenario()) {
      pendingCartesianFitRef.current = false;
    }
  }, [sceneViewMode, controlsMountVersion, fitToScenario]);
  useEffect(() => {
    if (isGeneratedMode || !autoFitPending || !hasTrajectoryChunk || !playbackFrame) {
      return;
    }
    if (fitToScenario()) {
      consumeAutoFit();
    }
  }, [
    isGeneratedMode,
    autoFitPending,
    controlsMountVersion,
    consumeAutoFit,
    fitToScenario,
    playbackFrame,
    hasTrajectoryChunk,
  ]);

  const exportActiveFrames = isGeneratedMode
    ? generatedScene
      ? [generatedScene]
      : []
    : controlPanelMode === "simulation"
      ? simulationFrames
      : frames;
  const exportPrefix = isGeneratedMode
    ? "generated_scene"
    : controlPanelMode === "simulation"
      ? "simulation"
      : "preview";

  const onScreenshot = () => {
    const canvas = scenePanelRef.current?.querySelector("canvas");
    if (canvas instanceof HTMLCanvasElement) {
      captureCanvasScreenshot(canvas, `scene_${exportPrefix}`);
    }
  };

  return (
    <div className="scene-panel" ref={scenePanelRef}>
      <div className="canvas-rulers">
        <div className="ruler-top">
          {sceneViewMode === "cartesian" ? (
            <>
              <span>X {viewInfo.xMin.toFixed(0)} m</span>
              <span>Zoom x{viewInfo.zoomScale.toFixed(2)}</span>
              <span>X {viewInfo.xMax.toFixed(0)} m</span>
            </>
          ) : (
            <>
              <span>Geofence center lat {referenceGeofence.latitude.toFixed(6)}</span>
              <span>Nautical map mode</span>
              <span>lon {referenceGeofence.longitude.toFixed(6)}</span>
            </>
          )}
        </div>
        <div className="ruler-left">
          {sceneViewMode === "cartesian" ? (
            <>
              <span>Y {viewInfo.yMax.toFixed(0)} m</span>
              <span>Y {viewInfo.yMin.toFixed(0)} m</span>
            </>
          ) : (
            <>
              <span>Reference (0,0) at geofence center</span>
              <span>Rendered as WGS84</span>
            </>
          )}
        </div>
        <RecenterControl
          className="axis-legend"
          legendMode={sceneViewMode === "nautical" ? "nautical" : "cartesian"}
          onRecenter={() => {
            if (sceneViewMode === "nautical") {
              setNauticalRecenterSignal((v) => v + 1);
              return;
            }
            fitToScenario();
          }}
        />
      </div>
      {sceneViewMode === "nautical" ? (
        <NauticalMapView
          layers={[
            ...(showPreview
              ? [
                  {
                    actors,
                    statesByActorId,
                    trajectoriesByActorId,
                    colorByActorId,
                    showVelocity: previewOverlays.velocity,
                  },
                ]
              : []),
            ...(showSimulation
              ? [
                  {
                    actors: simActors,
                    statesByActorId: simStatesByActorId,
                    trajectoriesByActorId: simulationTrajectoriesByActorId,
                    colorByActorId: simulationStreamColorByActorId,
                    showVelocity: simulationOverlays.velocity,
                  },
                ]
              : []),
          ]}
          reference={{
            latitude: referenceGeofence.latitude,
            longitude: referenceGeofence.longitude,
          }}
          recenterSignal={nauticalRecenterSignal}
        />
      ) : (
        <Canvas camera={{ position: [0, 0, 380], fov: 45, near: 0.1, far: 500000 }}>
          <ambientLight intensity={0.9} />
          <directionalLight position={[30, 60, 80]} intensity={0.5} />
          <mesh position={[0, 0, -8]} renderOrder={-10}>
            <planeGeometry args={[SEA_PLANE_SIZE, SEA_PLANE_SIZE]} />
            <meshStandardMaterial color="#3A457A" depthWrite={false} />
          </mesh>

          {showPreview && (
            <>
              {previewOverlays.trajectory && (
                <TrajectoriesLayer
                  stream="animation"
                  trajectoriesByActorId={trajectoriesByActorId}
                  origin={previewOrigin}
                  colorByActorId={colorByActorId}
                  zoomScale={viewInfo.zoomScale}
                />
              )}
              {previewOverlays.velocity && (
                <VelocityVectorsLayer
                  stream="animation"
                  actors={actors}
                  statesByActorId={statesByActorId}
                  origin={previewOrigin}
                  colorByActorId={colorByActorId}
                  zoomScale={viewInfo.zoomScale}
                />
              )}
              {(previewOverlays.safetyDomain || previewOverlays.safetyRadius) && (
                <DomainsLayer
                  stream="animation"
                  actors={actors}
                  statesByActorId={statesByActorId}
                  origin={previewOrigin}
                  colorByActorId={colorByActorId}
                />
              )}
              {previewOverlays.dot && (
                <VesselMarkerLayer
                  stream="animation"
                  actors={actors}
                  statesByActorId={statesByActorId}
                  origin={previewOrigin}
                  zoomScale={viewInfo.zoomScale}
                  colorByActorId={colorByActorId}
                />
              )}
            </>
          )}

          {showSimulation && (
            <>
              {simulationOverlays.trajectory && (
                <TrajectoriesLayer
                  stream="simulation"
                  trajectoriesByActorId={simulationTrajectoriesByActorId}
                  origin={simulationOrigin}
                  colorByActorId={simulationStreamColorByActorId}
                  zoomScale={viewInfo.zoomScale}
                />
              )}
              {simulationOverlays.velocity && (
                <VelocityVectorsLayer
                  stream="simulation"
                  actors={simActors}
                  statesByActorId={simStatesByActorId}
                  origin={simulationOrigin}
                  colorByActorId={simulationStreamColorByActorId}
                  zoomScale={viewInfo.zoomScale}
                />
              )}
              {(simulationOverlays.safetyDomain || simulationOverlays.safetyRadius) && (
                <DomainsLayer
                  stream="simulation"
                  actors={simActors}
                  statesByActorId={simStatesByActorId}
                  origin={simulationOrigin}
                  colorByActorId={simulationStreamColorByActorId}
                />
              )}
              {simulationOverlays.dot && (
                <VesselMarkerLayer
                  stream="simulation"
                  actors={simActors}
                  statesByActorId={simStatesByActorId}
                  origin={simulationOrigin}
                  zoomScale={viewInfo.zoomScale}
                  colorByActorId={simulationStreamColorByActorId}
                />
              )}
            </>
          )}

          <OrbitControls
            ref={handleControlsRef}
            makeDefault
            enablePan
            enableRotate={false}
            enableDamping={false}
            minDistance={40}
            maxDistance={200000}
            onChange={updateViewInfo}
          />
        </Canvas>
      )}
      <button
        type="button"
        className="scene-view-toggle-btn"
        onClick={() => {
          setSceneViewMode(sceneViewMode === "cartesian" ? "nautical" : "cartesian");
        }}
      >
        {sceneViewMode === "cartesian" ? "Nautical GPS" : "Cartesian Canvas"}
      </button>
      <div className="scene-export-toolbar toolbar-row" aria-label="Export scene">
        <button type="button" onClick={onScreenshot}>
          Screenshot
        </button>
        <button
          type="button"
          disabled={exportActiveFrames.length === 0}
          onClick={() => exportFramesAsCsv(exportActiveFrames, exportPrefix)}
        >
          CSV
        </button>
        <button
          type="button"
          disabled={exportActiveFrames.length === 0}
          onClick={() => exportFramesAsGeoJson(exportActiveFrames, exportPrefix)}
        >
          GeoJSON
        </button>
      </div>
    </div>
  );
}
