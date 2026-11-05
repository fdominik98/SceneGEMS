import type { ReactNode } from "react";

/**
 * Line icons for buttons that only act (fit, hide a panel, export) and for the rows of the
 * layer menu. 24 unit grid, drawn in `currentColor`, hidden from assistive technology: the
 * button that holds one carries the name.
 */
function Icon({ size = 20, children }: { size?: number; children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

interface IconProps {
  size?: number;
}

export function CloseIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}

export function FitViewIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
      <circle cx="12" cy="12" r="2.2" />
    </Icon>
  );
}

/** North up: a compass needle with its north half filled. */
export function NorthUpIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 5l3 7h-6z" fill="currentColor" />
      <path d="M9 12l3 7 3-7" />
    </Icon>
  );
}

/** Head up: the own ship's bow at the top. */
export function HeadUpIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M12 3l5 7v10H7V10z" />
      <path d="M10 14h4" />
    </Icon>
  );
}

export function LayersIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M12 4l9 5-9 5-9-5z" />
      <path d="M3 13.5l9 5 9-5" />
    </Icon>
  );
}

/** The nautical map (a folded chart). */
export function MapIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z" />
      <path d="M9 4v14M15 6v14" />
    </Icon>
  );
}

/** The encounter canvas (a radar display). */
export function RadarIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 12l6.4-6.4" />
    </Icon>
  );
}

export function DownloadIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
    </Icon>
  );
}

/** Hide the panel on the right: the panel's edge with an arrow pushing it out. */
export function PanelRightCloseIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16M8 9l3 3-3 3" />
    </Icon>
  );
}

/** Show the panel on the right: the arrow pulls it back in. */
export function PanelRightOpenIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16M11 9l-3 3 3 3" />
    </Icon>
  );
}

/** The rule timeline: rows of bars over time. */
export function TimelineIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M4 7h9M4 12h14M4 17h6" />
      <path d="M17 4v16" strokeDasharray="2 2.5" />
    </Icon>
  );
}

export function EyeIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.8" />
    </Icon>
  );
}

export function HullIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M12 3l5 8v10H7V11z" fill="currentColor" fillOpacity={0.35} />
    </Icon>
  );
}

export function VectorIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M4 20L20 4M13 4h7v7" />
      <path d="M8 13.5l2.5 2.5M12 9.5l2.5 2.5" />
    </Icon>
  );
}

export function TrackIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M3 19c4 0 5-6 9-7" />
      <path d="M12 12c4-1 5-6 9-7" strokeDasharray="2.5 2.5" />
    </Icon>
  );
}

export function SafetyDomainIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <ellipse cx="12" cy="12" rx="6.5" ry="9.5" strokeDasharray="3 2.2" />
      <path d="M12 8l2.5 6h-5z" fill="currentColor" />
    </Icon>
  );
}

export function CorridorIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <path d="M3 17l5-9h8l5 9z" strokeDasharray="3 2.2" />
    </Icon>
  );
}

export function StaticDomainIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="8.5" strokeDasharray="0.1 3.2" strokeWidth={2.4} />
    </Icon>
  );
}

export function SafetyRadiusIcon({ size }: IconProps) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 12h8.5" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
    </Icon>
  );
}
