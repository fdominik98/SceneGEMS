import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePersistedState } from "../../../app/usePersistedState";
import { Disclosure } from "../../../components/Disclosure";
import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { sceneSelectionMode, useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import { useCatalogClasses } from "../../campaigns/useCampaignData";
import { ModelGraph } from "../designSpace/graphs/ModelGraph";
import { useTextOrGraph } from "../designSpace/graphs/textOrGraph";
import { useDebouncedValue } from "../designSpace/graphs/useDebouncedValue";
import { ViewSwitch } from "../designSpace/graphs/ViewSwitch";
import { CatalogFecList } from "./CatalogFecList";
import { loadCatalogTexts, useCatalogTexts } from "./catalogTexts";
import { ProblemEditor } from "./ProblemEditor";
import { ANY_COUNT, countOptions, filterCatalogClasses, hiddenSelections, selectListed } from "./scenarioCatalog";
import { SceneBatchResults } from "./SceneBatchResults";
import { SceneGenerationPaneViewSelect } from "./SceneGenerationPaneViewSelect";
import { copyLabel } from "./sceneSelection";
import "./sceneFecPicker.css";

/** Persisted keys (with the `scenegems:` prefix) of the pane's two Graph and Text switches. */
export const SCENE_EDITOR_VIEW_KEY = "scene-generation-editor-view";
export const SCENE_FEC_VIEW_KEY = "scene-generation-fec-view";

/** The editor's graph waits until typing pauses. */
const PARSE_DELAY_MS = 250;

function primaryModifierLabel(): string {
  if (typeof navigator === "undefined") {
    return "Ctrl";
  }
  return /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent) ? "⌘" : "Ctrl";
}

interface Props {
  functionalSpecText: string;
  /** What the editor holds: the class id of a loaded catalog scenario, another label, or null. */
  functionalSpecLabel: string | null;
  onFunctionalSpecTextChange: (value: string) => void;
  /** The functional scenario of a class of the control node's catalog. */
  loadScenarioText: (classId: string) => Promise<string>;
  onLoadFunctionalSpecFromFile: (file: File) => void;
  onExportFunctionalSpec: () => void;
  /** Puts a catalog FEC's text into the editor under this label; the selection is cleared, so the editor shows it. */
  onEditCopy: (label: string, text: string) => void;
  isSceneGenerationBusy?: boolean;
  /** Preview a generated scene in the canvas (without loading it on the backend). */
  onVisualizeFromEvaluation?: (evaluationData: EvaluationData, scene: SimulationFrame) => void;
  /** Scene currently visualized in the canvas, used to highlight the active batch result. */
  activeScene?: SimulationFrame | null;
}

/** The editor's text as a model graph, a moment after typing pauses. */
function EditorGraph({ text }: { text: string }) {
  return <ModelGraph text={useDebouncedValue(text, PARSE_DELAY_MS)} label="Model graph of the editor's text" />;
}

/** A catalog FEC read only: its model graph or its text, or why it cannot be read. */
function CatalogFecView({ classId, view }: { classId: string; view: "text" | "graph" }) {
  const text = useCatalogTexts((s) => s.texts[classId]);
  const error = useCatalogTexts((s) => s.errors[classId]);
  if (text === undefined) {
    return error !== undefined ? <p className="error">{error}</p> : <LoadingSpinner label="Reading the FEC's text..." size="sm" />;
  }
  return view === "graph" ? <ModelGraph text={text} label={`Model graph of ${classId}`} /> : <ProblemEditor value={text} readOnly ariaLabel={`Specification of ${classId}`} />;
}

/**
 * The scene page's right pane: the control node's catalog FECs to choose from (search, vessel and obstacle
 * filters, a checkbox per FEC), then what the run takes. Nothing selected: the editor, with its file
 * tools and its model graph. One selected: that FEC read only, with "Edit a copy". Several: they run
 * as a batch. A row's body previews its FEC without selecting it; the latest batch's results stay below
 * the list.
 */
export function SceneGenerationSidebar({
  functionalSpecText,
  functionalSpecLabel,
  onFunctionalSpecTextChange,
  loadScenarioText,
  onLoadFunctionalSpecFromFile,
  onExportFunctionalSpec,
  onEditCopy,
  isSceneGenerationBusy = false,
  onVisualizeFromEvaluation,
  activeScene = null,
}: Props) {
  const functionalSpecInputRef = useRef<HTMLInputElement | null>(null);
  const hasText = functionalSpecText.trim().length > 0;
  const [refineryPasteHintOpen, setRefineryPasteHintOpen] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [editorView, setEditorView] = useTextOrGraph(SCENE_EDITOR_VIEW_KEY, "text");
  const [fecView, setFecView] = useTextOrGraph(SCENE_FEC_VIEW_KEY, "graph");
  // The functional scenarios come from the control node's class catalog: the presets every cluster offers.
  const catalog = useCatalogClasses();
  const allPresets = useMemo(() => catalog.data?.items ?? [], [catalog.data]);
  const manifestLoading = catalog.isLoading;
  const manifestError = catalog.isError ? `The control node's FEC catalog could not be read: ${catalog.error instanceof Error ? catalog.error.message : String(catalog.error)}` : null;
  const [searchQuery, setSearchQuery] = usePersistedState("scene-generation-preset-search", "");
  const [vesselFilter, setVesselFilter] = usePersistedState("scene-generation-vessel-filter", ANY_COUNT);
  const [obstacleFilter, setObstacleFilter] = usePersistedState("scene-generation-obstacle-filter", ANY_COUNT);
  const mod = primaryModifierLabel();

  const selectedClassIds = useBatchGenerationStore((s) => s.selectedClassIds);
  const running = useBatchGenerationStore((s) => s.running);
  const toggle = useBatchGenerationStore((s) => s.toggleSelectedClassId);
  const setSelected = useBatchGenerationStore((s) => s.setSelectedClassIds);
  const clearSelected = useBatchGenerationStore((s) => s.clearSelectedClassIds);
  const keepKnown = useBatchGenerationStore((s) => s.keepKnownSelection);
  const selected = useMemo(() => new Set(selectedClassIds), [selectedClassIds]);
  const mode = sceneSelectionMode(selectedClassIds.length);
  const single = mode === "single" ? selectedClassIds[0] : null;

  const filteredPresets = useMemo(() => filterCatalogClasses(allPresets, searchQuery, vesselFilter, obstacleFilter), [allPresets, searchQuery, vesselFilter, obstacleFilter]);
  const vesselOptions = useMemo(() => countOptions(allPresets, "vessel_count"), [allPresets]);
  const obstacleOptions = useMemo(() => countOptions(allPresets, "obstacle_count"), [allPresets]);
  const hidden = hiddenSelections(selectedClassIds, filteredPresets);

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
  }, [manifestLoading, allPresets.length, vesselFilter, obstacleFilter, vesselOptions, obstacleOptions, setVesselFilter, setObstacleFilter]);

  // A remembered selection of FECs the control node no longer has is dropped once its catalog is known.
  useEffect(() => {
    if (catalog.data !== undefined) {
      keepKnown(new Set(catalog.data.items.map((entry) => entry.fec_id)));
    }
  }, [catalog.data, keepKnown]);

  // Another cluster has another catalog: its texts are read anew.
  const resetTexts = useCatalogTexts((s) => s.reset);
  const lastReader = useRef(loadScenarioText);
  useEffect(() => {
    if (lastReader.current !== loadScenarioText) {
      lastReader.current = loadScenarioText;
      resetTexts();
    }
  }, [loadScenarioText, resetTexts]);

  // The texts of the rows in view, of the previewed FEC and of the one selected.
  const [shownRows, setShownRows] = useState<string[]>([]);
  const onShownRows = useCallback((ids: string[]) => setShownRows(ids), []);
  useEffect(() => {
    const wanted = [...(previewId !== null ? [previewId] : []), ...(single !== null ? [single] : []), ...shownRows];
    void loadCatalogTexts(loadScenarioText, wanted);
  }, [loadScenarioText, previewId, shownRows, single]);

  const openInRefinery = async (text: string) => {
    if (!text.trim()) {
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

  const refineryButton = (text: string | undefined) => (
    <button type="button" className="open-in-refinery-btn" onClick={() => void openInRefinery(text ?? "")} disabled={!text?.trim()}>
      <img src="/refinery-icon.svg" alt="" width={16} height={16} className="open-in-refinery-btn-icon" />
      Open in Refinery
    </button>
  );

  const texts = useCatalogTexts((s) => s.texts);
  const editCopy = (classId: string) => {
    const text = texts[classId];
    if (text === undefined) {
      return;
    }
    setPreviewId(null);
    clearSelected();
    onEditCopy(copyLabel(classId), text);
  };

  const filtersActive = searchQuery || vesselFilter !== ANY_COUNT || obstacleFilter !== ANY_COUNT;

  let detail;
  if (previewId !== null) {
    detail = (
      <section className="scene-pane-detail" aria-label={`Preview of ${previewId}`}>
        <div className="scene-pane-detail-head">
          <h4 className="scene-pane-heading" title={previewId}>
            Preview: {previewId}
          </h4>
          <ViewSwitch label="Show the FEC as" value={fecView} onChange={setFecView} order={["graph", "text"]} />
        </div>
        <div className="toolbar-row">
          <button type="button" disabled={running} onClick={() => toggle(previewId)}>
            {selected.has(previewId) ? "Remove from the selection" : "Add to the selection"}
          </button>
          <button type="button" onClick={() => setPreviewId(null)}>
            Close the preview
          </button>
        </div>
        <CatalogFecView classId={previewId} view={fecView} />
      </section>
    );
  } else if (single !== null) {
    detail = (
      <section className="scene-pane-detail" aria-label={`Selected FEC ${single}`}>
        <div className="scene-pane-detail-head">
          <h4 className="scene-pane-heading" title={single}>
            {single}
          </h4>
          <ViewSwitch label="Show the FEC as" value={fecView} onChange={setFecView} order={["graph", "text"]} />
        </div>
        <p className="meta">Generate scene runs this FEC. To change it, edit a copy in the editor.</p>
        <div className="toolbar-row">
          <button type="button" disabled={isSceneGenerationBusy || texts[single] === undefined} onClick={() => editCopy(single)}>
            Edit a copy
          </button>
          {refineryButton(texts[single])}
        </div>
        <CatalogFecView classId={single} view={fecView} />
      </section>
    );
  } else if (mode === "batch") {
    detail = (
      <section className="scene-pane-detail" aria-label="Selected FECs">
        <p className="meta">
          {selectedClassIds.length} FECs selected: the run generates a scene of each, as one entry with a case per FEC. Only valid scenes are kept. Open a row
          to see its FEC.
        </p>
      </section>
    );
  } else {
    detail = (
      <section className="scene-pane-detail" aria-label="Editor">
        <div className="scene-pane-detail-head">
          <h4 className="scene-pane-heading">{functionalSpecLabel ?? (hasText ? "Written in the editor" : "The editor")}</h4>
          <ViewSwitch label="Show the editor's text as" value={editorView} onChange={setEditorView} />
        </div>
        <p className="meta">No FEC is selected, so the run generates the editor's text. Write one, load a file, or select a FEC above.</p>
        <Disclosure id="scene-gen:file-tools" variant="link" headingLevel={null} title="Files and editor tools" openTitle="Hide files and editor tools" keepMounted>
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
            <button type="button" onClick={onExportFunctionalSpec} disabled={!hasText || isSceneGenerationBusy}>
              Export
            </button>
            {refineryButton(functionalSpecText)}
          </div>
        </Disclosure>
        {/* The editor stays mounted under the graph, so its undo history survives the switch. */}
        <div className="scene-pane-editor" hidden={editorView !== "text"}>
          <ProblemEditor value={functionalSpecText} onChange={onFunctionalSpecTextChange} />
        </div>
        {editorView === "graph" ? <EditorGraph text={functionalSpecText} /> : null}
      </section>
    );
  }

  return (
    <aside className="right-pane scene-generation-sidebar">
      <SceneGenerationPaneViewSelect />
      <div className="scene-editor-panel">
        <p className="meta">Each functional scenario specification is one functional equivalence class (FEC).</p>
        {manifestLoading && <LoadingSpinner label="Loading the control node's FEC catalog…" size="sm" />}
        {manifestError && <p className="error">{manifestError}</p>}
        <Disclosure
          id="scene-gen:find-preset"
          variant="plain"
          headingLevel={4}
          title="FECs of the control node"
          defaultOpen
          hint={`${selectedClassIds.length} selected, ${filtersActive ? `${filteredPresets.length} of ${allPresets.length} match` : `${allPresets.length} FECs`}`}
        >
          <div className="preset-filters toolbar-row">
            <input type="search" placeholder="Search FECs…" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} aria-label="Search FECs" />
            <select value={vesselFilter} onChange={(e) => setVesselFilter(e.target.value)} aria-label="Filter by vessel count">
              <option value={ANY_COUNT}>Any vessels</option>
              {vesselOptions.map((n) => (
                <option key={n} value={String(n)}>
                  {n} vessels
                </option>
              ))}
            </select>
            <select value={obstacleFilter} onChange={(e) => setObstacleFilter(e.target.value)} aria-label="Filter by obstacle count">
              <option value={ANY_COUNT}>Any obstacles</option>
              {obstacleOptions.map((n) => (
                <option key={n} value={String(n)}>
                  {n} obstacles
                </option>
              ))}
            </select>
          </div>
          <div className="toolbar-row fec-pick-toolbar">
            <span className="meta fec-pick-count" role="status">
              {selectedClassIds.length} selected{hidden > 0 ? `, ${hidden} of them not shown by the filters (they run too)` : ""}
            </span>
            <button type="button" disabled={running || filteredPresets.length === 0} onClick={() => setSelected(selectListed(selectedClassIds, filteredPresets))}>
              Select all shown ({filteredPresets.length})
            </button>
            <button type="button" disabled={running || selectedClassIds.length === 0} onClick={clearSelected}>
              Clear
            </button>
          </div>
          {filteredPresets.length === 0 ? (
            <p className="meta">No FEC of the control node's catalog matches the filters.</p>
          ) : (
            <CatalogFecList
              presets={filteredPresets}
              selected={selected}
              previewId={previewId}
              disabled={running}
              onToggle={toggle}
              onPreview={(classId) => setPreviewId((current) => (current === classId ? null : classId))}
              onShownRows={onShownRows}
            />
          )}
        </Disclosure>
        {onVisualizeFromEvaluation ? <SceneBatchResults onVisualizeScenario={onVisualizeFromEvaluation} activeScene={activeScene} /> : null}
        {refineryPasteHintOpen && (
          <div className="refinery-paste-hint" role="status">
            <p>
              Refinery opened in a new tab. The FEC specification is on the clipboard. There: click inside the text editor area, clear it (<kbd>{mod}</kbd>+
              <kbd>A</kbd>), then paste (<kbd>{mod}</kbd>+<kbd>V</kbd>).&nbsp;&nbsp;
              <button type="button" className="refinery-paste-hint-dismiss" onClick={() => setRefineryPasteHintOpen(false)}>
                Dismiss
              </button>
            </p>
          </div>
        )}
        {detail}
      </div>
    </aside>
  );
}
