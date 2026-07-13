import type { EvaluationData, SimulationFrame } from "../../domain/simulation/types";
import {
  useBatchGenerationStore,
  type BatchRunResult,
} from "../../domain/sceneGeneration/batchGenerationStore";
import type { FunctionalPresetEntry } from "./functionalPresets";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { downloadValidBatchScenesZip } from "./batchSceneExport";

export type { BatchRunResult };

interface BatchPresetRunnerProps {
  presets: FunctionalPresetEntry[];
  /** Preview a generated scene in the canvas (without loading it on the backend). */
  onVisualizeScenario: (evaluationData: EvaluationData, scene: SimulationFrame) => void;
  /** Open a preset's functional spec in Refinery. */
  onOpenPresetInRefinery: (path: string) => void;
  /** Scene currently visualized in the canvas, used to highlight the active result. */
  activeScene: SimulationFrame | null;
}

export function BatchPresetRunner({
  presets,
  onVisualizeScenario,
  onOpenPresetInRefinery,
  activeScene,
}: BatchPresetRunnerProps) {
  const results = useBatchGenerationStore((s) => s.results);
  const selectedPaths = useBatchGenerationStore((s) => s.selectedPaths);
  const running = useBatchGenerationStore((s) => s.running);
  const toggleSelectedPath = useBatchGenerationStore((s) => s.toggleSelectedPath);
  const selectAllPaths = useBatchGenerationStore((s) => s.selectAllPaths);
  const clearSelectedPaths = useBatchGenerationStore((s) => s.clearSelectedPaths);

  const selected = new Set(selectedPaths);

  const validResultCount = results.filter(
    (r) => r.status === "success" && r.evaluationData && r.scene
  ).length;

  return (
    <div className="batch-preset-runner batch-preset-runner--tab">
      <div className="batch-preset-runner-body">
        {presets.length === 0 ? (
          <p className="meta">No functional presets available for batch generation.</p>
        ) : (
          <>
            <p className="meta">
              Select presets to queue, then use “Generate Initial Scenes” below. Only valid scenes
              are kept. {selected.size} selected.
            </p>
            <div className="toolbar-row batch-preset-toolbar">
              <button
                type="button"
                disabled={running}
                onClick={() => selectAllPaths(presets.map((p) => p.path))}
              >
                Select all ({presets.length})
              </button>
              <button
                type="button"
                disabled={running || selected.size === 0}
                onClick={clearSelectedPaths}
              >
                Clear
              </button>
              <button
                type="button"
                disabled={validResultCount === 0}
                onClick={() => void downloadValidBatchScenesZip(results)}
              >
                Export all valid ({validResultCount})
              </button>
            </div>
            <div className="batch-preset-list">
              {presets.map((preset) => (
                <div key={preset.path} className="batch-preset-item">
                  <label className="batch-preset-item-label">
                    <input
                      type="checkbox"
                      checked={selected.has(preset.path)}
                      onChange={() => toggleSelectedPath(preset.path)}
                      disabled={running}
                    />
                    <span>{preset.label}</span>
                  </label>
                  <button
                    type="button"
                    className="batch-preset-refinery-icon-btn"
                    title="Open in Refinery"
                    aria-label={`Open ${preset.label} in Refinery`}
                    onClick={() => onOpenPresetInRefinery(preset.path)}
                  >
                    <img src="/refinery-icon.svg" alt="" width={14} height={14} />
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
        {running && <LoadingSpinner label="Running batch…" size="sm" />}
        {results.length > 0 && (
          <div
            className="batch-preset-results-scroll"
            role="region"
            aria-label="Batch generation results"
          >
            <ul className="batch-preset-results">
              {results.map((r) => {
                const isSuccess = r.status === "success" && !!r.evaluationData && !!r.scene;
                const isActive = isSuccess && r.scene === activeScene;
                const visualize = isSuccess
                  ? () => onVisualizeScenario(r.evaluationData!, r.scene!)
                  : undefined;
                return (
                  <li
                    key={r.requestId}
                    className={`batch-result batch-result--${r.status}${
                      isSuccess ? " batch-result--clickable" : ""
                    }${isActive ? " batch-result--active" : ""}`}
                    role={isSuccess ? "button" : undefined}
                    tabIndex={isSuccess ? 0 : undefined}
                    title={isSuccess ? "Click to visualize this scene" : undefined}
                    onClick={visualize}
                    onKeyDown={
                      visualize
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              visualize();
                            }
                          }
                        : undefined
                    }
                  >
                    <div className="batch-result-main">
                      <span>{r.label}</span>
                      <span>
                        {r.status}
                        {isActive ? " · visualized" : ""}
                      </span>
                      {r.message && r.status !== "timeout" ? (
                        <span className="meta">{r.message}</span>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
