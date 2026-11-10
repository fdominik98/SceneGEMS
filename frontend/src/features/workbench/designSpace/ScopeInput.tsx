import { useId } from "react";
import { SCOPE_FORM, SCOPE_PLACEHOLDER, scopeProblem } from "../../../domain/designSpace/designSpaceScope";
import "./designSpace.css";

interface Props {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** The field's accessible name when no label element names it. */
  ariaLabel?: string;
  id?: string;
}

/**
 * The scope of a design space exploration: one text field, checked as it is typed, with a message
 * that says which entry is wrong and the form it should have. An empty field shows the form only.
 */
export function ScopeInput({ value, onChange, disabled, ariaLabel, id }: Props) {
  const own = useId();
  const inputId = id ?? own;
  const messageId = `${inputId}-message`;
  const problem = value.trim().length === 0 ? null : scopeProblem(value);
  return (
    <span className="scope-input">
      <input
        id={inputId}
        type="text"
        className="scope-input-field"
        value={value}
        placeholder={SCOPE_PLACEHOLDER}
        spellCheck={false}
        autoComplete="off"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-invalid={problem !== null || undefined}
        aria-describedby={messageId}
        title={`How many objects of each class: ${SCOPE_FORM}`}
        onChange={(event) => onChange(event.target.value)}
      />
      <span id={messageId} className={problem !== null ? "scope-input-message error" : "scope-input-message meta"} role={problem !== null ? "alert" : undefined}>
        {problem ?? (value.trim().length === 0 ? `Enter ${SCOPE_FORM}.` : null)}
      </span>
    </span>
  );
}
