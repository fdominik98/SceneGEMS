import { create } from "zustand";

export type Theme = "dark" | "light";

/** The inline script of `index.html` reads this key too, to set the theme before the first paint. */
export const THEME_STORAGE_KEY = "scenegems:theme";

export function readStoredTheme(): Theme {
  try {
    return globalThis.localStorage?.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function applyTheme(theme: Theme): void {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = theme;
  }
}

function storeTheme(theme: Theme): void {
  try {
    globalThis.localStorage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Persistence is best-effort: the choice still holds until the page reloads.
  }
}

interface ThemeState {
  theme: Theme;
  toggleTheme: () => void;
}

/** Light or dark mode, kept per browser. The colors themselves are the tokens in `theme.css`. */
export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readStoredTheme(),
  toggleTheme: () => {
    const theme: Theme = get().theme === "dark" ? "light" : "dark";
    storeTheme(theme);
    applyTheme(theme);
    set({ theme });
  },
}));

/** Puts the stored theme on the root element. Every page entry calls it before rendering. */
export function installTheme(): void {
  applyTheme(useThemeStore.getState().theme);
}

/** For what cannot follow a CSS token by itself: React Flow's color mode, CodeMirror's themes, the ship colors. */
export function useTheme(): Theme {
  return useThemeStore((state) => state.theme);
}
