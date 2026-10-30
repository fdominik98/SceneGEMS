import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useCanvasSettings } from "./canvasSettings";
import { CanvasToolbar } from "./CanvasToolbar";
import {
  anchorOf,
  drawnStreams,
  fitPoints,
  ownShipOf,
  primaryStream,
  vesselClickHandler,
  type EncounterCanvasStream,
} from "./canvasStreams";
import {
  fitView,
  formatDegrees,
  formatNm,
  headUpRotation,
  rangeBetween,
  screenToWorld,
  trueBearingDeg,
  type Point,
  type ViewTransform,
} from "./encounterGeometry";
import { EncounterLayers } from "./EncounterLayers";
import { CANVAS_COLORS, CANVAS_FONT } from "./encounterPalette";
import type { LayerColumn } from "./LayerMenu";
import "./encounterCanvas.css";

export type { EncounterCanvasStream } from "./canvasStreams";

export interface EncounterCanvasProps {
  streams: EncounterCanvasStream[];
  /** The switches of the layer menu, a column per stream. */
  layerColumns: LayerColumn[];
  /** Changing this number fits the view to the vessels (once a frame and a size exist). */
  fitSignal?: number;
  /** Called after each fit. */
  onFit?: () => void;
  selectedRelationId?: string | null;
  onSelectRelation?: (relationId: string | null) => void;
  /** Buttons laid over the canvas's top right (export, map switch). */
  children?: ReactNode;
  /** Receives the SVG element (for screenshots). */
  svgRef?: (element: SVGSVGElement | null) => void;
  emptyMessage?: string;
}

const MIN_SCALE = 1e-5;
const MAX_SCALE = 40;
/** Room kept free of vessels when fitting: the toolbar above, the north arrow and actions right, the scale bar below. */
const FIT_INSETS = { top: 60, right: 70, bottom: 40, left: 24 };

interface ViewState {
  /**
   * View center relative to the anchor (the own ship, or the vessels' centroid), in the
   * view's rotated frame (u right, v up on screen), so head-up keeps the own ship in place
   * as its heading changes.
   */
  offset: Point;
  /** Pixels per meter. */
  scale: number;
}

/** A world displacement in the view's rotated frame, and back. */
function toViewFrame(d: Point, rotation: number): Point {
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return { x: d.x * cos - d.y * sin, y: d.x * sin + d.y * cos };
}

function fromViewFrame(d: Point, rotation: number): Point {
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return { x: d.x * cos + d.y * sin, y: -d.x * sin + d.y * cos };
}

/**
 * The 2D encounter canvas in a nautical presentation: north-up or head-up around the own
 * ship, range rings, a true bearing scale, hulls to scale with heading lines, course and
 * speed vectors with time marks, the past track and the path ahead, the CPA of each
 * encounter, safety and maneuvering domains, and each vessel's encounters and roles.
 * Drag pans, the wheel zooms around the pointer, double-click or Fit recenters on the own
 * ship. It draws what its streams give it and reads no store.
 */
export function EncounterCanvas({
  streams,
  layerColumns,
  fitSignal = 0,
  onFit,
  selectedRelationId = null,
  onSelectRelation,
  children,
  svgRef,
  emptyMessage = "No scene to show yet.",
}: EncounterCanvasProps) {
  const [settings, updateSettings] = useCanvasSettings();

  const hostRef = useRef<HTMLDivElement | null>(null);
  const svgElementRef = useRef<SVGSVGElement | null>(null);
  const readoutRef = useRef<HTMLSpanElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [view, setView] = useState<ViewState>({ offset: { x: 0, y: 0 }, scale: 0.1 });
  const [pendingFit, setPendingFit] = useState(true);
  /** The user zoomed or panned since the last fit: a resize then keeps the view. */
  const [adjusted, setAdjusted] = useState(false);
  const [fittedSize, setFittedSize] = useState(size);
  const [seenFitSignal, setSeenFitSignal] = useState(fitSignal);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((prev) =>
        Math.abs(prev.width - width) < 0.5 && Math.abs(prev.height - height) < 0.5 ? prev : { width, height }
      );
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  if (fitSignal !== seenFitSignal) {
    setSeenFitSignal(fitSignal);
    setPendingFit(true);
  }

  const visibleStreams = drawnStreams(streams);
  const primary = primaryStream(visibleStreams);
  const frame = primary?.frame ?? null;
  const own = ownShipOf(frame);
  const anchor = anchorOf(frame);
  const headUp = settings.orientation === "head-up" && own !== null;
  const rotation = headUp && own ? headUpRotation(own.state.heading) : 0;

  const transform: ViewTransform = {
    center: (() => {
      const d = fromViewFrame(view.offset, rotation);
      return { x: anchor.x + d.x, y: anchor.y + d.y };
    })(),
    scale: view.scale,
    rotation,
    width: Math.max(size.width, 1),
    height: Math.max(size.height, 1),
  };
  const transformRef = useRef(transform);
  useEffect(() => {
    transformRef.current = transform;
  });

  /** The view centered on the anchor that fits every vessel, or null before a frame and a size exist. */
  const computeFitView = (): ViewState | null => {
    if (size.width < 20 || size.height < 20) {
      return null;
    }
    const fitted = fitView(fitPoints(visibleStreams), rotation, size.width, size.height, FIT_INSETS);
    if (!fitted) {
      return null;
    }
    return {
      offset: toViewFrame({ x: fitted.center.x - anchor.x, y: fitted.center.y - anchor.y }, rotation),
      scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, fitted.scale)),
    };
  };
  const [fitCount, setFitCount] = useState(0);
  const resized = fittedSize.width !== size.width || fittedSize.height !== size.height;
  if (pendingFit || (resized && !adjusted)) {
    const next = computeFitView();
    if (next) {
      setPendingFit(false);
      setView(next);
      setFittedSize(size);
      setAdjusted(false);
      setFitCount((count) => count + 1);
    }
  }
  const fit = () => {
    const next = computeFitView();
    if (next) {
      setView(next);
      setFittedSize(size);
      setAdjusted(false);
      setFitCount((count) => count + 1);
    }
  };
  const reportedFit = useRef(0);
  useEffect(() => {
    if (fitCount !== reportedFit.current) {
      reportedFit.current = fitCount;
      onFit?.();
    }
  }, [fitCount, onFit]);

  // Wheel zoom around the pointer; a native listener so the page does not scroll.
  useEffect(() => {
    const svg = svgElementRef.current;
    if (!svg) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const current = transformRef.current;
      const factor = Math.exp(-event.deltaY * 0.0015);
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
      const before = screenToWorld(current, pointer);
      const after = screenToWorld({ ...current, scale }, pointer);
      setAdjusted(true);
      setView((prev) => ({
        scale,
        offset: (() => {
          const d = toViewFrame({ x: before.x - after.x, y: before.y - after.y }, current.rotation);
          return { x: prev.offset.x + d.x, y: prev.offset.y + d.y };
        })(),
      }));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const dragRef = useRef<{ id: number; last: Point; moved: boolean } | null>(null);
  const pointerPosition = (event: ReactPointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    dragRef.current = { id: event.pointerId, last: pointerPosition(event), moved: false };
  };
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const p = pointerPosition(event);
    const drag = dragRef.current;
    if (drag && drag.id === event.pointerId) {
      if (!drag.moved && Math.hypot(p.x - drag.last.x, p.y - drag.last.y) < 3) {
        return;
      }
      if (!drag.moved) {
        drag.moved = true;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      const current = transformRef.current;
      const from = screenToWorld(current, drag.last);
      const to = screenToWorld(current, p);
      drag.last = p;
      setAdjusted(true);
      const d = toViewFrame({ x: from.x - to.x, y: from.y - to.y }, current.rotation);
      setView((prev) => ({ ...prev, offset: { x: prev.offset.x + d.x, y: prev.offset.y + d.y } }));
      return;
    }
    const readout = readoutRef.current;
    if (readout) {
      const world = screenToWorld(transformRef.current, p);
      const reference = own ? `${formatNm(rangeBetween(own.state, world))} ${formatDegrees(trueBearingDeg(own.state, world))} from ${own.actor.name} · ` : "";
      readout.textContent = `${reference}x ${Math.round(world.x)} m, y ${Math.round(world.y)} m`;
    }
  };
  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.id === event.pointerId) {
      dragRef.current = null;
    }
  };
  const onPointerLeave = () => {
    if (readoutRef.current) {
      readoutRef.current.textContent = "";
    }
  };

  const ready = size.width > 0 && size.height > 0;

  return (
    <div className="enc-canvas" ref={hostRef}>
      <svg
        ref={(element) => {
          svgElementRef.current = element;
          svgRef?.(element);
        }}
        className="enc-canvas-svg"
        width={transform.width}
        height={transform.height}
        viewBox={`0 0 ${transform.width} ${transform.height}`}
        xmlns="http://www.w3.org/2000/svg"
        fontFamily={CANVAS_FONT}
        role="img"
        aria-label="Encounter canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onDoubleClick={() => fit()}
      >
        <rect width={transform.width} height={transform.height} fill={CANVAS_COLORS.sea} />
        {ready && frame ? (
          <EncounterLayers
            streams={visibleStreams}
            view={transform}
            settings={settings}
            headUp={headUp}
            selectedRelationId={selectedRelationId}
            onVesselClick={vesselClickHandler(frame, selectedRelationId, onSelectRelation)}
          />
        ) : null}
      </svg>

      {!frame ? <p className="enc-canvas-empty">{emptyMessage}</p> : null}

      <CanvasToolbar
        onFit={fit}
        fitTitle="Fit view: every vessel in sight (or double-click the canvas)"
        settings={settings}
        onSettingsChange={updateSettings}
        onOrientationChange={(orientation) => {
          updateSettings({ orientation });
          setPendingFit(true);
        }}
        canHeadUp={own !== null}
        layerColumns={layerColumns}
      >
        {children}
      </CanvasToolbar>
      <span className="enc-canvas-readout" ref={readoutRef} aria-live="off" />
    </div>
  );
}
