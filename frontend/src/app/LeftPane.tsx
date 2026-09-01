import type { ReactElement, SVGProps } from "react";

export type AppView =
  | "simulation"
  | "waraps"
  | "domainConfig"
  | "sceneGeneration"
  | "trajectoryGeneration";
export type MenuActive = AppView;

const APP_TITLE = "SceneGEMS";

type IconProps = SVGProps<SVGSVGElement>;

function iconBaseProps(props: IconProps) {
  return {
    className: "left-menu-icon",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

function DomainConfigIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="9" cy="6" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="8" cy="18" r="2" />
    </svg>
  );
}

function SceneGenerationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z" />
      <path d="M18 14l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z" />
    </svg>
  );
}

function TrajectoryGenerationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <circle cx="5" cy="19" r="2" />
      <circle cx="19" cy="5" r="2" />
      <path d="M7 19h6a4 4 0 0 0 4-4V7" strokeDasharray="3 3" />
    </svg>
  );
}

function SimulationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <polygon points="9 7 18 12 9 17 9 7" />
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

function WarapsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M9 7V3M15 7V3" />
      <path d="M7 7h10v4a5 5 0 0 1-10 0V7z" />
      <path d="M12 16v5" />
    </svg>
  );
}

function DocumentationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M6 4h9l4 4v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <path d="M14 4v5h5" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="14" y2="17" />
    </svg>
  );
}

const MENU_ITEMS: { view: AppView; label: string; Icon: (props: IconProps) => ReactElement }[] = [
  { view: "domainConfig", label: "Domain Configuration", Icon: DomainConfigIcon },
  { view: "sceneGeneration", label: "Scene Generation", Icon: SceneGenerationIcon },
  { view: "trajectoryGeneration", label: "Trajectory Generation", Icon: TrajectoryGenerationIcon },
  { view: "simulation", label: "Simulation", Icon: SimulationIcon },
  { view: "waraps", label: "Connect to WARA-PS", Icon: WarapsIcon },
];

interface LeftPaneProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  activeMenu: MenuActive;
  onAppViewSelect: (view: AppView) => void;
}

export function LeftPane({
  isCollapsed,
  onToggleCollapse,
  activeMenu,
  onAppViewSelect,
}: LeftPaneProps) {
  return (
    <aside className={`left-pane${isCollapsed ? " collapsed" : ""}`}>
      <div className="left-pane-brand">
        {isCollapsed ? (
          <img className="left-pane-logo" src="/favicon.svg" alt={APP_TITLE} />
        ) : (
          <>
            <div className="left-pane-brand-header">
              <img className="left-pane-logo" src="/favicon.svg" alt="" aria-hidden />
              <span className="left-pane-brand-title">{APP_TITLE}</span>
            </div>
            <p className="left-pane-brand-subtitle">
              A Scenario Generation and Execution Framework for Simulation-Based Assurance of
              Maritime Autonomous Surface Vehicles
            </p>
          </>
        )}
      </div>
      <div className="left-pane-header">
        <button
          className="left-menu-toggle"
          aria-label="Toggle menu"
          onClick={onToggleCollapse}
        >
          &#9776;
        </button>
      </div>
      {!isCollapsed && (
        <details open className="left-menu-group">
          <summary>Menu</summary>
          {MENU_ITEMS.map(({ view, label, Icon }) => (
            <button
              key={view}
              className={`left-menu-item${activeMenu === view ? " active" : ""}`}
              onClick={() => onAppViewSelect(view)}
            >
              <Icon />
              {label}
            </button>
          ))}
          <a href="/docs/" className="left-menu-item">
            <DocumentationIcon />
            Documentation
          </a>
        </details>
      )}
    </aside>
  );
}
