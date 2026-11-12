import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../test/memoryStorage";
import { readStoredTheme, THEME_STORAGE_KEY, useThemeStore } from "./theme";

describe("theme", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", new MemoryStorage());
    useThemeStore.setState({ theme: "dark" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts light without a stored choice", () => {
    expect(readStoredTheme()).toBe("light");
  });

  it("reads a stored dark choice", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredTheme()).toBe("dark");
  });

  it("reads a stored light choice", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readStoredTheme()).toBe("light");
  });

  it("treats an unknown stored value as light", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredTheme()).toBe("light");
  });

  it("stays light when the storage cannot be read", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("denied");
      },
    });
    expect(readStoredTheme()).toBe("light");
  });

  it("toggles and remembers the choice", () => {
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("keeps the choice for the session when the storage cannot be written", () => {
    vi.stubGlobal("localStorage", {
      setItem: () => {
        throw new Error("quota");
      },
    });
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("light");
  });

  it("has index.html start light and its inline script read the same key for dark", () => {
    const html = readFileSync(resolve(__dirname, "../../index.html"), "utf8");
    expect(html).toContain('<html lang="en" data-theme="light">');
    expect(html).toContain(`localStorage.getItem("${THEME_STORAGE_KEY}") === "dark"`);
  });
});
