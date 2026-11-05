import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { LeftPane } from "./LeftPane";
import { installTheme, THEME_STORAGE_KEY, useThemeStore } from "./theme";

function renderPane(isCollapsed = false) {
  render(
    <LeftPane
      isCollapsed={isCollapsed}
      onToggleCollapse={() => {}}
      activeSection="workbench"
      onSectionSelect={() => {}}
      workbenchView="sceneGeneration"
      onWorkbenchViewSelect={() => {}}
    />
  );
}

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
