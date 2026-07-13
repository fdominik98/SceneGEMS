/** Circular reference geofence: one point on the WGS84 ellipsoid and radius in meters. */
export interface ReferenceGeofence {
  latitude: number;
  longitude: number;
  /** Horizontal radius in meters (great-circle distance on the sphere Leaflet uses). */
  radius_meters: number;
}

export const defaultReferenceGeofence: ReferenceGeofence = {
  // Center: 57°45'39.73"N, 16°40'49.14"E
  latitude: 57.76080082972655,
  longitude: 16.680965995056,
  radius_meters: 20,
};

export function getGeofenceMapCenter(geofence: ReferenceGeofence): [number, number] {
  return [geofence.latitude, geofence.longitude];
}
