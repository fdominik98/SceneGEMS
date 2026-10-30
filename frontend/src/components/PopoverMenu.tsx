import { useEffect, useId, useRef, useState, type ReactNode } from "react";

interface PopoverMenuProps {
  /** The text of the button that opens the menu, or its icon with `iconLabel`. */
  label: ReactNode;
  /** Names the opened group for assistive technology; defaults to a string label. */
  ariaLabel?: string;
  /** Makes the button icon-only: `label` is the icon, this is its name and tooltip (and the group's name). */
  iconLabel?: string;
  /** Which edge of the button the panel lines up with. */
  align?: "start" | "end";
  /** Whether the panel opens below or above the button. */
  placement?: "bottom" | "top";
  className?: string;
  children: ReactNode;
}

/**
 * A button that opens a small panel of options laid over the page, for groups of secondary
 * controls (view options, exports). The button has `aria-expanded`; Escape or a click outside
 * closes the panel and Escape returns focus to the button.
 */
export function PopoverMenu({
  label,
  ariaLabel,
  iconLabel,
  align = "start",
  placement = "bottom",
  className,
  children,
}: PopoverMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`popover-menu${className ? ` ${className}` : ""}`}>
      <button
        ref={buttonRef}
        type="button"
        className={iconLabel ? `popover-menu-button icon-btn${open ? " is-active" : ""}` : "popover-menu-button"}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={iconLabel}
        title={iconLabel}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
        {iconLabel ? null : <span className="popover-menu-chevron" aria-hidden />}
      </button>
      <div
        id={panelId}
        className="popover-menu-panel"
        role="group"
        aria-label={ariaLabel ?? iconLabel ?? (typeof label === "string" ? label : undefined)}
        data-align={align}
        data-placement={placement}
        hidden={!open}
      >
        {children}
      </div>
    </div>
  );
}
