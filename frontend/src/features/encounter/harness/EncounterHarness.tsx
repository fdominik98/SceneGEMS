/**
 * Screenshot harness for `EncounterView` on recorded frames (`/encounter-harness.html` on the
 * dev server). Query: `case=two|three`, `live=1` replays the frames as if they arrived live,
 * `width=<px>` narrows the host like an embedding section. Not part of the app bundle.
 */
import { useEffect, useMemo, useState } from "react";
import { EncounterView } from "../EncounterView";
import { threeVesselFrames, twoVesselFrames } from "../fixtures/recordedFrames";

const params = new URLSearchParams(window.location.search);
const scenario = params.get("case") === "two" ? "two" : "three";
const live = params.get("live") === "1";
const width = Number(params.get("width")) || null;
const initial = params.get("t") === null ? undefined : Number(params.get("t"));

export function EncounterHarness() {
  const all = useMemo(() => (scenario === "two" ? twoVesselFrames() : threeVesselFrames()), []);
  const [count, setCount] = useState(live ? 12 : all.length);
  const [shownAt, setShownAt] = useState<number | null>(null);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setCount((n) => Math.min(all.length, n + 1)), 700);
    return () => window.clearInterval(id);
  }, [all.length]);

  const frames = useMemo(() => all.slice(0, count), [all, count]);
  return (
    <div style={{ padding: 12, height: "100vh", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 6 }}>
      <p className="meta" style={{ margin: 0 }}>
        Harness: {scenario === "two" ? "two-vessel crossing" : "three vessels"} {live ? "(live replay)" : "(recorded)"}, shown frame{" "}
        {shownAt ?? "-"} s
      </p>
      <div style={{ flex: 1, minHeight: 0, width: width ?? "100%" }}>
        <EncounterView
          frames={frames}
          timeStep={10}
          live={live && count < all.length}
          title={scenario === "two" ? "os and ts1, crossing" : "os, ts1 and ts2"}
          initialTimestamp={initial}
          onTimestampChange={setShownAt}
        />
      </div>
    </div>
  );
}
