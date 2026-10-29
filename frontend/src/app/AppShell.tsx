import { useEffect, useState } from "react";
import "./shell.css";
import "../components/components.css";
import { LeftPane } from "./LeftPane";
import { useUiStore } from "./uiStore";
import { usePersistedState } from "./usePersistedState";
import { WorkbenchSection } from "./WorkbenchSection";
import { usePlaybackStore } from "../domain/playback/playbackStore";
import { ClusterSection } from "../features/cluster/ClusterSection";
import { CampaignsSection } from "../features/campaigns/CampaignsSection";
import { CapabilitiesSection } from "../features/capabilities/CapabilitiesSection";
import { DomainSection } from "../features/domain/DomainSection";
import { HistorySection } from "../features/history/HistorySection";
import { ResultsSection } from "../features/results/ResultsSection";

const APP_TITLE = "SceneGEMS";
const NARROW_QUERY = "(max-width: 800px)";

function isNarrowScreen(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.(NARROW_QUERY).matches === true;
}

/**
 * The frame of the console: the left pane with its sections and the shown section. The
 * workbench stays mounted while another section is shown, so its gateway socket, generation
 * runs and editor state carry on; the cluster sections mount when shown.
 */
export function AppShell() {
  useEffect(() => {
    document.title = APP_TITLE;
  }, []);

  const section = useUiStore((s) => s.section);
  const setSection = useUiStore((s) => s.setSection);
  const workbenchView = useUiStore((s) => s.workbenchView);
  const setWorkbenchView = useUiStore((s) => s.setWorkbenchView);
  // The menu is open on a wide screen and starts closed on a narrow one, where it is a bar at the top.
  const [isLeftMenuCollapsed, setIsLeftMenuCollapsed] = usePersistedState<boolean>(
    "left-menu-collapsed",
    isNarrowScreen
  );
  /** After choosing a destination on a narrow screen, close the menu so the content is visible. */
  const closeMenuWhenNarrow = () => {
    if (isNarrowScreen()) {
      setIsLeftMenuCollapsed(true);
    }
  };
  const [errorSlot, setErrorSlot] = useState<HTMLDivElement | null>(null);

  return (
    <div className="app-shell">
      <div className={`app-body${isLeftMenuCollapsed ? " is-menu-collapsed" : ""}`}>
        <LeftPane
          isCollapsed={isLeftMenuCollapsed}
          onToggleCollapse={() => setIsLeftMenuCollapsed((v) => !v)}
          activeSection={section}
          onSectionSelect={(next) => {
            setSection(next);
            closeMenuWhenNarrow();
          }}
          workbenchView={workbenchView}
          onWorkbenchViewSelect={(view) => {
            if (view === "simulation") {
              usePlaybackStore.getState().requestAutoFit();
            }
            setWorkbenchView(view);
            setSection("workbench");
            closeMenuWhenNarrow();
          }}
        />

        <WorkbenchSection active={section === "workbench"} errorSlot={errorSlot} />
        {section === "cluster" && <ClusterSection />}
        {section === "domain" && <DomainSection />}
        {section === "capabilities" && <CapabilitiesSection />}
        {section === "campaigns" && <CampaignsSection />}
        {section === "history" && <HistorySection />}
        {section === "results" && <ResultsSection />}
      </div>
      <div ref={setErrorSlot} className="app-error-slot" />
    </div>
  );
}
