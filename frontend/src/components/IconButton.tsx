import type { ReactNode } from "react";

interface IconButtonProps {
  /** Accessible name and tooltip; the button shows only the icon. */
  label: string;
  icon: ReactNode;
  onClick: () => void;
  /** Longer tooltip when the name alone does not say enough (a shortcut, why it is disabled). */
  title?: string;
  /** For a toggle: whether it is on (`aria-pressed`). */
  pressed?: boolean;
  /** For a button that shows or hides a region: whether it is shown (`aria-expanded`). */
  expanded?: boolean;
  disabled?: boolean;
  className?: string;
}

/**
 * A square button with an icon and no text, for actions that tell nothing by themselves
 * (fit the view, hide a panel, export). Its name is the tooltip and what assistive
 * technology reads; it is at least the hit target in both directions.
 */
export function IconButton({ label, icon, onClick, title, pressed, expanded, disabled, className }: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-btn${pressed ? " is-active" : ""}${className ? ` ${className}` : ""}`}
      aria-label={label}
      title={title ?? label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
    </button>
  );
}
