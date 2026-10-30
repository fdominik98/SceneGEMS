import { describe, expect, it } from "vitest";
import { worldToScreen, type Point } from "./encounterGeometry";
import { latLonToLocalMeters, localMetersToLatLon, mapViewTransform } from "./geoTransform";

// The workbench's default reference geofence (Västervik, UTM zone 33 north).
const REFERENCE = { latitude: 57.76080082972655, longitude: 16.680965995056 };
const METERS_PER_DEGREE_LAT = 111_320;

describe("localMetersToLatLon and latLonToLocalMeters", () => {
  it("puts the origin on the reference point", () => {
    const [latitude, longitude] = localMetersToLatLon(0, 0, REFERENCE);
    expect(latitude).toBeCloseTo(REFERENCE.latitude, 9);
    expect(longitude).toBeCloseTo(REFERENCE.longitude, 9);
  });

  it("goes north with y and east with x", () => {
    const [northLat, northLon] = localMetersToLatLon(0, 1000, REFERENCE);
    const [eastLat, eastLon] = localMetersToLatLon(1000, 0, REFERENCE);
    expect((northLat - REFERENCE.latitude) * METERS_PER_DEGREE_LAT).toBeCloseTo(1000, -1);
    expect(Math.abs(northLon - REFERENCE.longitude)).toBeLessThan(0.001);
    expect(eastLon).toBeGreaterThan(REFERENCE.longitude);
    expect(Math.abs(eastLat - REFERENCE.latitude)).toBeLessThan(0.001);
  });

  it("round-trips a point", () => {
    const [latitude, longitude] = localMetersToLatLon(-2345.6, 789.1, REFERENCE);
    const back = latLonToLocalMeters(latitude, longitude, REFERENCE);
    expect(back.x).toBeCloseTo(-2345.6, 4);
    expect(back.y).toBeCloseTo(789.1, 4);
  });

  it("keeps a frame per reference point", () => {
    const other = { latitude: -33.86, longitude: 151.21 };
    const [latitude, longitude] = localMetersToLatLon(500, -500, other);
    expect(latitude).toBeLessThan(other.latitude);
    expect(longitude).toBeGreaterThan(other.longitude);
    expect(localMetersToLatLon(0, 0, REFERENCE)[0]).toBeCloseTo(REFERENCE.latitude, 9);
  });
});

describe("mapViewTransform", () => {
  // Web Mercator in pixels, as Leaflet projects at some zoom, with the map centered on `center`.
  function mercator(center: { latitude: number; longitude: number }, size: { width: number; height: number }, zoom: number) {
    const worldPx = 256 * 2 ** zoom;
    const project = (latitude: number, longitude: number): Point => {
      const x = ((longitude + 180) / 360) * worldPx;
      const sin = Math.sin((latitude * Math.PI) / 180);
      const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * worldPx;
      return { x, y };
    };
    const c = project(center.latitude, center.longitude);
    return (latitude: number, longitude: number): Point => {
      const p = project(latitude, longitude);
      return { x: p.x - c.x + size.width / 2, y: p.y - c.y + size.height / 2 };
    };
  }

  const size = { width: 900, height: 500 };
  const [centerLat, centerLon] = localMetersToLatLon(800, -300, REFERENCE);
  const center = { latitude: centerLat, longitude: centerLon };
  const project = mercator(center, size, 15);
  const view = mapViewTransform(project, center, size, REFERENCE);

  it("centers the view on the local point at the middle of the map", () => {
    expect(view.center.x).toBeCloseTo(800, 3);
    expect(view.center.y).toBeCloseTo(-300, 3);
    expect(view.width).toBe(900);
    expect(view.height).toBe(500);
  });

  // At zoom 15 a pixel is about 2.5 m; the linearization drifts about 3 m 2.3 km from the center.
  it("draws local points where the map shows them, within a pixel and a half over the encounter", () => {
    for (const local of [
      { x: 800, y: -300 },
      { x: -1200, y: 900 },
      { x: 2500, y: -1800 },
    ]) {
      const drawn = worldToScreen(view, local);
      const shown = project(...localMetersToLatLon(local.x, local.y, REFERENCE));
      expect(Math.abs(drawn.x - shown.x)).toBeLessThan(1.5);
      expect(Math.abs(drawn.y - shown.y)).toBeLessThan(1.5);
    }
  });

  it("turns the UTM grid by its convergence east of the central meridian", () => {
    // Zone 33's central meridian is 15 E; at 16.68 E, 57.76 N the grid's north lies about 1.4 degrees east of
    // true north, so on a north-up map the drawing turns that much clockwise.
    expect((view.rotation * 180) / Math.PI).toBeCloseTo(-1.42, 1);
  });
});
