import { saveBlob } from "../../../components/saveBlob";
import type { SimulationFrame } from "../../../domain/simulation/types";

/** Saves a file (the shared helper: it keeps the URL alive long enough for every browser to start the download). */
export const downloadBlob = saveBlob;

export function exportFramesAsCsv(frames: SimulationFrame[], fileNamePrefix: string) {
  const sorted = [...frames].sort((a, b) => a.timestamp - b.timestamp);
  const rows: string[] = ["timestamp,actorId,x,y,speed,heading"];
  for (const frame of sorted) {
    for (const actor of frame.actors) {
      const state = frame.statesByActorId[actor.id];
      if (!state) continue;
      rows.push(
        [
          frame.timestamp,
          actor.id,
          state.x,
          state.y,
          state.speed,
          state.heading,
        ].join(",")
      );
    }
  }
  downloadBlob(
    new Blob([rows.join("\n")], { type: "text/csv" }),
    `${fileNamePrefix}_${stamp()}.csv`
  );
}

export function exportFramesAsGeoJson(frames: SimulationFrame[], fileNamePrefix: string) {
  const sorted = [...frames].sort((a, b) => a.timestamp - b.timestamp);
  const features: GeoJSON.Feature[] = [];
  for (const frame of sorted) {
    for (const actor of frame.actors) {
      const state = frame.statesByActorId[actor.id];
      if (!state) continue;
      features.push({
        type: "Feature",
        properties: {
          timestamp: frame.timestamp,
          actorId: actor.id,
          actorName: actor.name,
          speed: state.speed,
          heading: state.heading,
        },
        geometry: {
          type: "Point",
          coordinates: [state.x, state.y],
        },
      });
    }
  }
  const collection: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };
  downloadBlob(
    new Blob([JSON.stringify(collection, null, 2)], { type: "application/geo+json" }),
    `${fileNamePrefix}_${stamp()}.geojson`
  );
}

export function captureCanvasScreenshot(canvas: HTMLCanvasElement, fileNamePrefix: string) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    downloadBlob(blob, `${fileNamePrefix}_${stamp()}.png`);
  }, "image/png");
}

/** Replaces each reference to a theme token with its value: an SVG rendered as an image has no stylesheet to read them from. */
export function inlineCssVariables(markup: string, valueOf: (token: string) => string): string {
  return markup.replace(/var\((--[\w-]+)\)/g, (_, token: string) => valueOf(token).trim());
}

/** Rasterizes the encounter canvas's SVG, with the colors of the current theme, and downloads it as PNG. */
export function captureSvgScreenshot(svg: SVGSVGElement, fileNamePrefix: string) {
  const width = svg.width.baseVal.value;
  const height = svg.height.baseVal.value;
  const style = getComputedStyle(svg);
  const markup = inlineCssVariables(new XMLSerializer().serializeToString(svg), (token) => style.getPropertyValue(token));
  const url = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }));
  const image = new Image();
  image.onload = () => {
    const ratio = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    if (context) {
      context.scale(ratio, ratio);
      context.drawImage(image, 0, 0, width, height);
      captureCanvasScreenshot(canvas, fileNamePrefix);
    }
    URL.revokeObjectURL(url);
  };
  image.onerror = () => URL.revokeObjectURL(url);
  image.src = url;
}

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}
