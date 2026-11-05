import CodeMirror from "@uiw/react-codemirror";
import { useMemo, useState } from "react";
import { useTheme } from "../../../../app/theme";
import { usePersistedState } from "../../../../app/usePersistedState";
import { yamlEditorExtensions } from "../yamlEditorExtensions";
import "./constraintsEditor.css";
import { ConstraintsForm } from "./ConstraintsForm";
import { findParseFailure, type ModelOptions } from "./fieldModel";

export type ConstraintsEditorTab = "form" | "yaml";

export interface ConstraintsEditorProps extends ModelOptions {
  /** The YAML text. The editor keeps no copy: it shows this text and reports every change. */
  text: string;
  onTextChange: (text: string) => void;
  /** The tab shown first (default the form). */
  initialTab?: ConstraintsEditorTab;
  /** Names the editor for assistive technology, for example "COLREGS constraints". */
  label?: string;
  /** Names the file in the remembered state of its collapsible sections; defaults to the label. */
  scope?: string;
}

/**
 * Edits a constraints YAML text as a form generated from the YAML itself, or as raw YAML. Both tabs edit
 * the same text, so a change in one shows in the other, and comments and key order survive form edits.
 */
export function ConstraintsEditor({ text, onTextChange, initialTab = "form", label = "Constraints", scope, protectedRows, tableMinRows }: ConstraintsEditorProps) {
  const [tab, setTab] = useState<ConstraintsEditorTab>(initialTab);
  const [showKeys, setShowKeys] = usePersistedState("constraints-show-keys", false);
  const failure = useMemo(() => findParseFailure(text), [text]);
  const theme = useTheme();

  return (
    <div className="ce-editor" data-show-keys={showKeys ? "true" : undefined}>
      <div className="ce-tabs" role="tablist" aria-label={`${label} view`}>
        <button type="button" role="tab" aria-selected={tab === "form"} className={`ce-tab${tab === "form" ? " active" : ""}`} onClick={() => setTab("form")}>
          Form
        </button>
        <button type="button" role="tab" aria-selected={tab === "yaml"} className={`ce-tab${tab === "yaml" ? " active" : ""}`} onClick={() => setTab("yaml")}>
          YAML text
          {failure ? <span className="ce-tab-flag" title="The YAML does not parse">!</span> : null}
        </button>
        {tab === "form" ? (
          <label className="check ce-keys-toggle">
            <input type="checkbox" checked={showKeys} onChange={(event) => setShowKeys(event.target.checked)} />
            <span>Show technical names</span>
          </label>
        ) : null}
      </div>
      {tab === "form" ? (
        <div className="ce-body" role="tabpanel" aria-label={`${label} form`}>
          <ConstraintsForm
            scope={scope ?? label}
            text={text}
            onTextChange={onTextChange}
            onShowYaml={() => setTab("yaml")}
            protectedRows={protectedRows}
            tableMinRows={tableMinRows}
          />
        </div>
      ) : (
        <div className="ce-body ce-body-yaml" role="tabpanel" aria-label={`${label} YAML`}>
          {failure ? (
            <p className="ce-issue ce-issue-error ce-yaml-error" role="alert">
              {failure.message}
              {failure.line !== null ? ` (line ${failure.line}${failure.column !== null ? `, column ${failure.column}` : ""})` : ""}
            </p>
          ) : null}
          <CodeMirror
            className="scene-editor-yaml-codemirror"
            value={text}
            height="100%"
            theme={theme}
            extensions={yamlEditorExtensions[theme]}
            onChange={onTextChange}
          />
        </div>
      )}
    </div>
  );
}
