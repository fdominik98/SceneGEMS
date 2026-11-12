import type { ReactElement, SVGProps } from "react";
import { Disclosure } from "../components/Disclosure";
import { useClusterStore } from "../domain/cluster/clusterStore";
import { useTheme, useThemeStore } from "./theme";
import type { AppSection, WorkbenchView } from "./uiStore";

const APP_TITLE = "SceneGEMS";

type IconProps = SVGProps<SVGSVGElement>;

function iconBaseProps(props: IconProps) {
  return {
    className: "left-nav-icon",
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

function DesignSpaceExplorationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <circle cx="17.5" cy="17.5" r="3" />
      <line x1="19.7" y1="19.7" x2="22" y2="22" />
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

function ConnectionsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M9 7V3M15 7V3" />
      <path d="M7 7h10v4a5 5 0 0 1-10 0V7z" />
      <path d="M12 16v5" />
    </svg>
  );
}

function ClusterIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <rect x="4" y="3" width="16" height="5" rx="1" />
      <rect x="4" y="10" width="16" height="5" rx="1" />
      <rect x="4" y="17" width="16" height="4" rx="1" />
      <path d="M8 5.5h.01M8 12.5h.01M8 19h.01" />
    </svg>
  );
}

function CapabilitiesIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <rect x="3" y="4" width="6" height="5" rx="1" />
      <rect x="15" y="3" width="6" height="5" rx="1" />
      <rect x="9" y="16" width="6" height="5" rx="1" />
      <path d="M9 6.5h6M6 9v3.5a2 2 0 0 0 2 2h1M18 8v4.5a2 2 0 0 1-2 2h-1" />
    </svg>
  );
}

function CampaignsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M5 21V4" />
      <path d="M5 4h11l-2 4 2 4H5" />
    </svg>
  );
}

function HistoryIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function ResultsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M4 20h16" />
      <rect x="6" y="11" width="3" height="7" />
      <rect x="11" y="6" width="3" height="12" />
      <rect x="16" y="13" width="3" height="5" />
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

function SunIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
    </svg>
  );
}

function MenuIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
    </svg>
  );
}

interface NavEntry<T> {
  id: T;
  label: string;
  /** One plain phrase on what the destination is for. */
  hint: string;
  Icon: (props: IconProps) => ReactElement;
}

/** The workbench views in the order of the workflow: explore the design space, generate a scene, plan trajectories, simulate. */
const WORKBENCH_ITEMS: NavEntry<WorkbenchView>[] = [
  { id: "designSpaceExploration", label: "Design Space Exploration", hint: "Find the scenario classes", Icon: DesignSpaceExplorationIcon },
  { id: "sceneGeneration", label: "Scene Generation", hint: "Create a starting scene", Icon: SceneGenerationIcon },
  { id: "trajectoryGeneration", label: "Trajectory Generation", hint: "Plan the vessel routes", Icon: TrajectoryGenerationIcon },
  { id: "simulation", label: "Simulation", hint: "Watch the scenario play", Icon: SimulationIcon },
  { id: "connections", label: "Connections", hint: "MQTT broker of real vessels, reference area", Icon: ConnectionsIcon },
];

const CLUSTER_ITEMS: NavEntry<AppSection>[] = [
  { id: "cluster", label: "Cluster", hint: "Machines and what they run", Icon: ClusterIcon },
  { id: "domain", label: "Domain Configuration", hint: "Rules and vessel types of the cluster", Icon: DomainConfigIcon },
  { id: "capabilities", label: "Capabilities", hint: "What the system can run", Icon: CapabilitiesIcon },
  { id: "campaigns", label: "Campaigns", hint: "Define and start a campaign", Icon: CampaignsIcon },
  { id: "history", label: "Campaign History", hint: "Campaigns and runs, with outputs", Icon: HistoryIcon },
  { id: "results", label: "Results", hint: "Review finished runs", Icon: ResultsIcon },
];

function ClusterSelect() {
  const clusters = useClusterStore((s) => s.clusters);
  const selectedClusterId = useClusterStore((s) => s.selectedClusterId);
  const selectCluster = useClusterStore((s) => s.selectCluster);
  return (
    <label className="left-pane-cluster">
      <span className="left-pane-cluster-label">Active cluster</span>
      <select
        value={selectedClusterId ?? ""}
        onChange={(e) => selectCluster(e.target.value === "" ? null : e.target.value)}
      >
        <option value="">{clusters.length === 0 ? "No clusters yet" : "None selected"}</option>
        {clusters.map((cluster) => (
          <option key={cluster.id} value={cluster.id}>
            {cluster.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Names the mode a click switches to, as a row of the footer (an icon with a tooltip on the rail). */
function ThemeToggle() {
  const theme = useTheme();
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const label = theme === "dark" ? "Light mode" : "Dark mode";
  const Icon = theme === "dark" ? SunIcon : MoonIcon;
  return (
    <button type="button" className="left-nav-item left-nav-link" onClick={toggleTheme} title={label} aria-label={label}>
      <Icon />
      <span className="left-nav-text">
        <span className="left-nav-label">{label}</span>
      </span>
    </button>
  );
}

interface NavButtonProps {
  entry: NavEntry<string>;
  active: boolean;
  onSelect: () => void;
}

function NavButton({ entry, active, onSelect }: NavButtonProps) {
  const { label, hint, Icon } = entry;
  return (
    <button
      type="button"
      className={`left-nav-item${active ? " active" : ""}`}
      onClick={onSelect}
      aria-current={active ? "page" : undefined}
      aria-label={label}
      title={label}
    >
      <Icon />
      <span className="left-nav-text">
        <span className="left-nav-label">{label}</span>
        <span className="left-nav-hint">{hint}</span>
      </span>
    </button>
  );
}

interface LeftPaneProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  activeSection: AppSection;
  onSectionSelect: (section: AppSection) => void;
  workbenchView: WorkbenchView;
  /** Selecting a workbench view also shows the workbench section. */
  onWorkbenchViewSelect: (view: WorkbenchView) => void;
}

/**
 * The main navigation. Expanded it shows each destination with a plain-language hint; collapsed
 * it is an icon rail (names stay as tooltips and accessible names), so every section is one
 * click away in both states. On narrow screens it becomes a bar at the top.
 */
export function LeftPane({
  isCollapsed,
  onToggleCollapse,
  activeSection,
  onSectionSelect,
  workbenchView,
  onWorkbenchViewSelect,
}: LeftPaneProps) {
  const workbenchActive = activeSection === "workbench";
  return (
    <aside className={`left-pane${isCollapsed ? " collapsed" : ""}`}>
      <div className="left-pane-top">
        <div className="left-pane-brand">
          <img className="left-pane-logo" src="/favicon.svg" alt="" aria-hidden />
          <span className="left-pane-brand-title">{APP_TITLE}</span>
        </div>
        <button
          type="button"
          className="left-pane-toggle"
          onClick={onToggleCollapse}
          aria-expanded={!isCollapsed}
          aria-controls="main-navigation"
          aria-label={isCollapsed ? "Show menu labels" : "Collapse menu"}
          title={isCollapsed ? "Show menu labels" : "Collapse menu"}
        >
          <MenuIcon />
        </button>
      </div>
      {!isCollapsed && (
        <Disclosure
          id="left-pane:about"
          variant="link"
          headingLevel={null}
          title="About SceneGEMS"
          className="left-pane-about"
        >
          A Scenario Generation and Execution Framework for Simulation-Based Assurance of Maritime
          Autonomous Surface Vehicles.
        </Disclosure>
      )}
      <nav id="main-navigation" className="left-nav" aria-label="Main">
        <p className="left-nav-heading">Workbench</p>
        <div className="left-nav-group">
          {WORKBENCH_ITEMS.map((entry) => (
            <NavButton
              key={entry.id}
              entry={entry}
              active={workbenchActive && workbenchView === entry.id}
              onSelect={() => onWorkbenchViewSelect(entry.id)}
            />
          ))}
        </div>
        <p className="left-nav-heading">Cluster</p>
        <div className="left-nav-group">
          {CLUSTER_ITEMS.map((entry) => (
            <NavButton
              key={entry.id}
              entry={entry}
              active={activeSection === entry.id}
              onSelect={() => onSectionSelect(entry.id)}
            />
          ))}
        </div>
      </nav>
      <div className="left-pane-footer">
        {!isCollapsed && <ClusterSelect />}
        <ThemeToggle />
        <a href="/docs/" className="left-nav-item left-nav-link" title="Documentation" aria-label="Documentation">
          <DocumentationIcon />
          <span className="left-nav-text">
            <span className="left-nav-label">Documentation</span>
          </span>
        </a>
      </div>
    </aside>
  );
}
