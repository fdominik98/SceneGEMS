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

export function formatAxisTick(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) {
    return "—";
  }
  if (Math.abs(value) >= 1e5 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) {
    return value.toExponential(1);
  }
  if (Number.isInteger(value) && Math.abs(value) < 1e4) {
    return String(value);
  }
  const fixed = value.toFixed(decimals).replace(/\.?0+$/, "");
  return fixed === "-0" ? "0" : fixed;
}
