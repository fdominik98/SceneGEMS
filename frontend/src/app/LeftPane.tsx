export type AppView = "simulation" | "waraps" | "domainConfig" | "sceneGeneration";
export type MenuActive = AppView;

const APP_TITLE = "SceneGEMS";

const MENU_ITEMS: { view: AppView; label: string }[] = [
  { view: "domainConfig", label: "Domain Configuration" },
  { view: "sceneGeneration", label: "Scene Generation" },
  { view: "simulation", label: "Simulation" },
  { view: "waraps", label: "Connect to WARA-PS" },
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
          {MENU_ITEMS.map(({ view, label }) => (
            <button
              key={view}
              className={`left-menu-item${activeMenu === view ? " active" : ""}`}
              onClick={() => onAppViewSelect(view)}
            >
              {label}
            </button>
          ))}
          <a href="/docs/" className="left-menu-item">
            Documentation
          </a>
        </details>
      )}
    </aside>
  );
}
