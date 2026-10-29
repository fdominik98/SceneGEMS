import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import {
  useBatchGenerationStore,
  type BatchRunResult,
} from "../../../domain/sceneGeneration/batchGenerationStore";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { downloadValidBatchScenesZip } from "./batchSceneExport";

export type { BatchRunResult };

interface BatchPresetRunnerProps {
  /** The functional scenarios of the master's catalog that the filters match. */
  presets: CatalogClass[];
  /** Preview a generated scene in the canvas (without loading it on the backend). */
  onVisualizeScenario: (evaluationData: EvaluationData, scene: SimulationFrame) => void;
  /** Open a class's functional scenario in Refinery. */
  onOpenPresetInRefinery: (classId: string) => void;
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
  const selectedClassIds = useBatchGenerationStore((s) => s.selectedClassIds);
  const running = useBatchGenerationStore((s) => s.running);
  const toggleSelectedClassId = useBatchGenerationStore((s) => s.toggleSelectedClassId);
  const setSelectedClassIds = useBatchGenerationStore((s) => s.setSelectedClassIds);
  const clearSelectedClassIds = useBatchGenerationStore((s) => s.clearSelectedClassIds);

  const selected = new Set(selectedClassIds);

  const validResultCount = results.filter(
    (r) => r.status === "success" && r.evaluationData && r.scene
  ).length;

  return (
    <div className="batch-preset-runner batch-preset-runner--tab">
      <div className="batch-preset-runner-body">
        {presets.length === 0 ? (
          <p className="meta">The master offers no functional scenarios that match the filters.</p>
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
                onClick={() => setSelectedClassIds(presets.map((p) => p.class_id))}
              >
                Select all ({presets.length})
              </button>
              <button
                type="button"
                disabled={running || selected.size === 0}
                onClick={clearSelectedClassIds}
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
                <div key={preset.class_id} className="batch-preset-item">
                  <label className="batch-preset-item-label">
                    <input
                      type="checkbox"
                      checked={selected.has(preset.class_id)}
                      onChange={() => toggleSelectedClassId(preset.class_id)}
                      disabled={running}
                    />
                    <span>{preset.class_id}</span>
                  </label>
                  <button
                    type="button"
                    className="batch-preset-refinery-icon-btn"
                    title="Open in Refinery"
                    aria-label={`Open ${preset.class_id} in Refinery`}
                    onClick={() => onOpenPresetInRefinery(preset.class_id)}
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
