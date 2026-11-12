import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LeftPane } from "./LeftPane";
import type { SystemStatus } from "./systemStatus";
import { installTheme, THEME_STORAGE_KEY, useThemeStore } from "./theme";
import type { AppSection } from "./uiStore";

function renderPane(isCollapsed = false, system?: SystemStatus, onSectionSelect: (section: AppSection) => void = () => {}) {
  render(
    <LeftPane
      isCollapsed={isCollapsed}
      onToggleCollapse={() => {}}
      activeSection="workbench"
      onSectionSelect={onSectionSelect}
      workbenchView="sceneGeneration"
      onWorkbenchViewSelect={() => {}}
      system={system}
    />
  );
}

const BUSY_SYSTEM: SystemStatus = {
  cluster: { tone: "ok", label: "Connected", detail: "1 of 1 worker node online, 2 of 5 slots in use" },
  steps: { trajectoryGeneration: { tone: "busy", label: "Running" }, sceneGeneration: { tone: "info", label: "Shows a result" } },
  runningEntries: 2,
};

describe("LeftPane system state", () => {
  it("shows how the selected cluster is doing and opens the Cluster section from it", async () => {
    const user = userEvent.setup();
    const onSectionSelect = vi.fn();
    renderPane(false, BUSY_SYSTEM, onSectionSelect);

    const status = screen.getByRole("button", { name: /: Connected, 1 of 1 worker node online, 2 of 5 slots in use$/ });
    expect(status).toHaveTextContent("Connected");
    expect(status).toHaveTextContent("1 of 1 worker node online, 2 of 5 slots in use");
    await user.click(status);
    expect(onSectionSelect).toHaveBeenCalledWith("cluster");
  });

  it("says that no cluster is selected when nothing is known of the system", () => {
    renderPane();
    expect(screen.getByRole("button", { name: /: No cluster selected$/ })).toBeVisible();
  });

  it("marks the workbench pages that run or show a result, and no other", () => {
    renderPane(false, BUSY_SYSTEM);
    expect(screen.getByRole("button", { name: "Trajectory Generation" })).toHaveAccessibleDescription("Running");
    expect(screen.getByRole("button", { name: "Scene Generation" })).toHaveAccessibleDescription("Shows a result");
    // an unmarked destination is described by its hint alone
    expect(screen.getByRole("button", { name: "Simulation" })).toHaveAccessibleDescription("Simulation: Watch the scenario play");
    expect(screen.getByRole("button", { name: "Connections" })).toHaveAccessibleDescription("Connections: Broker and reference area");
  });

  it("counts the running entries on Campaign History, and shows no count when none runs", () => {
    renderPane(false, BUSY_SYSTEM);
    const history = screen.getByRole("button", { name: "Campaign History" });
    expect(history).toHaveAccessibleDescription("2 entries running");
    expect(history).toHaveTextContent("2");
  });

  it("leaves Campaign History unmarked while no entry runs", () => {
    renderPane(false, { ...BUSY_SYSTEM, runningEntries: 0 });
    expect(screen.getByRole("button", { name: "Campaign History" })).toHaveAccessibleDescription("Campaign History: Every campaign and run");
  });

  it("keeps the cluster's state on the collapsed rail as a dot with its words", () => {
    renderPane(true, BUSY_SYSTEM);
    expect(screen.getByRole("button", { name: /: Connected, 1 of 1 worker node online, 2 of 5 slots in use$/ })).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});

describe("LeftPane theme toggle", () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: "dark" });
    installTheme();
  });

  it("switches to light mode and back, naming the mode a click switches to", async () => {
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Light mode" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    await user.click(screen.getByRole("button", { name: "Dark mode" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("stays reachable on the collapsed icon rail", () => {
    renderPane(true);
    expect(screen.getByRole("button", { name: "Light mode" })).toBeVisible();
  });
});
