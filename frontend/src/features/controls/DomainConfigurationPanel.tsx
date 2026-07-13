import CodeMirror from "@uiw/react-codemirror";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  COLREGS_CONSTRAINTS_PRESETS,
  OBSTACLE_TYPES_PRESETS,
  VESSEL_TYPES_PRESETS,
} from "./domainConfigPresets";
import { yamlEditorExtensions } from "./yamlEditorExtensions";

type DomainConfigTab = "colregs" | "vesselObstacleTypes";

const DUAL_COLUMN_SPLIT_MIN = 15;
const DUAL_COLUMN_SPLIT_MAX = 85;

function clampDualColumnSplit(value: number): number {
  return Math.min(DUAL_COLUMN_SPLIT_MAX, Math.max(DUAL_COLUMN_SPLIT_MIN, value));
}

interface YamlEditorColumnProps {
  title: string;
  presets: readonly string[];
  text: string;
  onTextChange: (value: string) => void;
  onLoadFromPreset: (path: string) => void;
  onLoadFromFile: (file: File) => void;
  onExport: () => void;
  style?: CSSProperties;
}

function YamlEditorColumn({
  title,
  presets,
  text,
  onTextChange,
  onLoadFromPreset,
  onLoadFromFile,
  onExport,
  style,
}: YamlEditorColumnProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const hasContent = useMemo(() => text.trim().length > 0, [text]);

  return (
    <div className="domain-config-column" style={style}>
      <h4>{title}</h4>
      <div className="toolbar-row">
        <select
          onChange={(event) => {
            const path = event.target.value;
            if (path) {
              onLoadFromPreset(path);
            }
          }}
          defaultValue=""
        >
          <option value="" disabled>
            Load preset...
          </option>
          {presets.map((path) => (
            <option key={path} value={path}>
              {path}
            </option>
          ))}
        </select>
        <input
          ref={fileInputRef}
          hidden
          type="file"
          accept=".yaml,.yml,text/yaml,text/x-yaml"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              onLoadFromFile(file);
            }
            event.target.value = "";
          }}
        />
        <button type="button" onClick={() => fileInputRef.current?.click()}>
          Load from computer
        </button>
        <button type="button" onClick={onExport} disabled={!hasContent}>
          Export
        </button>
      </div>
      <CodeMirror
        className="scene-editor-yaml-codemirror"
        value={text}
        height="100%"
        theme="dark"
        extensions={yamlEditorExtensions}
        onChange={onTextChange}
      />
    </div>
  );
}

interface Props {
  colregsText: string;
  onColregsTextChange: (value: string) => void;
  onLoadColregsFromPreset: (path: string) => void;
  onLoadColregsFromFile: (file: File) => void;
  onExportColregs: () => void;
  vesselTypesText: string;
  onVesselTypesTextChange: (value: string) => void;
  onLoadVesselTypesFromPreset: (path: string) => void;
  onLoadVesselTypesFromFile: (file: File) => void;
  onExportVesselTypes: () => void;
  obstacleTypesText: string;
  onObstacleTypesTextChange: (value: string) => void;
  onLoadObstacleTypesFromPreset: (path: string) => void;
  onLoadObstacleTypesFromFile: (file: File) => void;
  onExportObstacleTypes: () => void;
}

export function DomainConfigurationPanel({
  colregsText,
  onColregsTextChange,
  onLoadColregsFromPreset,
  onLoadColregsFromFile,
  onExportColregs,
  vesselTypesText,
  onVesselTypesTextChange,
  onLoadVesselTypesFromPreset,
  onLoadVesselTypesFromFile,
  onExportVesselTypes,
  obstacleTypesText,
  onObstacleTypesTextChange,
  onLoadObstacleTypesFromPreset,
  onLoadObstacleTypesFromFile,
  onExportObstacleTypes,
}: Props) {
  const [activeTab, setActiveTab] = useState<DomainConfigTab>("colregs");
  const [vesselColumnSplitPercent, setVesselColumnSplitPercent] = useState(50);
  const [isResizingDualColumns, setIsResizingDualColumns] = useState(false);
  const dualColumnsRef = useRef<HTMLDivElement | null>(null);
  const dualColumnSplitDragRef = useRef<{ startX: number; startSplit: number; width: number } | null>(
    null
  );
  const colregsInputRef = useRef<HTMLInputElement | null>(null);
  const hasColregs = useMemo(() => colregsText.trim().length > 0, [colregsText]);

  const onDualColumnResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const el = dualColumnsRef.current;
      if (!el) {
        return;
      }
      const width = el.getBoundingClientRect().width;
      dualColumnSplitDragRef.current = {
        startX: event.clientX,
        startSplit: vesselColumnSplitPercent,
        width,
      };
      setIsResizingDualColumns(true);

      const onPointerMove = (moveEvent: PointerEvent) => {
        const drag = dualColumnSplitDragRef.current;
        if (!drag) {
          return;
        }
        const deltaPct = ((moveEvent.clientX - drag.startX) / drag.width) * 100;
        setVesselColumnSplitPercent(clampDualColumnSplit(drag.startSplit + deltaPct));
      };

      const onPointerUp = () => {
        dualColumnSplitDragRef.current = null;
        setIsResizingDualColumns(false);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp, { once: true });
    },
    [vesselColumnSplitPercent]
  );

  return (
    <aside className="right-pane scene-generation-sidebar domain-configuration-panel">
      <div className="scene-gen-tabs" role="tablist" aria-label="Domain configuration section">
        <button
          className={`scene-gen-tab${activeTab === "colregs" ? " active" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeTab === "colregs"}
          onClick={() => setActiveTab("colregs")}
        >
          COLREGS Constants
        </button>
        <button
          className={`scene-gen-tab${activeTab === "vesselObstacleTypes" ? " active" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeTab === "vesselObstacleTypes"}
          onClick={() => setActiveTab("vesselObstacleTypes")}
        >
          Vessel and Obstacle types
        </button>
      </div>

      {activeTab === "colregs" ? (
        <div className="scene-editor-panel">
          <h3>COLREGS Constants (.yaml)</h3>
          <div className="toolbar-row">
            <select
              onChange={(event) => {
                const path = event.target.value;
                if (path) {
                  onLoadColregsFromPreset(path);
                }
              }}
              defaultValue=""
            >
              <option value="" disabled>
                Load preset...
              </option>
              {COLREGS_CONSTRAINTS_PRESETS.map((path) => (
                <option key={path} value={path}>
                  {path}
                </option>
              ))}
            </select>
            <input
              ref={colregsInputRef}
              hidden
              type="file"
              accept=".yaml,.yml,text/yaml,text/x-yaml"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  onLoadColregsFromFile(file);
                }
                event.target.value = "";
              }}
            />
            <button type="button" onClick={() => colregsInputRef.current?.click()}>
              Load from computer
            </button>
            <button type="button" onClick={onExportColregs} disabled={!hasColregs}>
              Export
            </button>
          </div>
          <CodeMirror
            className="scene-editor-yaml-codemirror"
            value={colregsText}
            height="100%"
            theme="dark"
            extensions={yamlEditorExtensions}
            onChange={onColregsTextChange}
          />
        </div>
      ) : (
        <div className="scene-editor-panel domain-config-dual-panel">
          <h3>Vessel and Obstacle types (.yaml)</h3>
          <div
            ref={dualColumnsRef}
            className={`domain-config-dual-columns${isResizingDualColumns ? " is-resizing" : ""}`}
          >
            <YamlEditorColumn
              title="Vessel types"
              presets={VESSEL_TYPES_PRESETS}
              text={vesselTypesText}
              onTextChange={onVesselTypesTextChange}
              onLoadFromPreset={onLoadVesselTypesFromPreset}
              onLoadFromFile={onLoadVesselTypesFromFile}
              onExport={onExportVesselTypes}
              style={{ flex: `0 0 ${vesselColumnSplitPercent}%`, minWidth: 0 }}
            />
            <div
              className="domain-config-column-resizer"
              onPointerDown={onDualColumnResizeStart}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize vessel types and obstacle types panels"
              aria-valuenow={vesselColumnSplitPercent}
              aria-valuemin={DUAL_COLUMN_SPLIT_MIN}
              aria-valuemax={DUAL_COLUMN_SPLIT_MAX}
            />
            <YamlEditorColumn
              title="Static obstacle types"
              presets={OBSTACLE_TYPES_PRESETS}
              text={obstacleTypesText}
              onTextChange={onObstacleTypesTextChange}
              onLoadFromPreset={onLoadObstacleTypesFromPreset}
              onLoadFromFile={onLoadObstacleTypesFromFile}
              onExport={onExportObstacleTypes}
              style={{ flex: "1 1 0%", minWidth: 0 }}
            />
          </div>
        </div>
      )}
    </aside>
  );
}
