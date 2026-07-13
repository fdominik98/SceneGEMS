const MARKER_SCALE_FACTOR = 0.15

export function getVesselMarkerScale(length: number, breadth: number, zoomScale: number): [number, number, number] {
  const zoomFactor = 1 / Math.max(zoomScale, 0.01);
  return [
    Math.max(length, length * MARKER_SCALE_FACTOR * zoomFactor) * 0.5,
    Math.max(breadth, breadth * MARKER_SCALE_FACTOR * zoomFactor) * 0.5,
    1,
  ];
}
