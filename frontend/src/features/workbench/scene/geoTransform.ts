import proj4 from "proj4";
import type { Converter } from "proj4";
import type { Point, ViewTransform } from "./encounterGeometry";

interface LatLon {
  latitude: number;
  longitude: number;
}

function getUtmZone(longitude: number): number {
  return Math.max(1, Math.min(60, Math.floor((longitude + 180) / 6) + 1));
}

function getUtmProjString(latitude: number, longitude: number): string {
  const zone = getUtmZone(longitude);
  const hemisphereFlag = latitude >= 0 ? "" : " +south";
  return `+proj=utm +zone=${zone}${hemisphereFlag} +datum=WGS84 +units=m +no_defs +type=crs`;
}

interface LocalFrame {
  converter: Converter;
  x0: number;
  y0: number;
}

const frames = new Map<string, LocalFrame>();

/**
 * The local frame of a reference point, as the backend's `Geofence` builds it: UTM easting
 * and northing of its zone, relative to the reference. Built once per reference.
 */
function localFrame(reference: LatLon): LocalFrame {
  const key = `${reference.latitude},${reference.longitude}`;
  let frame = frames.get(key);
  if (!frame) {
    const converter = proj4("EPSG:4326", getUtmProjString(reference.latitude, reference.longitude));
    const [x0, y0] = converter.forward([reference.longitude, reference.latitude]);
    frame = { converter, x0: x0!, y0: y0! };
    frames.set(key, frame);
  }
  return frame;
}

/** WGS84 [latitude, longitude] of a point in local meters (x east, y north) from the reference. */
export function localMetersToLatLon(localX: number, localY: number, reference: LatLon): [number, number] {
  const frame = localFrame(reference);
  const [lon, lat] = frame.converter.inverse([frame.x0 + localX, frame.y0 + localY]);
  return [lat!, lon!];
}

/** Local meters from the reference of a WGS84 point; the inverse of `localMetersToLatLon`. */
export function latLonToLocalMeters(latitude: number, longitude: number, reference: LatLon): Point {
  const frame = localFrame(reference);
  const [x, y] = frame.converter.forward([longitude, latitude]);
  return { x: x! - frame.x0, y: y! - frame.y0 };
}

/**
 * The canvas view transform that draws local meters where a map shows them, linearized at
 * the map's center: `project` gives the screen pixel of a latitude and longitude, `center` is
 * the latitude and longitude at the middle of a map of `size`. Exact at the center; over the
 * few kilometers of an encounter the map's scale and the UTM grid's turn change too little to see.
 */
export function mapViewTransform(
  project: (latitude: number, longitude: number) => Point,
  center: { latitude: number; longitude: number },
  size: { width: number; height: number },
  reference: LatLon
): ViewTransform {
  const local = latLonToLocalMeters(center.latitude, center.longitude, reference);
  const step = 100;
  const origin = project(...localMetersToLatLon(local.x, local.y, reference));
  const east = project(...localMetersToLatLon(local.x + step, local.y, reference));
  const dx = east.x - origin.x;
  const dy = east.y - origin.y;
  return {
    center: local,
    scale: Math.hypot(dx, dy) / step,
    rotation: Math.atan2(-dy, dx),
    width: size.width,
    height: size.height,
  };
}
