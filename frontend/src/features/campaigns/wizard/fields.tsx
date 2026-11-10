import { useId, useState, type ReactNode } from "react";
import type { CatalogParameter, StepMonitor } from "../../../domain/cluster/campaignApi";
import type { Reason } from "./reasons";
import { UNLIMITED_FAILURE_BUDGET, type FailureBudgetDraft } from "./wizardState";

/** Form pieces of the wizard: labelled fields with their reasons, number inputs, and an input for each catalog parameter type. */

export function FieldIssues({ reasons, showField = false }: { reasons: readonly Reason[] | undefined; showField?: boolean }) {
  if (!reasons || reasons.length === 0) {
    return null;
  }
  return (
    <ul className="wiz-issues" role="alert">
      {reasons.map((reason, index) => (
        <li key={`${reason.raw}-${index}`} className={`wiz-issue wiz-issue--${reason.source}`}>
          {reason.source === "server" && <span className="wiz-issue-source">master</span>}
          {showField && reason.field ? `${reason.field}: ` : ""}
          {reason.message}
        </li>
      ))}
    </ul>
  );
}

const MONITOR_CHOICES: { value: StepMonitor; label: string; hint: (output: string) => string }[] = [
  { value: "empty", label: "No monitor", hint: (output) => `The ${output} are kept without a monitor result summary.` },
  { value: "post_hoc", label: "Post hoc monitor", hint: (output) => `The COLREGS monitor judges the ${output} after the step.` },
];

/** The monitor after a generation step: none, or the post hoc monitor that judges what the step produced. */
export function MonitorChoice({ name, legend, output, value, onChange }: { name: string; legend: string; output: string; value: StepMonitor; onChange: (value: StepMonitor) => void }) {
  return (
    <fieldset className="wiz-choice">
      <legend>{legend}</legend>
      {MONITOR_CHOICES.map((choice) => (
        <label key={choice.value} className={`wiz-option${value === choice.value ? " wiz-option--on" : ""}`}>
          <input type="radio" name={name} checked={value === choice.value} onChange={() => onChange(choice.value)} />
          <span>
            <strong>{choice.label}</strong>
            <span className="wiz-hint">{choice.hint(output)}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  issues?: readonly Reason[];
  htmlFor?: string;
  children: ReactNode;
  /** Lay the label and the input side by side. */
  inline?: boolean;
}

export function Field({ label, hint, issues, htmlFor, children, inline }: FieldProps) {
  const invalid = issues !== undefined && issues.length > 0;
  return (
    <div className={`wiz-field${inline ? " wiz-field--inline" : ""}${invalid ? " wiz-field--invalid" : ""}`}>
      <label className="wiz-label" htmlFor={htmlFor}>
        {label}
      </label>
      <div className="wiz-control">
        {children}
        {hint && <p className="wiz-hint wiz-field-hint">{hint}</p>}
        <FieldIssues reasons={issues} />
      </div>
    </div>
  );
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "" : String(value);
}

export interface NumberFieldProps {
  id?: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  integer?: boolean;
  min?: number;
  max?: number;
  placeholder?: string;
  invalid?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
  suffix?: string;
}

/** A number input that keeps what is typed until it reads as a number; an empty box is null. */
export function NumberField({ id, value, onChange, integer, min, max, placeholder, invalid, disabled, ariaLabel, suffix }: NumberFieldProps) {
  const [draft, setDraft] = useState(formatNumber(value));
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    // Follow a change made elsewhere (a reset), not the user's own typing
    setSeen(value);
    const typed = draft.trim() === "" ? null : Number(draft);
    if (typed !== (value ?? null)) {
      setDraft(formatNumber(value));
    }
  }

  const commit = (text: string) => {
    setDraft(text);
    if (text.trim() === "") {
      onChange(null);
      return;
    }
    const parsed = Number(text);
    if (Number.isFinite(parsed) && (!integer || Number.isInteger(parsed))) {
      onChange(parsed);
    }
  };

  const typed = draft.trim() === "" ? null : Number(draft);
  const unreadable = typed !== null && (!Number.isFinite(typed) || (integer === true && !Number.isInteger(typed)));
  return (
    <span className="wiz-number">
      <input
        id={id}
        type="number"
        inputMode={integer ? "numeric" : "decimal"}
        step={integer ? 1 : "any"}
        min={min}
        max={max}
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-invalid={invalid || unreadable ? true : undefined}
        className={invalid || unreadable ? "wiz-input-invalid" : undefined}
        onChange={(event) => commit(event.target.value)}
      />
      {suffix && <span className="wiz-unit">{suffix}</span>}
    </span>
  );
}

/**
 * A failure budget: a number of cases, or unlimited. Unticking Unlimited brings back the number it replaced. An
 * unlimited class is never abandoned, so a scenario that never gives a valid scene runs until a stop condition or
 * the operator ends the campaign.
 */
export function FailureBudgetField({ id, value, invalid, onChange }: { id: string; value: FailureBudgetDraft; invalid?: boolean; onChange: (value: FailureBudgetDraft) => void }) {
  const unlimited = value === UNLIMITED_FAILURE_BUDGET;
  const [replaced, setReplaced] = useState<number | null>(null);
  return (
    <span className="wiz-budget">
      <span className="wiz-budget-row">
        <NumberField id={id} integer min={0} value={unlimited ? null : value} placeholder={unlimited ? "unlimited" : undefined} disabled={unlimited} invalid={invalid} onChange={onChange} />
        <label className="wiz-check">
          <input
            type="checkbox"
            checked={unlimited}
            onChange={(event) => {
              if (event.target.checked) {
                setReplaced(typeof value === "number" ? value : null);
                onChange(UNLIMITED_FAILURE_BUDGET);
              } else {
                onChange(replaced ?? 0);
              }
            }}
          />
          Unlimited
        </label>
      </span>
      {unlimited && <span className="wiz-hint wiz-hint--warn wiz-budget-note">Never abandoned: it runs until its quota is complete, a stop condition of the Policy step ends the campaign, or you stop it.</span>}
    </span>
  );
}

function constraintText(parameter: CatalogParameter): string {
  const parts: string[] = [];
  if (parameter.minimum !== null && parameter.minimum !== undefined) {
    parts.push(`at least ${parameter.minimum}`);
  }
  if (parameter.exclusive_minimum !== null && parameter.exclusive_minimum !== undefined) {
    parts.push(`above ${parameter.exclusive_minimum}`);
  }
  if (parameter.maximum !== null && parameter.maximum !== undefined) {
    parts.push(`at most ${parameter.maximum}`);
  }
  return parts.join(", ");
}

function defaultText(parameter: CatalogParameter): string | undefined {
  const { default: fallback } = parameter;
  if (fallback === null || fallback === undefined) {
    return undefined;
  }
  if (typeof fallback === "object") {
    return Array.isArray(fallback) ? fallback.join(", ") : undefined;
  }
  return String(fallback);
}

function MapInput({ value, onChange }: { value: Record<string, number>; onChange: (value: Record<string, number> | undefined) => void }) {
  const entries = Object.entries(value);
  const [draft, setDraft] = useState<{ key: string; value: number | null }[]>(() => entries.map(([key, number]) => ({ key, value: number })));
  const update = (next: { key: string; value: number | null }[]) => {
    setDraft(next);
    const result: Record<string, number> = {};
    for (const row of next) {
      if (row.key.trim() && row.value !== null) {
        result[row.key.trim()] = row.value;
      }
    }
    onChange(Object.keys(result).length > 0 ? result : undefined);
  };
  return (
    <div className="wiz-map">
      {draft.map((row, index) => (
        <div key={index} className="wiz-map-row">
          <input
            type="text"
            value={row.key}
            placeholder="name"
            aria-label={`Name ${index + 1}`}
            onChange={(event) => update(draft.map((item, at) => (at === index ? { ...item, key: event.target.value } : item)))}
          />
          <NumberField value={row.value} ariaLabel={`Value ${index + 1}`} onChange={(next) => update(draft.map((item, at) => (at === index ? { ...item, value: next } : item)))} />
          <button type="button" onClick={() => update(draft.filter((_item, at) => at !== index))} aria-label={`Remove ${row.key || `row ${index + 1}`}`}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="wiz-add" onClick={() => setDraft([...draft, { key: "", value: null }])}>
        Add a value
      </button>
    </div>
  );
}

export interface ParameterInputProps {
  parameter: CatalogParameter;
  value: unknown;
  /** Undefined takes the parameter out of the config. */
  onChange: (value: unknown) => void;
  issues?: readonly Reason[];
  /** What a missing value means when the catalog gives no default (for example "derived from the scene"). */
  absentText?: string;
}

function tuple(value: unknown, size: number): (number | null)[] {
  const list = Array.isArray(value) ? (value as unknown[]) : [];
  return Array.from({ length: size }, (_unused, index) => (typeof list[index] === "number" ? (list[index] as number) : null));
}

/** An input for one catalog parameter, by its type; an empty box leaves the parameter out. */
export function ParameterInput({ parameter, value, onChange, issues, absentText }: ParameterInputProps) {
  const id = useId();
  const fallback = defaultText(parameter);
  const placeholder = fallback ?? (parameter.required ? "required" : (absentText ?? "left out"));
  const constraints = constraintText(parameter);
  const hint = (
    <>
      {parameter.description}
      {constraints && <span className="wiz-constraint"> ({constraints})</span>}
      {fallback !== undefined && <span className="wiz-constraint"> Default {fallback}.</span>}
    </>
  );
  const label = (
    <>
      {parameter.key}
      {parameter.required && <span className="wiz-required" title="Required"> *</span>}
    </>
  );
  const invalid = issues !== undefined && issues.length > 0;
  let control: ReactNode;
  switch (parameter.type) {
    case "number":
    case "integer":
      control = (
        <NumberField
          id={id}
          value={typeof value === "number" ? value : null}
          integer={parameter.type === "integer"}
          min={parameter.minimum ?? undefined}
          max={parameter.maximum ?? undefined}
          placeholder={placeholder}
          suffix={parameter.unit ?? undefined}
          invalid={invalid}
          onChange={(next) => onChange(next === null ? undefined : next)}
        />
      );
      break;
    case "boolean":
      control = (
        <select id={id} value={typeof value === "boolean" ? String(value) : ""} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}>
          <option value="">{fallback !== undefined ? `Default (${fallback})` : "Left out"}</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      );
      break;
    case "string":
      control = parameter.choices && parameter.choices.length > 0 ? (
        <select id={id} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}>
          <option value="">{fallback !== undefined ? `Default (${fallback})` : "Left out"}</option>
          {parameter.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : (
        <input id={id} type="text" value={typeof value === "string" ? value : ""} placeholder={placeholder} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)} />
      );
      break;
    case "number_pair":
    case "number_triple": {
      const size = parameter.type === "number_pair" ? 2 : 3;
      const parts = tuple(value, size);
      const axes = size === 2 ? ["x", "y"] : ["east", "north", "up"];
      control = (
        <span className="wiz-tuple">
          {parts.map((part, index) => (
            <span key={axes[index]} className="wiz-tuple-part">
              <span className="wiz-axis">{axes[index]}</span>
              <NumberField
                id={index === 0 ? id : undefined}
                value={part}
                ariaLabel={`${parameter.key} ${axes[index]}`}
                invalid={invalid}
                onChange={(next) => {
                  const updated = parts.map((item, at) => (at === index ? next : item));
                  onChange(updated.every((item) => item === null) ? undefined : updated.map((item) => item ?? 0));
                }}
              />
            </span>
          ))}
          {parameter.unit && <span className="wiz-unit">{parameter.unit}</span>}
        </span>
      );
      break;
    }
    case "number_map":
      control = <MapInput value={(value as Record<string, number> | undefined) ?? {}} onChange={onChange} />;
      break;
    default:
      control = <span className="meta">This value is set in the YAML.</span>;
  }
  return (
    <Field label={label} htmlFor={id} hint={hint} issues={issues}>
      {control}
    </Field>
  );
}
