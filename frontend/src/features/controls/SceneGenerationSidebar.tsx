import CodeMirror from "@uiw/react-codemirror";
import { syntaxHighlighting } from "@codemirror/language";
import { oneDarkTheme } from "@codemirror/theme-one-dark";
import { classHighlighter } from "@lezer/highlight";
import { EditorView } from "@codemirror/view";
import { useEffect, useMemo, useRef, useState } from "react";
import { useUiStore } from "../../app/uiStore";
import problemLanguageSupport from "../../language/refineryProblem/problemLanguageSupport";
import { formatFunctionalPresetLabel } from "./functionalPresetPaths";
import {
  filterPresets,
  loadFunctionalPresetsManifest,
  type FunctionalPresetEntry,
} from "./functionalPresets";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { BatchPresetRunner } from "./BatchPresetRunner";
import type { EvaluationData, SimulationFrame } from "../../domain/simulation/types";

const refineryLikeContentAttributes = EditorView.contentAttributes.of({
  spellcheck: "false",
  autocorrect: "off",
  autocapitalize: "off",
  translate: "no",
  writingsuggestions: "false",
});

const functionalSpecProblemExtensions = [
  problemLanguageSupport(),
  syntaxHighlighting(classHighlighter),
  oneDarkTheme,
  refineryLikeContentAttributes,
  EditorView.theme(
    {
      "&": { backgroundColor: "#020617" },
      ".cm-gutters": { backgroundColor: "#020617", borderColor: "#334155", color: "#64748b" },
      ".cm-activeLineGutter": { backgroundColor: "transparent" },
      ".cm-content": { tabSize: 4 },
    },
    { dark: true }
  ),
];

function primaryModifierLabel(): string {
  if (typeof navigator === "undefined") {
    return "Ctrl";
  }
  return /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent) ? "⌘" : "Ctrl";
}

const PRESETS_PAGE_SIZE = 40;

interface Props {
  functionalSpecText: string;
  onFunctionalSpecTextChange: (value: string) => void;
  onLoadFunctionalSpecFromPreset: (path: string) => void;
  onLoadFunctionalSpecFromFile: (file: File) => void;
  onExportFunctionalSpec: () => void;
  isSceneGenerationBusy?: boolean;
  /** Preview a generated scene in the canvas (without loading it on the backend). */
  onVisualizeFromEvaluation?: (evaluationData: EvaluationData, scene: SimulationFrame) => void;
  /** Scene currently visualized in the canvas, used to highlight the active batch result. */
  activeScene?: SimulationFrame | null;
}

export function SceneGenerationSidebar({
  functionalSpecText,
  onFunctionalSpecTextChange,
  onLoadFunctionalSpecFromPreset,
  onLoadFunctionalSpecFromFile,
  onExportFunctionalSpec,
  isSceneGenerationBusy = false,
  onVisualizeFromEvaluation,
  activeScene = null,
}: Props) {
  const functionalSpecInputRef = useRef<HTMLInputElement | null>(null);
  const isFunctionalDirty = useMemo(
    () => functionalSpecText.trim().length > 0,
    [functionalSpecText]
  );
  const tab = useUiStore((s) => s.sceneGenerationTab);
  const setTab = useUiStore((s) => s.setSceneGenerationTab);
  const [refineryPasteHintOpen, setRefineryPasteHintOpen] = useState(false);
  const [allPresets, setAllPresets] = useState<FunctionalPresetEntry[]>([]);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [manifestLoading, setManifestLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [vesselFilter, setVesselFilter] = useState("any");
  const [obstacleFilter, setObstacleFilter] = useState("any");
  const [page, setPage] = useState(0);
  const mod = primaryModifierLabel();

  useEffect(() => {
    void (async () => {
      setManifestLoading(true);
      try {
        const manifest = await loadFunctionalPresetsManifest();
        setAllPresets(manifest.presets);
        setManifestError(null);
      } catch (error) {
        setManifestError(
          error instanceof Error ? error.message : "Failed to load functional presets manifest."
        );
      } finally {
        setManifestLoading(false);
      }
    })();
  }, []);

  const filteredPresets = useMemo(
    () => filterPresets(allPresets, searchQuery, vesselFilter, obstacleFilter),
    [allPresets, searchQuery, vesselFilter, obstacleFilter]
  );

  const vesselOptions = useMemo(() => {
    const counts = new Set<number>();
    for (const p of allPresets) {
      if (p.vesselCount !== null) counts.add(p.vesselCount);
    }
    return Array.from(counts).sort((a, b) => a - b);
  }, [allPresets]);

  const obstacleOptions = useMemo(() => {
    const counts = new Set<number>();
    for (const p of allPresets) {
      if (p.obstacleCount !== null) counts.add(p.obstacleCount);
    }
    return Array.from(counts).sort((a, b) => a - b);
  }, [allPresets]);

  const pageCount = Math.max(1, Math.ceil(filteredPresets.length / PRESETS_PAGE_SIZE));
  const pagePresets = filteredPresets.slice(
    page * PRESETS_PAGE_SIZE,
    (page + 1) * PRESETS_PAGE_SIZE
  );

  useEffect(() => {
    setPage(0);
  }, [searchQuery, vesselFilter, obstacleFilter]);

  const loadPresetText = async (path: string) => {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`Failed to load ${path}`);
    }
    return response.text();
  };

  const openInRefinery = async (text: string) => {
    const trimmedText = text.trim();
    if (!trimmedText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Opening the editor is still useful even if clipboard access is blocked.
    }
    window.open("https://refinery.services/", "_blank", "noopener,noreferrer");
    setRefineryPasteHintOpen(true);
  };

  const openPresetInRefinery = (path: string) => {
    void (async () => {
      try {
        await openInRefinery(await loadPresetText(path));
      } catch {
        // Ignore failures to load the preset for Refinery hand-off.
      }
    })();
  };

  const batchEnabled = Boolean(onVisualizeFromEvaluation);

  return (
    <aside className="right-pane scene-generation-sidebar">
      <div className="scene-editor-panel">
        <h3>Functional Scenario Specification (.problem)</h3>
        {manifestLoading && <LoadingSpinner label="Loading preset catalog…" size="sm" />}
        {manifestError && <p className="error">{manifestError}</p>}
        <div className="preset-filters toolbar-row">
          <input
            type="search"
            placeholder="Search presets…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search functional presets"
          />
          <select
            value={vesselFilter}
            onChange={(e) => setVesselFilter(e.target.value)}
            aria-label="Filter by vessel count"
          >
            <option value="any">Any vessels</option>
            {vesselOptions.map((n) => (
              <option key={n} value={String(n)}>
                {n} vessels
              </option>
            ))}
          </select>
          <select
            value={obstacleFilter}
            onChange={(e) => setObstacleFilter(e.target.value)}
            aria-label="Filter by obstacle count"
          >
            <option value="any">Any obstacles</option>
            {obstacleOptions.map((n) => (
              <option key={n} value={String(n)}>
                {n} obstacles
              </option>
            ))}
          </select>
        </div>
        <p className="meta">
          {filteredPresets.length} preset(s)
          {tab === "single" && filteredPresets.length > PRESETS_PAGE_SIZE
            ? ` · page ${page + 1} / ${pageCount}`
            : ""}
        </p>

        <div className="scene-gen-tabs" role="tablist" aria-label="Scene generation mode">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "single"}
            className={`scene-gen-tab${tab === "single" ? " active" : ""}`}
            onClick={() => setTab("single")}
          >
            Single scene generation
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "batch"}
            className={`scene-gen-tab${tab === "batch" ? " active" : ""}`}
            onClick={() => setTab("batch")}
            disabled={!batchEnabled}
          >
            Batch scene generation
          </button>
        </div>

        {tab === "single" ? (
          <>
            <div className="toolbar-row">
              <select
                onChange={(event) => {
                  const path = event.target.value;
                  if (path) {
                    onLoadFunctionalSpecFromPreset(path);
                  }
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  Load preset…
                </option>
                {pagePresets.map((preset) => (
                  <option key={preset.path} value={preset.path}>
                    {formatFunctionalPresetLabel(preset.path)}
                  </option>
                ))}
              </select>
              {pageCount > 1 && (
                <>
                  <button
                    type="button"
                    disabled={page <= 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={page >= pageCount - 1}
                    onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                  >
                    Next
                  </button>
                </>
              )}
              <input
                ref={functionalSpecInputRef}
                hidden
                type="file"
                accept=".problem,text/plain"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    onLoadFunctionalSpecFromFile(file);
                  }
                  event.target.value = "";
                }}
              />
              <button type="button" onClick={() => functionalSpecInputRef.current?.click()}>
                Load from computer
              </button>
              <button
                type="button"
                onClick={onExportFunctionalSpec}
                disabled={!isFunctionalDirty || isSceneGenerationBusy}
              >
                Export
              </button>
              <button
                type="button"
                className="open-in-refinery-btn"
                onClick={() => void openInRefinery(functionalSpecText)}
                disabled={!isFunctionalDirty}
              >
                <img
                  src="/refinery-icon.svg"
                  alt=""
                  width={16}
                  height={16}
                  className="open-in-refinery-btn-icon"
                />
                Open in Refinery
              </button>
            </div>
            {refineryPasteHintOpen && (
              <div className="refinery-paste-hint" role="status">
                <p>
                  Refinery opened in a new tab. Your spec is on the clipboard. There: click inside
                  the text editor area, clear it (<kbd>{mod}</kbd>+<kbd>A</kbd>), then paste (
                  <kbd>{mod}</kbd>+<kbd>V</kbd>).&nbsp;&nbsp;
                  <button
                    type="button"
                    className="refinery-paste-hint-dismiss"
                    onClick={() => setRefineryPasteHintOpen(false)}
                  >
                    Dismiss
                  </button>
                </p>
              </div>
            )}
            <CodeMirror
              className="scene-editor-problem-codemirror"
              value={functionalSpecText}
              height="100%"
              theme="none"
              extensions={functionalSpecProblemExtensions}
              onChange={onFunctionalSpecTextChange}
            />
          </>
        ) : (
          <>
            {refineryPasteHintOpen && (
              <div className="refinery-paste-hint" role="status">
                <p>
                  Refinery opened in a new tab. The preset spec is on the clipboard. There: click
                  inside the text editor area, clear it (<kbd>{mod}</kbd>+<kbd>A</kbd>), then paste (
                  <kbd>{mod}</kbd>+<kbd>V</kbd>).&nbsp;&nbsp;
                  <button
                    type="button"
                    className="refinery-paste-hint-dismiss"
                    onClick={() => setRefineryPasteHintOpen(false)}
                  >
                    Dismiss
                  </button>
                </p>
              </div>
            )}
            {batchEnabled && (
              <BatchPresetRunner
                presets={filteredPresets}
                onVisualizeScenario={onVisualizeFromEvaluation!}
                onOpenPresetInRefinery={openPresetInRefinery}
                activeScene={activeScene}
              />
            )}
          </>
        )}
      </div>
    </aside>
  );
}
