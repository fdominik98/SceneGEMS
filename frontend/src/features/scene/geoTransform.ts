import proj4 from "proj4";

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

export function localMetersToLatLon(
  localX: number,
  localY: number,
  reference: LatLon
): [number, number] {
  const utmProj = getUtmProjString(reference.latitude, reference.longitude);
  const toUtm = proj4("EPSG:4326", utmProj);
  const toWgs84 = proj4(utmProj, "EPSG:4326");
  const [x0, y0] = toUtm.forward([reference.longitude, reference.latitude]);
  const [lon, lat] = toWgs84.forward([x0 + localX, y0 + localY]);
  return [lat, lon];
}
