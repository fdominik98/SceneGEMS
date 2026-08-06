import { useMemo } from "react";
import {
  getCurrentFrame,
  getCurrentSimulationFrame,
  usePlaybackStore,
} from "../../domain/playback/playbackStore";
import { computeScenarioDiff } from "./scenarioDiff";

export function ScenarioDiffPanel() {
  const playbackState = usePlaybackStore();
  const previewFrame = getCurrentFrame(playbackState);
  const simulationFrame = getCurrentSimulationFrame(playbackState);

  const diff = useMemo(
    () => computeScenarioDiff(previewFrame, simulationFrame),
    [previewFrame, simulationFrame]
  );

  if (!previewFrame && !simulationFrame) {
    return (
      <p className="meta scenario-diff-empty">
        Load preview and simulation trajectories to compare streams at the playhead.
      </p>
    );
  }

  return (
    <div className="scenario-diff-panel">
      <h4 className="scenario-diff-title">Preview vs simulation</h4>
      <p className="meta">
        Preview t={diff.previewTimestamp ?? "-"} · Simulation t={diff.simulationTimestamp ?? ":"}
        {diff.ruleMismatchCount > 0 ? ` · ${diff.ruleMismatchCount} rule status mismatch(es)` : ""}
      </p>
      <div className="scenario-diff-table-wrap">
        <table className="scenario-diff-table">
          <thead>
            <tr>
              <th>Actor</th>
              <th>Δ position (m)</th>
              <th>Preview (x, y)</th>
              <th>Simulation (x, y)</th>
            </tr>
          </thead>
          <tbody>
            {diff.actorDeltas.map((row) => (
              <tr key={row.actorId}>
                <td>{row.actorName}</td>
                <td>{row.distanceM !== null ? row.distanceM.toFixed(1) : "-"}</td>
                <td>
                  {row.preview ? `${row.preview.x.toFixed(0)}, ${row.preview.y.toFixed(0)}` : "-"}
                </td>
                <td>
                  {row.simulation
                    ? `${row.simulation.x.toFixed(0)}, ${row.simulation.y.toFixed(0)}`
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
