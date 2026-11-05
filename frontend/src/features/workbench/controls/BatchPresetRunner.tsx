import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import {
  useBatchGenerationStore,
  type BatchRunResult,
} from "../../../domain/sceneGeneration/batchGenerationStore";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { downloadValidBatchScenesZip } from "./batchSceneExport";
import { hiddenSelections, selectListed } from "./scenarioCatalog";

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
  // Selected classes the filters hide still run; the hint says so, so a filter change does not hide them silently
  const hidden = hiddenSelections(selectedClassIds, presets);

  const validResultCount = results.filter(
    (r) => r.status === "success" && r.evaluationData && r.scene
  ).length;

  return (
    <div className="batch-preset-runner batch-preset-runner--tab">
      <div className="batch-preset-runner-body">
        {presets.length === 0 ? (
          <p className="meta">
            No FEC of the master's catalog matches the filters.
            {selected.size > 0 ? ` ${selected.size} selected earlier still run.` : ""}
          </p>
        ) : (
          <>
            <p className="meta">
              Select the FECs to run, then generate their scenes below. Only valid
              scenes are kept. {selected.size} selected
              {hidden > 0 ? `, ${hidden} of them not shown by the filters (they run too)` : ""}.
            </p>
            <div className="toolbar-row batch-preset-toolbar">
              <button
                type="button"
                disabled={running}
                onClick={() => setSelectedClassIds(selectListed(selectedClassIds, presets))}
              >
                Select all shown ({presets.length})
              </button>
              <button
                type="button"
                disabled={running || selected.size === 0}
                onClick={clearSelectedClassIds}
              >
                Clear selection
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
                <div key={preset.fec_id} className="batch-preset-item">
                  <label className="batch-preset-item-label">
                    <input
                      type="checkbox"
                      checked={selected.has(preset.fec_id)}
                      onChange={() => toggleSelectedClassId(preset.fec_id)}
                      disabled={running}
                    />
                    <span>{preset.fec_id}</span>
                  </label>
                  <button
                    type="button"
                    className="batch-preset-refinery-icon-btn"
                    title="Open in Refinery"
                    aria-label={`Open ${preset.fec_id} in Refinery`}
                    onClick={() => onOpenPresetInRefinery(preset.fec_id)}
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
