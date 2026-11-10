import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import { downloadValidBatchScenesZip } from "./batchSceneExport";

interface Props {
  /** Shows a generated scene on the canvas. */
  onVisualizeScenario: (evaluationData: EvaluationData, scene: SimulationFrame) => void;
  /** The scene on the canvas, to mark its row. */
  activeScene: SimulationFrame | null;
}

/**
 * The results of the latest batch, a row per FEC with its status: a valid scene opens on the canvas
 * (its row stays marked), and every valid scene exports as one ZIP. They stay after the run, also
 * when the selection changes, until the next batch replaces them.
 */
export function SceneBatchResults({ onVisualizeScenario, activeScene }: Props) {
  const results = useBatchGenerationStore((s) => s.results);
  const running = useBatchGenerationStore((s) => s.running);
  if (results.length === 0 && !running) {
    return null;
  }
  const valid = results.filter((row) => row.status === "success" && row.evaluationData && row.scene).length;
  return (
    <div className="scene-batch-results">
      <div className="toolbar-row scene-batch-results-head">
        <h4 className="scene-pane-heading">Batch results</h4>
        {running ? <LoadingSpinner label="Running batch…" size="sm" /> : null}
        <button type="button" disabled={valid === 0} onClick={() => void downloadValidBatchScenesZip(results)}>
          Export all valid ({valid})
        </button>
      </div>
      {results.length > 0 ? (
        <div className="batch-preset-results-scroll" role="region" aria-label="Batch generation results">
          <ul className="batch-preset-results">
            {results.map((row) => {
              const success = row.status === "success" && !!row.evaluationData && !!row.scene;
              const active = success && row.scene === activeScene;
              const visualize = success ? () => onVisualizeScenario(row.evaluationData!, row.scene!) : undefined;
              return (
                <li
                  key={row.requestId}
                  className={`batch-result batch-result--${row.status}${success ? " batch-result--clickable" : ""}${active ? " batch-result--active" : ""}`}
                  role={success ? "button" : undefined}
                  tabIndex={success ? 0 : undefined}
                  title={success ? "Click to visualize this scene" : undefined}
                  onClick={visualize}
                  onKeyDown={
                    visualize
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            visualize();
                          }
                        }
                      : undefined
                  }
                >
                  <div className="batch-result-main">
                    <span>{row.label}</span>
                    <span>
                      {row.status}
                      {active ? " · visualized" : ""}
                    </span>
                    {row.message && row.status !== "timeout" ? <span className="meta">{row.message}</span> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
