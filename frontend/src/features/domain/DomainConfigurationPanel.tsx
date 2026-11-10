import { useRef, useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { DOMAIN_KEYS, DOMAIN_LABELS, matchingPreset, type DomainKey, type DomainPreset, type DomainPresets, type DomainTexts } from "../../domain/cluster/presetsApi";
import { ConstraintsEditor } from "../workbench/controls/constraintsEditor";

// The backend looks these rows up by name (VesselTypeMap and StaticObstacleTypeMap).
const PROTECTED_ROWS: Partial<Record<DomainKey, readonly string[]>> = {
  vessel_types: ["UnspecifiedVesselType"],
  obstacle_types: ["UnspecifiedObstacleType"],
};

/** The tab of each text; the COLREGS constants keep the name their remembered sections were stored under. */
const TAB_LABELS: Record<DomainKey, string> = {
  colregs_constants: "Collision rules (COLREGS)",
  vessel_types: "Vessel types",
  obstacle_types: "Static obstacle types",
};
const EDITOR_SCOPES: Partial<Record<DomainKey, string>> = { colregs_constants: "colregs" };

interface DomainFileToolsProps {
  domainKey: DomainKey;
  text: string;
  /** The control node's presets of this text; null while they load. */
  presets: readonly DomainPreset[] | null;
  onTextChange: (key: DomainKey, text: string) => void;
  onLoadFile: (key: DomainKey, file: File) => void;
  onExport: (key: DomainKey) => void;
}

/** Pick one of the control node's presets (the usual way to change a text) and, behind one toggle, load a file from the computer or export. */
function DomainFileTools({ domainKey, text, presets, onTextChange, onLoadFile, onExport }: DomainFileToolsProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const match = presets === null ? null : matchingPreset(presets, text);
  return (
    <div className="domain-file-tools">
      <select
        aria-label={`Load a preset of the ${DOMAIN_LABELS[domainKey]}`}
        value={match?.name ?? ""}
        disabled={presets === null || presets.length === 0}
        onChange={(event) => {
          const preset = presets?.find((entry) => entry.name === event.target.value);
          if (preset) {
            onTextChange(domainKey, preset.content);
          }
        }}
      >
        <option value="" disabled>
          {presets === null ? "Loading the control node's presets..." : text.trim() ? "Edited: load a preset of the control node..." : "Load a preset of the control node..."}
        </option>
        {(presets ?? []).map((preset) => (
          <option key={preset.name} value={preset.name}>
            {preset.default ? `${preset.name} (default)` : preset.name}
          </option>
        ))}
      </select>
      <Disclosure
        id={`domain-config:${domainKey}:file-options`}
        variant="link"
        headingLevel={null}
        title="Files: load or export"
        openTitle="Hide file options"
        keepMounted
      >
        <div className="toolbar-row">
          <input
            ref={fileInputRef}
            hidden
            type="file"
            accept=".yaml,.yml,text/yaml,text/x-yaml"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                onLoadFile(domainKey, file);
              }
              event.target.value = "";
            }}
          />
          <button type="button" onClick={() => fileInputRef.current?.click()}>
            Load from computer
          </button>
          <button type="button" onClick={() => onExport(domainKey)} disabled={text.trim().length === 0}>
            Export as YAML file
          </button>
        </div>
      </Disclosure>
    </div>
  );
}

interface Props {
  texts: DomainTexts;
  presets: DomainPresets | null;
  onTextChange: (key: DomainKey, text: string) => void;
  onLoadFile: (key: DomainKey, file: File) => void;
  onExport: (key: DomainKey) => void;
}

/** The three texts of a domain configuration, one tab each, so every editor has the page's full width. */
export function DomainConfigurationPanel({ texts, presets, onTextChange, onLoadFile, onExport }: Props) {
  const [activeKey, setActiveKey] = useState<DomainKey>("colregs_constants");

  return (
    <div className="domain-configuration-panel">
      <div className="scene-gen-tabs" role="tablist" aria-label="Domain configuration section">
        {DOMAIN_KEYS.map((key) => (
          <button
            key={key}
            id={`domain-tab-${key}`}
            className={`scene-gen-tab${activeKey === key ? " active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeKey === key}
            aria-controls="domain-tab-panel"
            onClick={() => setActiveKey(key)}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      <div className="scene-editor-panel" role="tabpanel" id="domain-tab-panel" aria-labelledby={`domain-tab-${activeKey}`}>
        <DomainFileTools
          domainKey={activeKey}
          text={texts[activeKey]}
          presets={presets?.[activeKey] ?? null}
          onTextChange={onTextChange}
          onLoadFile={onLoadFile}
          onExport={onExport}
        />
        <ConstraintsEditor
          key={activeKey}
          text={texts[activeKey]}
          onTextChange={(text) => onTextChange(activeKey, text)}
          label={DOMAIN_LABELS[activeKey]}
          scope={EDITOR_SCOPES[activeKey]}
          protectedRows={PROTECTED_ROWS[activeKey]}
          tableMinRows={PROTECTED_ROWS[activeKey] ? 1 : undefined}
        />
      </div>
    </div>
  );
}
