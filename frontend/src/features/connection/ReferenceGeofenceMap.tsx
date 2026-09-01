import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  defaultReferenceGeofence,
  getGeofenceMapCenter,
  type ReferenceGeofence,
} from "./referenceGeofence";

const MIN_RADIUS_METERS = 10;
const MAX_RADIUS_METERS = 100_000;

interface ReferenceGeofenceMapProps {
  geofence: ReferenceGeofence;
  onGeofenceChange: (geofence: ReferenceGeofence) => void;
}

/** Clamp a radius to a sane range and drop non-finite values. */
function sanitizeGeofence(geofence: ReferenceGeofence): ReferenceGeofence {
  const latitude = Number.isFinite(geofence.latitude)
    ? geofence.latitude
    : defaultReferenceGeofence.latitude;
  const longitude = Number.isFinite(geofence.longitude)
    ? geofence.longitude
    : defaultReferenceGeofence.longitude;
  const rawRadius = Number.isFinite(geofence.radius_meters)
    ? geofence.radius_meters
    : defaultReferenceGeofence.radius_meters;
  return {
    latitude,
    longitude,
    radius_meters: Math.min(MAX_RADIUS_METERS, Math.max(MIN_RADIUS_METERS, rawRadius)),
  };
}

function geofencesEqual(a: ReferenceGeofence, b: ReferenceGeofence): boolean {
  return (
    a.latitude === b.latitude &&
    a.longitude === b.longitude &&
    a.radius_meters === b.radius_meters
  );
}

export function ReferenceGeofenceMap({ geofence, onGeofenceChange }: ReferenceGeofenceMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const circleRef = useRef<L.Circle | null>(null);
  const clickMarkerRef = useRef<L.CircleMarker | null>(null);
  const centerRef = useRef<L.LatLng | null>(null);
  const isSelectionModeRef = useRef(false);
  const isWaitingRadiusRef = useRef(false);
  const initialGeofenceRef = useRef<ReferenceGeofence>(sanitizeGeofence(geofence));
  // Keep the latest callback in a ref so the map-init effect never re-runs when
  // the parent passes a fresh inline function (it re-renders on every stream
  // frame). Re-running that effect would tear down and rebuild the whole map.
  const onGeofenceChangeRef = useRef(onGeofenceChange);
  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [isWaitingRadius, setIsWaitingRadius] = useState(false);

  const isDefault = useMemo(
    () => geofencesEqual(sanitizeGeofence(geofence), defaultReferenceGeofence),
    [geofence]
  );

  // Abort an in-progress selection and restore the drawn circle.
  const cancelSelection = useCallback(() => {
    centerRef.current = null;
    isWaitingRadiusRef.current = false;
    isSelectionModeRef.current = false;
    setIsWaitingRadius(false);
    setIsSelectionMode(false);
    clickMarkerRef.current?.remove();
    clickMarkerRef.current = null;
    const clean = sanitizeGeofence(geofence);
    circleRef.current?.setLatLng([clean.latitude, clean.longitude]);
    circleRef.current?.setRadius(clean.radius_meters);
  }, [geofence]);

  // Mirror it into a ref so the map-init effect's keydown handler (registered
  // once) always calls the current version without re-subscribing.
  const cancelSelectionRef = useRef(cancelSelection);
  useEffect(() => {
    cancelSelectionRef.current = cancelSelection;
  }, [cancelSelection]);

  useEffect(() => {
    onGeofenceChangeRef.current = onGeofenceChange;
  }, [onGeofenceChange]);

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
        isWaitingRadiusRef.current = true;
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
      const radiusM = Math.min(
        MAX_RADIUS_METERS,
        Math.max(MIN_RADIUS_METERS, c.distanceTo(event.latlng))
      );
      onGeofenceChangeRef.current({
        latitude: c.lat,
        longitude: c.lng,
        radius_meters: radiusM,
      });
      centerRef.current = null;
      isWaitingRadiusRef.current = false;
      isSelectionModeRef.current = false;
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
      const radiusM = Math.min(
        MAX_RADIUS_METERS,
        Math.max(MIN_RADIUS_METERS, centerRef.current.distanceTo(event.latlng))
      );
      circleRef.current.setLatLng(centerRef.current);
      circleRef.current.setRadius(radiusM);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isSelectionModeRef.current) {
        cancelSelectionRef.current();
      }
    };

    map.on("click", onClick);
    map.on("mousemove", onMouseMove);
    window.addEventListener("keydown", onKeyDown);

    const resizeTimer = window.setTimeout(() => map.invalidateSize(), 0);
    return () => {
      window.clearTimeout(resizeTimer);
      window.removeEventListener("keydown", onKeyDown);
      map.off("click", onClick);
      map.off("mousemove", onMouseMove);
      map.remove();
      mapRef.current = null;
      circleRef.current = null;
      clickMarkerRef.current = null;
      centerRef.current = null;
    };
  }, []);

  // Keep the drawn circle in sync with the committed geofence whenever we are
  // not mid-selection (during a radius drag the circle is driven by the mouse).
  useEffect(() => {
    if (!circleRef.current || isWaitingRadius) {
      return;
    }
    const clean = sanitizeGeofence(geofence);
    circleRef.current.setLatLng([clean.latitude, clean.longitude]);
    circleRef.current.setRadius(clean.radius_meters);
  }, [geofence, isWaitingRadius]);

  // Double-click zoom would fire a stray zoom (and a second click) while the
  // user is placing the center/radius, so suspend it during selection.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (isSelectionMode) {
      map.doubleClickZoom.disable();
    } else {
      map.doubleClickZoom.enable();
    }
  }, [isSelectionMode]);

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
    if (isSelectionMode) {
      cancelSelection();
      return;
    }
    setIsSelectionMode(true);
  };

  const resetToDefault = () => {
    cancelSelection();
    onGeofenceChangeRef.current({ ...defaultReferenceGeofence });
    const map = mapRef.current;
    const circle = circleRef.current;
    if (map && circle) {
      circle.setLatLng([
        defaultReferenceGeofence.latitude,
        defaultReferenceGeofence.longitude,
      ]);
      circle.setRadius(defaultReferenceGeofence.radius_meters);
      map.fitBounds(circle.getBounds(), { padding: [25, 25] });
    }
  };

  return (
    <section className="panel geofence-panel">
      <h3>Reference Geofence</h3>
      <p className="meta">
        Use the target button, then click the center, then click again to set the radius (distance from
        center). Press Escape to cancel.
      </p>
      <div className="toolbar-row">
        <button
          className={`geofence-target-toggle${isSelectionMode ? " active" : ""}`}
          onClick={toggleSelectionMode}
        >
          ⌖ {isSelectionMode ? "Selecting..." : "Select Geofence"}
        </button>
        <button onClick={resetToDefault} disabled={isDefault && !isSelectionMode}>
          Reset to default
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
