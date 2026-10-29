import { useState } from "react";
import type { ScalarFieldModel } from "./fieldModel";
import { alternateUnit, CONVERTED_DIGITS, formatDisplayNumber, fromAlternateUnit, toAlternateUnit, unitSymbol } from "./units";
import type { FieldIssue } from "./validation";
import type { YamlEdit } from "./yamlEdit";
import { parseTypedNumber } from "./yamlValues";

export type EditHandler = (edit: YamlEdit) => void;

interface DraftNumberInputProps {
  display: string;
  ariaLabel: string;
  title?: string;
  flagged: boolean;
  onNumber: (value: number) => void;
}

/**
 * A text input for a number. What is typed stays as typed while the input has focus; a text that is not a
 * number is flagged and not written, so the YAML keeps the last valid value.
 */
function DraftNumberInput({ display, ariaLabel, title, flagged, onNumber }: DraftNumberInputProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const invalid = draft !== null && parseTypedNumber(draft) === null;
  const classes = ["ce-input", "ce-number", flagged || invalid ? "ce-flagged" : ""].filter(Boolean).join(" ");
  return (
    <input
      type="text"
      inputMode="decimal"
      className={classes}
      value={draft ?? display}
      aria-label={ariaLabel}
      aria-invalid={invalid || flagged}
      title={invalid ? "This is not a number; the YAML keeps the previous value." : title}
      onChange={(event) => {
        const typed = event.target.value;
        setDraft(typed);
        const parsed = parseTypedNumber(typed);
        if (parsed !== null) {
          onNumber(parsed);
        }
      }}
      onBlur={() => setDraft(null)}
    />
  );
}

export function IssueList({ issues }: { issues: readonly FieldIssue[] }) {
  if (issues.length === 0) {
    return null;
  }
  return (
    <ul className="ce-issues">
      {issues.map((issue, index) => (
        <li key={index} className={`ce-issue ce-issue-${issue.severity}`}>
          {issue.message}
        </li>
      ))}
    </ul>
  );
}

interface ScalarControlProps {
  field: ScalarFieldModel;
  onEdit: EditHandler;
  ariaLabel: string;
  /** In a table cell the unit symbols sit in the column header. */
  showUnits: boolean;
}

/** The input of one scalar: a checkbox, a number with its unit and its converted twin, or text. */
export function ScalarControl({ field, onEdit, ariaLabel, showUnits }: ScalarControlProps) {
  const { path, kind, value } = field;
  const flagged = field.issues.some((issue) => issue.severity === "error");
  const issueTitle = field.issues.map((issue) => issue.message).join(" ");

  if (kind === "boolean") {
    return (
      <input
        type="checkbox"
        className="ce-checkbox"
        checked={value === true}
        aria-label={ariaLabel}
        onChange={(event) => onEdit({ kind: "set", path, value: event.target.checked })}
      />
    );
  }

  if (kind === "number" || kind === "integer") {
    const numeric = value as number;
    const asFloat = kind === "number";
    const unit = field.unit;
    const alternate = unit ? alternateUnit(unit) : null;
    const primaryDisplay = Number(field.source) === numeric ? field.source : formatDisplayNumber(numeric);
    return (
      <span className="ce-number-control">
        <DraftNumberInput
          display={primaryDisplay}
          ariaLabel={ariaLabel}
          title={issueTitle || undefined}
          flagged={flagged}
          onNumber={(next) => onEdit({ kind: "set", path, value: next, asFloat })}
        />
        {showUnits && unit ? <span className="ce-unit">{unitSymbol(unit)}</span> : null}
        {unit && alternate ? (
          // The converted value: beside the value in a form, under it in a table cell (constraintsEditor.css)
          <span className="ce-converted">
            <span className="ce-equals">=</span>
            <DraftNumberInput
              display={formatDisplayNumber(toAlternateUnit(unit, numeric), CONVERTED_DIGITS)}
              ariaLabel={`${ariaLabel} in ${alternate.symbol}`}
              flagged={false}
              onNumber={(next) => onEdit({ kind: "set", path, value: fromAlternateUnit(unit, next), asFloat: true })}
            />
            {showUnits ? <span className="ce-unit">{alternate.symbol}</span> : null}
          </span>
        ) : null}
      </span>
    );
  }

  return (
    <input
      type="text"
      className={`ce-input ce-text${flagged ? " ce-flagged" : ""}`}
      value={value === null ? "" : String(value)}
      placeholder={kind === "null" ? "null" : undefined}
      aria-label={ariaLabel}
      title={issueTitle || undefined}
      onChange={(event) => onEdit({ kind: "set", path, value: event.target.value === "" && kind === "null" ? null : event.target.value })}
    />
  );
}
