import type { ActorStaticInfo } from "../../domain/simulation/types";
import type { TrajectoryStream } from "../../app/uiStore";

const SHIP_COLOR_MAP: Record<string, string> = {
  os: "#06b6d4", // color interpretation: blue
  ts1: "#f97316", // color interpretation: orange
  ts2: "#22c55e", // color interpretation: green
  ts3: "#a855f7", // color interpretation: purple
  ts4: "#eab308", // color interpretation: yellow
  ts5: "#ef4444", // color interpretation: red
  ts6: "#3b82f6", // color interpretation: blue
  ts7: "#14b8a6", // color interpretation: teal
  ts8: "#f43f5e", // color interpretation: pink
};

function normalizeShipKey(name: string): string {
  const lower = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (lower.startsWith("os")) {
    return "os";
  }
  const tsMatch = lower.match(/ts(\d+)/);
  if (tsMatch?.[1]) {
    return `ts${tsMatch[1]}`;
  }
  return lower;
}

function fallbackColor(id: string): string {
  const palette = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f87171", "#60a5fa"];
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return palette[hash % palette.length];
}

export function getShipColor(actor: ActorStaticInfo): string {
  if (actor.isOwnShip) {
    return SHIP_COLOR_MAP.os;
  }
  const key = normalizeShipKey(actor.name);
  return SHIP_COLOR_MAP[key] ?? fallbackColor(actor.id);
}

/**
 * Scene-generation coloring: own ship is always OS; targets use TS1..TSn in actor order
 * (matches generated scenes even when loaded files use vessel-type names).
 */
export function buildShipColorsByActorId(actors: ActorStaticInfo[]): Record<string, string> {
  const colors: Record<string, string> = {};
  let targetNumber = 0;

  for (const actor of actors) {
    if (!actor.isVessel) {
      colors[actor.id] = fallbackColor(actor.id);
      continue;
    }

    if (actor.isOwnShip) {
      colors[actor.id] = SHIP_COLOR_MAP.os;
      continue;
    }

    const nameKey = normalizeShipKey(actor.name);
    if (nameKey.startsWith("ts") && SHIP_COLOR_MAP[nameKey]) {
      colors[actor.id] = SHIP_COLOR_MAP[nameKey];
      continue;
    }

    targetNumber += 1;
    colors[actor.id] = SHIP_COLOR_MAP[`ts${targetNumber}`] ?? fallbackColor(actor.id);
  }

  for (const actor of actors) {
    if (!(actor.id in colors)) {
      colors[actor.id] = fallbackColor(actor.id);
    }
  }

  return colors;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = Number.parseInt(full, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function rgbToHex(r: number, g: number, b: number): string {
  const byte = (v: number) =>
    Math.min(255, Math.max(0, Math.round(v)))
      .toString(16)
      .padStart(2, "0");
  return `#${byte(r)}${byte(g)}${byte(b)}`;
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n));
}

function rgbToHsl(r: number, g: number, b: number): { h: number; s: number; l: number } {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) {
    return { h: 0, s: 0, l };
  }
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let hh = 0;
  if (max === rn) {
    hh = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
  } else if (max === gn) {
    hh = ((bn - rn) / d + 2) / 6;
  } else {
    hh = ((rn - gn) / d + 4) / 6;
  }
  return { h: hh * 360, s, l };
}

function hslToRgb(h: number, s: number, l: number): { r: number; g: number; b: number } {
  const hn = (((h % 360) + 360) % 360) / 360;
  const sn = clamp01(s);
  const ln = clamp01(l);
  if (sn === 0) {
    const v = Math.round(ln * 255);
    return { r: v, g: v, b: v };
  }
  const q = ln < 0.5 ? ln * (1 + sn) : ln + sn - ln * sn;
  const p = 2 * ln - q;
  const hue2rgb = (t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  const r = hue2rgb(hn + 1 / 3);
  const g = hue2rgb(hn);
  const b = hue2rgb(hn - 1 / 3);
  return { r: Math.round(r * 255), g: Math.round(g * 255), b: Math.round(b * 255) };
}

/** Same hue as animation; lower lightness so simulation reads as the “darker twin”. */
const SIM_LIGHTNESS_SCALE = 0.64;
const SIM_SATURATION_BOOST = 1.06;

/**
 * Simulation-stream visuals: same family as `getShipColor`, but clearly darker (HSL lightness).
 */
export function getSimulationStreamColor(actor: ActorStaticInfo): string {
  const { r, g, b } = hexToRgb(getShipColor(actor));
  const hsl = rgbToHsl(r, g, b);
  const l = Math.max(0.08, hsl.l * SIM_LIGHTNESS_SCALE);
  const s = hsl.s === 0 ? 0 : Math.min(1, hsl.s * SIM_SATURATION_BOOST);
  const out = hslToRgb(hsl.h, s, l);
  return rgbToHex(out.r, out.g, out.b);
}

/** Right-panel dots: animation = ship colors; simulation = darker same-hue. */
export function getActorPanelDotColor(actor: ActorStaticInfo, panelKind: TrajectoryStream): string {
  return panelKind === "simulation" ? getSimulationStreamColor(actor) : getShipColor(actor);
}
