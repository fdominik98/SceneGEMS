export interface NiceScale {
  min: number;
  max: number;
  ticks: number[];
}

function niceStep(range: number, targetTicks: number): number {
  if (!Number.isFinite(range) || range <= 0) {
    return 1;
  }
  const rough = range / Math.max(1, targetTicks);
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const fraction = rough / magnitude;
  let niceFraction: number;
  if (fraction <= 1.5) {
    niceFraction = 1;
  } else if (fraction <= 3) {
    niceFraction = 2;
  } else if (fraction <= 7) {
    niceFraction = 5;
  } else {
    niceFraction = 10;
  }
  return niceFraction * magnitude;
}

export function buildNiceScale(
  rawMin: number,
  rawMax: number,
  targetTicks = 5
): NiceScale {
  let min = rawMin;
  let max = rawMax;

  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, max: 1, ticks: [0, 0.5, 1] };
  }

  if (min === max) {
    const pad = min === 0 ? 1 : Math.abs(min) * 0.15;
    min -= pad;
    max += pad;
  }

  const step = niceStep(max - min, targetTicks);
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = niceMin; value <= niceMax + step * 0.001; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return { min: niceMin, max: niceMax, ticks };
}

/** Decimals that tell the ticks of a scale apart: none for a step of 1 or more, one for 0.5, two for 0.05. */
export function tickDecimals(ticks: number[]): number {
  const step = ticks.length > 1 ? Math.abs(ticks[1]! - ticks[0]!) : 1;
  if (!Number.isFinite(step) || step <= 0 || step >= 1) {
    return 0;
  }
  return Math.min(6, Math.ceil(-Math.log10(step) - 1e-9));
}

/** Time steps a time axis may use, in seconds: whole seconds, then minutes, then hours. */
const TIME_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];

/**
 * Ticks for a time axis from `min` to `max` seconds: about `targetTicks` of them on whole
 * seconds, minutes or hours, so they read as clock times. The domain stays as given.
 */
export function buildTimeScale(min: number, max: number, targetTicks = 5): NiceScale {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    const at = Number.isFinite(min) ? min : 0;
    return { min: at, max: at + 1, ticks: [at] };
  }
  const rough = (max - min) / Math.max(1, targetTicks);
  const step = TIME_STEPS.find((candidate) => candidate >= rough) ?? Math.ceil(rough / 3600) * 3600;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-6; value += step) {
    ticks.push(value);
  }
  return { min, max, ticks };
}

export function formatAxisTick(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) >= 1e5 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) {
    return value.toExponential(1);
  }
  if (Number.isInteger(value) && Math.abs(value) < 1e4) {
    return String(value);
  }
  const fixed = value.toFixed(decimals);
  // Only a fraction's trailing zeros go: 20000 stays 20000.
  const trimmed = fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed;
  return trimmed === "-0" ? "0" : trimmed;
}

/** An axis tick in few characters: 20000 is "20k", so the axis keeps its width. */
export function formatCompactTick(value: number, decimals = 0): string {
  if (Number.isFinite(value) && Math.abs(value) >= 10000) {
    return `${formatAxisTick(value / 1000, Math.max(0, decimals - 3))}k`;
  }
  return formatAxisTick(value, decimals);
}
