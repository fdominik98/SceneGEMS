import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  getGeofenceMapCenter,
  type ReferenceGeofence,
} from "./referenceGeofence";

const MIN_RADIUS_METERS = 10;

interface ReferenceGeofenceMapProps {
  geofence: ReferenceGeofence;
  onGeofenceChange: (geofence: ReferenceGeofence) => void;
}

export function ReferenceGeofenceMap({ geofence, onGeofenceChange }: ReferenceGeofenceMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const circleRef = useRef<L.Circle | null>(null);
  const clickMarkerRef = useRef<L.CircleMarker | null>(null);
  const centerRef = useRef<L.LatLng | null>(null);
  const isSelectionModeRef = useRef(false);
  const isWaitingRadiusRef = useRef(false);
  const initialGeofenceRef = useRef<ReferenceGeofence>(geofence);
  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [isWaitingRadius, setIsWaitingRadius] = useState(false);

  useEffect(() => {
    isSelectionModeRef.current = isSelectionMode;
  }, [isSelectionMode]);

  useEffect(() => {
    isWaitingRadiusRef.current = isWaitingRadius;
  }, [isWaitingRadius]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const center = getGeofenceMapCenter(initialGeofenceRef.current);
    const map = L.map(mapContainerRef.current).setView(center, 12);
    mapRef.current = map;
    map.attributionControl.setPrefix("");

    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles &copy; Esri",
      }
    ).addTo(map);

    const init = initialGeofenceRef.current;
    circleRef.current = L.circle([init.latitude, init.longitude], {
      radius: init.radius_meters,
      color: "#22d3ee",
      weight: 2,
      fillOpacity: 0.12,
    }).addTo(map);
    map.fitBounds(circleRef.current.getBounds(), { padding: [25, 25] });

    const onClick = (event: L.LeafletMouseEvent) => {
      if (!isSelectionModeRef.current) {
        return;
      }
      const c = centerRef.current;
      if (!c) {
        centerRef.current = event.latlng;
        setIsWaitingRadius(true);
        if (!clickMarkerRef.current) {
          clickMarkerRef.current = L.circleMarker(event.latlng, {
            radius: 6,
            color: "#38bdf8",
            fillColor: "#0ea5e9",
            fillOpacity: 0.85,
          }).addTo(map);
        } else {
          clickMarkerRef.current.setLatLng(event.latlng);
        }
        return;
      }
      const radiusM = Math.max(MIN_RADIUS_METERS, c.distanceTo(event.latlng));
      onGeofenceChange({
        latitude: c.lat,
        longitude: c.lng,
        radius_meters: radiusM,
      });
      centerRef.current = null;
      setIsWaitingRadius(false);
      setIsSelectionMode(false);
      clickMarkerRef.current?.remove();
      clickMarkerRef.current = null;
    };

    const onMouseMove = (event: L.LeafletMouseEvent) => {
      if (
        !isSelectionModeRef.current ||
        !isWaitingRadiusRef.current ||
        !centerRef.current ||
        !circleRef.current
      ) {
        return;
      }
      const radiusM = Math.max(MIN_RADIUS_METERS, centerRef.current.distanceTo(event.latlng));
      circleRef.current.setLatLng(centerRef.current);
      circleRef.current.setRadius(radiusM);
    };

    map.on("click", onClick);
    map.on("mousemove", onMouseMove);

    const resizeTimer = window.setTimeout(() => map.invalidateSize(), 0);
    return () => {
      window.clearTimeout(resizeTimer);
      map.off("click", onClick);
      map.off("mousemove", onMouseMove);
      map.remove();
      mapRef.current = null;
    };
  }, [onGeofenceChange]);

  useEffect(() => {
    if (!circleRef.current || isWaitingRadius) {
      return;
    }
    circleRef.current.setLatLng([geofence.latitude, geofence.longitude]);
    circleRef.current.setRadius(geofence.radius_meters);
  }, [geofence, isWaitingRadius]);

  useEffect(() => {
    const container = mapContainerRef.current;
    const map = mapRef.current;
    if (!container || !map) {
      return;
    }
    const observer = new ResizeObserver(() => {
      map.invalidateSize();
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const toggleSelectionMode = () => {
    setIsSelectionMode((prev) => {
      const next = !prev;
      if (!next) {
        centerRef.current = null;
        setIsWaitingRadius(false);
        clickMarkerRef.current?.remove();
        clickMarkerRef.current = null;
      }
      return next;
    });
  };

  return (
    <section className="panel geofence-panel">
      <h3>Reference Geofence</h3>
      <p className="meta">
        Use the target button, then click the center, then click again to set the radius (distance from
        center).
      </p>
      <div className="toolbar-row">
        <button
          className={`geofence-target-toggle${isSelectionMode ? " active" : ""}`}
          onClick={toggleSelectionMode}
        >
          ⌖ {isSelectionMode ? "Selecting..." : "Select Geofence"}
        </button>
        {isWaitingRadius && <span className="meta">Click to set radius</span>}
      </div>
      <div
        className={`geofence-map${isSelectionMode ? " selecting" : ""}`}
        ref={mapContainerRef}
      />
      <p className="meta">
        Lat: {geofence.latitude.toFixed(6)} | Lon: {geofence.longitude.toFixed(6)} | Radius:{" "}
        {Math.round(geofence.radius_meters)} m
      </p>
    </section>
  );
}
