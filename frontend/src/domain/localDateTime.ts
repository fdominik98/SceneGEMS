/**
 * The one way the console writes a point in time: `2026-10-26 09:00:05` in the browser's zone, on a
 * 24 hour clock and the same in every locale, so a time reads alike in a table, a select and an entry's name.
 */
export function formatLocalDateTime(at: Date, precision: "second" | "minute" = "second"): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const minute = `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return precision === "minute" ? minute : `${minute}:${pad(at.getSeconds())}`;
}

/** An ISO time written as `formatLocalDateTime` does; the text itself when it is no time, `empty` when there is none. */
export function formatIsoDateTime(iso: string | null | undefined, empty: string, precision: "second" | "minute" = "second"): string {
  if (!iso) {
    return empty;
  }
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : formatLocalDateTime(at, precision);
}
