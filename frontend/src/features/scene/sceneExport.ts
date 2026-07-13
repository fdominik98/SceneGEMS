import type { SimulationFrame } from "../../domain/simulation/types";

export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

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

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}
