import CodeMirror from "@uiw/react-codemirror";
import { syntaxHighlighting } from "@codemirror/language";
import { oneDarkTheme } from "@codemirror/theme-one-dark";
import { classHighlighter } from "@lezer/highlight";
import { EditorView } from "@codemirror/view";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePersistedState } from "../../../app/usePersistedState";
import { useUiStore } from "../../../app/uiStore";
import problemLanguageSupport from "../../../language/refineryProblem/problemLanguageSupport";
import { useCatalogClasses } from "../../campaigns/useCampaignData";
import { ANY_COUNT, countOptions, filterCatalogClasses } from "./scenarioCatalog";
import { Disclosure } from "../../../components/Disclosure";
import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { BatchPresetRunner } from "./BatchPresetRunner";
import { SceneGenerationPaneViewSelect } from "./SceneGenerationPaneViewSelect";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";

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
  /** Loads a functional scenario of the master's catalog into the editor, by class id. */
  onLoadFunctionalSpecFromPreset: (classId: string) => void;
  /** The functional scenario of a class of the master's catalog. */
  loadScenarioText: (classId: string) => Promise<string>;
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
  loadScenarioText,
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
  // The functional scenarios come from the master's class catalog: the presets every cluster offers.
  const catalog = useCatalogClasses();
  const allPresets = useMemo(() => catalog.data?.items ?? [], [catalog.data]);
  const manifestLoading = catalog.isLoading;
  const manifestError = catalog.isError ? `The master's functional scenarios could not be read: ${catalog.error instanceof Error ? catalog.error.message : String(catalog.error)}` : null;
  const [searchQuery, setSearchQuery] = usePersistedState(
    "scene-generation-preset-search",
    ""
  );
  const [vesselFilter, setVesselFilter] = usePersistedState(
    "scene-generation-vessel-filter",
    ANY_COUNT
  );
  const [obstacleFilter, setObstacleFilter] = usePersistedState(
    "scene-generation-obstacle-filter",
    ANY_COUNT
  );
  const [page, setPage] = useState(0);
  const mod = primaryModifierLabel();

  const filteredPresets = useMemo(
    () => filterCatalogClasses(allPresets, searchQuery, vesselFilter, obstacleFilter),
    [allPresets, searchQuery, vesselFilter, obstacleFilter]
  );

  const vesselOptions = useMemo(() => countOptions(allPresets, "vessel_count"), [allPresets]);
  const obstacleOptions = useMemo(() => countOptions(allPresets, "obstacle_count"), [allPresets]);

  useEffect(() => {
    if (manifestLoading || allPresets.length === 0) {
      return;
    }
    if (vesselFilter !== ANY_COUNT && !vesselOptions.includes(Number(vesselFilter))) {
      setVesselFilter(ANY_COUNT);
    }
    if (obstacleFilter !== ANY_COUNT && !obstacleOptions.includes(Number(obstacleFilter))) {
      setObstacleFilter(ANY_COUNT);
    }
  }, [
    manifestLoading,
    allPresets.length,
    vesselFilter,
    obstacleFilter,
    vesselOptions,
    obstacleOptions,
    setVesselFilter,
    setObstacleFilter,
  ]);

  const pageCount = Math.max(1, Math.ceil(filteredPresets.length / PRESETS_PAGE_SIZE));
  // A filter that matches fewer presets may leave the remembered page past the end
  const shownPage = Math.min(page, pageCount - 1);
  const pagePresets = filteredPresets.slice(
    shownPage * PRESETS_PAGE_SIZE,
    (shownPage + 1) * PRESETS_PAGE_SIZE
  );


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

  const openPresetInRefinery = (classId: string) => {
    void (async () => {
      try {
        await openInRefinery(await loadScenarioText(classId));
      } catch {
        // Ignore failures to load the preset for Refinery hand-off.
      }
    })();
  };

  const batchEnabled = Boolean(onVisualizeFromEvaluation);

  return (
    <aside className="right-pane scene-generation-sidebar">
      <SceneGenerationPaneViewSelect />
      <div className="scene-editor-panel">
        {manifestLoading && <LoadingSpinner label="Loading the master's functional scenarios…" size="sm" />}
        {manifestError && <p className="error">{manifestError}</p>}
        <Disclosure
          id="scene-gen:find-preset"
          variant="plain"
          headingLevel={4}
          title="Find a preset"
          hint={
            searchQuery || vesselFilter !== ANY_COUNT || obstacleFilter !== ANY_COUNT
              ? `${filteredPresets.length} of ${allPresets.length} match`
              : `${allPresets.length} presets`
          }
        >
          <div className="preset-filters toolbar-row">
            <input
              type="search"
              placeholder="Search presets…"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(0);
              }}
              aria-label="Search functional presets"
            />
            <select
              value={vesselFilter}
              onChange={(e) => {
                setVesselFilter(e.target.value);
                setPage(0);
              }}
              aria-label="Filter by vessel count"
            >
              <option value={ANY_COUNT}>Any vessels</option>
              {vesselOptions.map((n) => (
                <option key={n} value={String(n)}>
                  {n} vessels
                </option>
              ))}
            </select>
            <select
              value={obstacleFilter}
              onChange={(e) => {
                setObstacleFilter(e.target.value);
                setPage(0);
              }}
              aria-label="Filter by obstacle count"
            >
              <option value={ANY_COUNT}>Any obstacles</option>
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
              ? ` · page ${shownPage + 1} / ${pageCount}`
              : ""}
          </p>
        </Disclosure>

        <div className="scene-gen-tabs" role="tablist" aria-label="Scene generation mode">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "single"}
            className={`scene-gen-tab${tab === "single" ? " active" : ""}`}
            onClick={() => setTab("single")}
          >
            Single scene
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "batch"}
            className={`scene-gen-tab${tab === "batch" ? " active" : ""}`}
            onClick={() => setTab("batch")}
            disabled={!batchEnabled}
          >
            Batch (several presets)
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
                  <option key={preset.class_id} value={preset.class_id}>
                    {preset.class_id}
                  </option>
                ))}
              </select>
              {pageCount > 1 && (
                <>
                  <button
                    type="button"
                    disabled={shownPage <= 0}
                    onClick={() => setPage(Math.max(0, shownPage - 1))}
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={shownPage >= pageCount - 1}
                    onClick={() => setPage(Math.min(pageCount - 1, shownPage + 1))}
                  >
                    Next
                  </button>
                </>
              )}
            </div>
            <Disclosure
              id="scene-gen:file-tools"
              variant="link"
              headingLevel={null}
              title="Files and editor tools"
              openTitle="Hide files and editor tools"
              keepMounted
            >
              <div className="toolbar-row">
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
            </Disclosure>
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
