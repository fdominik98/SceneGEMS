import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ActorKinematicState, ActorStaticInfo } from "../../domain/simulation/types";
import { localMetersToLatLon } from "./geoTransform";

interface TrajectoryPoint {
  x: number;
  y: number;
}

interface Props {
  layers: Array<{
    actors: ActorStaticInfo[];
    statesByActorId: Record<string, ActorKinematicState>;
    trajectoriesByActorId: Record<string, TrajectoryPoint[]>;
    colorByActorId: Record<string, string>;
    showVelocity: boolean;
  }>;
  reference: { latitude: number; longitude: number };
  recenterSignal: number;
}

export function NauticalMapView({
  layers,
  reference,
  recenterSignal,
}: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayLayerRef = useRef<L.LayerGroup | null>(null);
  const lastBoundsRef = useRef<L.LatLngBounds | null>(null);
  const hasAutoFittedRef = useRef(false);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }
    const map = L.map(mapContainerRef.current, {
      zoomControl: false,
      attributionControl: false,
    });
    mapRef.current = map;
    map.setView([reference.latitude, reference.longitude], 15);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
    }).addTo(map);

    L.tileLayer("https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png", {
      maxZoom: 18,
      opacity: 0.9,
    }).addTo(map);

    overlayLayerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      mapRef.current = null;
      overlayLayerRef.current = null;
    };
  }, [reference.latitude, reference.longitude]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.panTo([reference.latitude, reference.longitude], { animate: false });
  }, [reference.latitude, reference.longitude]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = overlayLayerRef.current;
    if (!map || !layer) {
      return;
    }
    layer.clearLayers();

    const boundsPoints: L.LatLngExpression[] = [[reference.latitude, reference.longitude]];
    L.circle([reference.latitude, reference.longitude], {
      radius: 1.5,
      color: "#f8fafc",
      weight: 2,
      opacity: 0.9,
    }).addTo(layer);

    for (const visualLayer of layers) {
      for (const actor of visualLayer.actors) {
        const state = visualLayer.statesByActorId[actor.id];
        if (!state) {
          continue;
        }
        const color = visualLayer.colorByActorId[actor.id] ?? "#22d3ee";
        const [lat, lon] = localMetersToLatLon(state.x, state.y, reference);
        const latLng: [number, number] = [lat, lon];
        boundsPoints.push(latLng);

        const path = visualLayer.trajectoriesByActorId[actor.id] ?? [];
        if (path.length > 1) {
          const latLngPath = path.map((point) => localMetersToLatLon(point.x, point.y, reference));
          latLngPath.forEach((coord) => boundsPoints.push([coord[0], coord[1]]));
          L.polyline(latLngPath as L.LatLngExpression[], {
            color,
            weight: actor.isOwnShip ? 4 : 2.5,
            opacity: 0.85,
          }).addTo(layer);
        }

        if (visualLayer.showVelocity && Number.isFinite(state.speed) && Number.isFinite(state.heading)) {
          const velocityLengthMeters = Math.max(6, Math.min(80, state.speed * 12));
          const vx = Math.cos(state.heading) * velocityLengthMeters;
          const vy = Math.sin(state.heading) * velocityLengthMeters;
          const [vLat, vLon] = localMetersToLatLon(state.x + vx, state.y + vy, reference);
          L.polyline([latLng, [vLat, vLon]], {
            color,
            weight: 2,
            opacity: 0.9,
            dashArray: "6,4",
          }).addTo(layer);
        }

        L.circleMarker(latLng, {
          radius: actor.isOwnShip ? 8 : 6,
          color,
          weight: 2,
          fillOpacity: 0.85,
        })
          .bindTooltip(`${actor.name} (${actor.id})`, { direction: "top" })
          .addTo(layer);
      }
    }

    const hasSceneContent = boundsPoints.length > 1;
    if (!hasSceneContent) {
      lastBoundsRef.current = null;
      hasAutoFittedRef.current = false;
      return;
    }

    const bounds = L.latLngBounds(boundsPoints as L.LatLngTuple[]);
    lastBoundsRef.current = bounds;
    if (!hasAutoFittedRef.current) {
      hasAutoFittedRef.current = true;
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 18 });
    }
  }, [layers, reference]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    hasAutoFittedRef.current = false;
    const bounds = lastBoundsRef.current;
    if (bounds) {
      hasAutoFittedRef.current = true;
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 18 });
      return;
    }
    map.setView([reference.latitude, reference.longitude], 15);
  }, [recenterSignal, reference.latitude, reference.longitude]);

  return <div className="nautical-map-canvas" ref={mapContainerRef} />;
}
