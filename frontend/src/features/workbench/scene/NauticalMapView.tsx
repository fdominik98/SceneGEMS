import { useEffect, useRef, useState, type ReactNode } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useCanvasSettings } from "./canvasSettings";
import { CanvasToolbar } from "./CanvasToolbar";
import {
  drawnStreams,
  fitBox,
  fitPoints,
  ownShipOf,
  primaryStream,
  vesselClickHandler,
  type DrawnStream,
  type EncounterCanvasStream,
} from "./canvasStreams";
import { formatDegrees, formatNm, rangeBetween, trueBearingDeg, worldToScreen, type ViewTransform } from "./encounterGeometry";
import { EncounterLayers } from "./EncounterLayers";
import { CANVAS_FONT } from "./encounterPalette";
import { latLonToLocalMeters, localMetersToLatLon, mapViewTransform } from "./geoTransform";
import type { LayerColumn } from "./LayerMenu";
import "./encounterCanvas.css";

interface Reference {
  latitude: number;
  longitude: number;
}

interface NauticalMapViewProps {
  streams: EncounterCanvasStream[];
  /** The switches of the layer menu, a column per stream. */
  layerColumns: LayerColumn[];
  /** The reference point (geofence center) the local meters of the frames start from. */
  reference: Reference;
  /** Changing this number fits the map to the vessels (once they are there). */
  fitSignal?: number;
  /** Changing this number fits the map too, unless the user moved or zoomed it since the last fit. */
  followSignal?: number;
  /** Called after each fit the signal asked for. */
  onFit?: () => void;
  selectedRelationId?: string | null;
  onSelectRelation?: (relationId: string | null) => void;
  /** Buttons laid over the map's top right (export, map switch). */
  children?: ReactNode;
  emptyMessage?: string;
}

/** Room kept free of vessels when fitting: the toolbar above, the scale bar and the attribution below. */
const FIT_PADDING_TOP_LEFT: [number, number] = [24, 64];
const FIT_PADDING_BOTTOM_RIGHT: [number, number] = [24, 56];
/** Height of the tile attribution along the bottom, kept free of the scale bar and the legend. */
const ATTRIBUTION_HEIGHT = 22;
/** How far from a vessel's position a click still selects it, in pixels. */
const VESSEL_HIT_PX = 14;

function formatLatLon(latitude: number, longitude: number): string {
  return `${Math.abs(latitude).toFixed(5)}° ${latitude >= 0 ? "N" : "S"}, ${Math.abs(longitude).toFixed(5)}° ${longitude >= 0 ? "E" : "W"}`;
}

/** Fits the map to the vessels of the streams; false while there are none. */
function fitMap(map: L.Map, streams: DrawnStream[], reference: Reference): boolean {
  const box = fitBox(fitPoints(streams));
  if (!box) {
    return false;
  }
  const corners = [
    localMetersToLatLon(box.minX, box.minY, reference),
    localMetersToLatLon(box.minX, box.maxY, reference),
    localMetersToLatLon(box.maxX, box.minY, reference),
    localMetersToLatLon(box.maxX, box.maxY, reference),
  ];
  map.fitBounds(L.latLngBounds(corners), {
    paddingTopLeft: FIT_PADDING_TOP_LEFT,
    paddingBottomRight: FIT_PADDING_BOTTOM_RIGHT,
    maxZoom: 19,
    animate: false,
  });
  return true;
}

/**
 * The encounter on a nautical chart: OpenStreetMap with the OpenSeaMap seamarks, darkened to
 * the canvas's colors, under the same drawing as the encounter canvas (hulls, vectors, tracks,
 * domains, CPA marks, labels, range rings), placed by the frames' local meters from the
 * reference point. Drag pans, the wheel zooms, a click on a vessel selects its pair with the
 * own ship. The map is always north up.
 */
export function NauticalMapView({
  streams,
  layerColumns,
  reference,
  fitSignal = 0,
  followSignal = 0,
  onFit,
  selectedRelationId = null,
  onSelectRelation,
  children,
  emptyMessage = "No scene to show yet.",
}: NauticalMapViewProps) {
  const [settings, updateSettings] = useCanvasSettings();
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const syncRef = useRef<(() => void) | null>(null);
  const readoutRef = useRef<HTMLSpanElement | null>(null);
  /** The canvas transform matching the map's current center and zoom; null until the map has a size. */
  const [view, setView] = useState<ViewTransform | null>(null);

  const visibleStreams = drawnStreams(streams);
  const frame = primaryStream(visibleStreams)?.frame ?? null;
  const onVesselClick = vesselClickHandler(frame, selectedRelationId, onSelectRelation);

  // What the map's own event handlers need of the latest render.
  const latest = useRef({ reference, visibleStreams, frame, view, onVesselClick });
  useEffect(() => {
    latest.current = { reference, visibleStreams, frame, view, onVesselClick };
  });
  /** `fitting` while a fit moves the map; `adjusted` once the user panned or zoomed after it (a resize then keeps the view). */
  const fitState = useRef({ fitting: false, adjusted: false, fitted: false });
  const fitNow = (map: L.Map, shown: DrawnStream[], origin: Reference): boolean => {
    fitState.current.fitting = true;
    const done = fitMap(map, shown, origin);
    fitState.current.fitting = false;
    if (done) {
      fitState.current.adjusted = false;
      fitState.current.fitted = true;
    }
    return done;
  };
  const fitNowRef = useRef(fitNow);
  useEffect(() => {
    fitNowRef.current = fitNow;
  });

  useEffect(() => {
    if (!container) {
      return;
    }
    const map = L.map(container, {
      zoomControl: false,
      attributionControl: false,
      // The drawing follows the map at each move; an animated zoom would leave it behind until the end.
      zoomAnimation: false,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      wheelPxPerZoomLevel: 90,
      maxZoom: 20,
    });
    L.control.attribution({ position: "bottomright", prefix: false }).addTo(map);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    }).addTo(map);
    L.tileLayer("https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 18,
      opacity: 0.9,
      attribution: '<a href="https://www.openseamap.org" target="_blank" rel="noreferrer">OpenSeaMap</a>',
    }).addTo(map);

    let frameId = 0;
    const sync = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(() => {
        const size = map.getSize();
        if (size.x < 1 || size.y < 1) {
          return;
        }
        const center = map.getCenter();
        setView(
          mapViewTransform(
            (latitude, longitude) => map.latLngToContainerPoint([latitude, longitude]),
            { latitude: center.lat, longitude: center.lng },
            { width: size.x, height: size.y },
            latest.current.reference
          )
        );
      });
    };
    syncRef.current = sync;
    map.on("move zoom resize viewreset", sync);
    map.on("movestart zoomstart", () => {
      if (!fitState.current.fitting) {
        fitState.current.adjusted = true;
      }
    });
    map.on("click", (event: L.LeafletMouseEvent) => {
      const { frame: shown, view: drawn, onVesselClick: select } = latest.current;
      if (!shown || !drawn || !select) {
        return;
      }
      let hit: string | null = null;
      let best = VESSEL_HIT_PX;
      for (const actor of shown.actors) {
        const state = shown.statesByActorId[actor.id];
        if (!state) continue;
        const screen = worldToScreen(drawn, state);
        const distance = Math.hypot(screen.x - event.containerPoint.x, screen.y - event.containerPoint.y);
        if (distance <= best) {
          hit = actor.id;
          best = distance;
        }
      }
      if (hit) {
        select(hit);
      }
    });
    map.on("mousemove", (event: L.LeafletMouseEvent) => {
      const readout = readoutRef.current;
      if (!readout) return;
      const { reference: origin, frame: shown } = latest.current;
      const point = latLonToLocalMeters(event.latlng.lat, event.latlng.lng, origin);
      const own = ownShipOf(shown);
      const from = own ? `${formatNm(rangeBetween(own.state, point))} ${formatDegrees(trueBearingDeg(own.state, point))} from ${own.actor.name} · ` : "";
      readout.textContent = `${from}${formatLatLon(event.latlng.lat, event.latlng.lng)}`;
    });
    map.on("mouseout", () => {
      if (readoutRef.current) {
        readoutRef.current.textContent = "";
      }
    });

    const start = latest.current.reference;
    map.setView([start.latitude, start.longitude], 15);
    // Leaflet measures its container only when told; the panes around it resize often.
    const observer = new ResizeObserver(() => {
      map.invalidateSize({ pan: false });
      if (fitState.current.fitted && !fitState.current.adjusted) {
        fitNowRef.current(map, latest.current.visibleStreams, latest.current.reference);
      }
      sync();
    });
    observer.observe(container);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frameId);
      map.remove();
      mapRef.current = null;
      syncRef.current = null;
    };
  }, [container]);

  // A new reference point moves every vessel on the chart: redraw and fit again.
  useEffect(() => {
    syncRef.current?.();
  }, [reference.latitude, reference.longitude]);

  // Fit once the map and the vessels are there, again for each fit signal and reference point.
  const fitRequest = `${fitSignal}|${reference.latitude}|${reference.longitude}`;
  const fittedRequest = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !view || fittedRequest.current === fitRequest) {
      return;
    }
    if (fitNow(map, visibleStreams, reference)) {
      fittedRequest.current = fitRequest;
      onFit?.();
    }
  });

  // A follow signal fits only a view the user left as the last fit placed it.
  const followedSignal = useRef(followSignal);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !view || followedSignal.current === followSignal) {
      return;
    }
    followedSignal.current = followSignal;
    if (!fitState.current.adjusted) {
      fitNow(map, visibleStreams, reference);
    }
  });

  return (
    <div className="enc-canvas nautical-map">
      <div className="nautical-map-tiles" ref={setContainer} />
      {view ? (
        <svg
          className="nautical-map-overlay"
          width={view.width}
          height={view.height}
          viewBox={`0 0 ${view.width} ${view.height}`}
          xmlns="http://www.w3.org/2000/svg"
          fontFamily={CANVAS_FONT}
          role="img"
          aria-label="Nautical map"
        >
          {frame ? (
            <EncounterLayers
              streams={visibleStreams}
              view={view}
              settings={settings}
              headUp={false}
              selectedRelationId={selectedRelationId}
              northArrow={false}
              bottomInset={ATTRIBUTION_HEIGHT}
            />
          ) : null}
        </svg>
      ) : null}

      {!frame ? <p className="enc-canvas-empty nautical-map-empty">{emptyMessage}</p> : null}

      <CanvasToolbar
        className="enc-canvas-toolbar--map"
        onFit={() => {
          const map = mapRef.current;
          if (map) {
            fitNow(map, visibleStreams, reference);
          }
        }}
        fitTitle="Fit view: every vessel in sight"
        settings={settings}
        onSettingsChange={updateSettings}
        layerColumns={layerColumns}
      >
        {children}
      </CanvasToolbar>
      <span className="enc-canvas-readout nautical-map-readout" ref={readoutRef} aria-live="off" />
    </div>
  );
}
