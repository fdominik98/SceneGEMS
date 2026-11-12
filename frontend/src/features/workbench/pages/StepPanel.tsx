import type { CSSProperties, ReactNode } from "react";
import { NumberField } from "../../campaigns/wizard/fields";
import "./stepPanel.css";
import { WORKBENCH_STEP_PAGES, type WorkbenchPage } from "./workbenchTarget";

/** The tone of a page's status chip. */
export type StepTone = "idle" | "busy" | "live" | "ok" | "warn" | "error";

export interface StepStatus {
  label: string;
  tone: StepTone;
}

/** Something the page needs before it can run, with an optional way to fix it. */
export interface StepNotice {
  text: string;
  action?: { label: string; onClick: () => void };
}

interface StepPanelProps {
  /** The page whose step this is: its place in the chain gives the number. */
  page: WorkbenchPage;
  title: string;
  status: StepStatus;
  /** Where the run happens and what it has there (the cluster's slots). */
  where?: ReactNode;
  /** The run buttons at the right of the header. */
  actions: ReactNode;
  notices?: StepNotice[];
  /** The page's rows: its input, its setup and its result. */
  children: ReactNode;
}

/**
 * The panel under the canvas of a workbench page, the same on every page: the step with its
 * status and its run buttons, what is missing before it can run, then a row each for the
 * page's input, its setup and the result it shows.
 */
export function StepPanel({ page, title, status, where, actions, notices = [], children }: StepPanelProps) {
  return (
    <section className="step-panel" aria-label={title}>
      {/* The title and the run buttons share the first line on every page; where it runs takes the line under them. */}
      <header className="step-panel-head">
        <div className="step-panel-title">
          <span className="step-panel-step">
            Step {WORKBENCH_STEP_PAGES.indexOf(page) + 1} of {WORKBENCH_STEP_PAGES.length}
          </span>
          <h3>{title}</h3>
          <StatusChip status={status} />
        </div>
        <div className="step-panel-actions">{actions}</div>
        {where ? <p className="step-panel-where">{where}</p> : null}
      </header>
      {notices.length > 0 ? (
        <ul className="step-notices" aria-label="Before it can run">
          {notices.map((notice) => (
            <li key={notice.text}>
              {notice.text}
              {notice.action ? (
                <button type="button" className="link-btn" onClick={notice.action.onClick}>
                  {notice.action.label}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="step-rows">{children}</div>
    </section>
  );
}

export function StatusChip({ status }: { status: StepStatus }) {
  return (
    <span className={`step-chip step-chip--${status.tone}`} role="status">
      {status.label}
    </span>
  );
}

interface StepRowProps {
  /** Input, Setup or Result. */
  label: string;
  children: ReactNode;
  /** Buttons at the row's right end (export, the next page). */
  aside?: ReactNode;
}

/** One row of a step panel: its label, its content, and buttons at its end. */
export function StepRow({ label, children, aside }: StepRowProps) {
  return (
    <div className="step-row" role="group" aria-label={label}>
      <span className="step-row-label" aria-hidden>
        {label}
      </span>
      <div className="step-row-body">{children}</div>
      {aside ? <div className="step-row-aside">{aside}</div> : null}
    </div>
  );
}

/** A setting on one line: its name, then its control. */
export function Setting({ label, title, children }: { label: string; title?: string; children: ReactNode }) {
  return (
    <label className="step-setting" title={title}>
      <span className="step-setting-label">{label}</span>
      {children}
    </label>
  );
}

interface NumberSettingProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  integer?: boolean;
  unit?: string;
  /** Room for this many characters in the field. */
  width?: number;
  title?: string;
  disabled?: boolean;
}

/** A number setting on one line, kept within its bounds; clearing the field keeps the last value. */
export function NumberSetting({ label, value, onChange, min, max, integer, unit, width = 6, title, disabled }: NumberSettingProps) {
  return (
    <span className="step-setting step-number" title={title} style={{ "--field-ch": width } as CSSProperties}>
      <span className="step-setting-label" aria-hidden>
        {label}
      </span>
      <NumberField
        value={value}
        integer={integer}
        min={min}
        max={max}
        ariaLabel={unit ? `${label} (${unit})` : label}
        disabled={disabled}
        onChange={(next) => {
          if (next === null) {
            return;
          }
          onChange(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next)));
        }}
        suffix={unit}
      />
    </span>
  );
}
