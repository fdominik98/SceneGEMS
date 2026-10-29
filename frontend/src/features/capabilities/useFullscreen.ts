import { useCallback, useEffect, useState, type RefObject } from "react";

/** Off, covering the browser window (the element's own styles do that), or on the whole screen through the Fullscreen API. */
export type FullscreenMode = "off" | "window" | "screen";

/**
 * Shows the element of `ref` full screen. Turning it on covers the window at once and asks the browser for the whole
 * screen; where the browser refuses or never answers (an iframe without permission, an embedded browser), the window
 * stays covered. Escape, the button or the browser leaving its full screen turn it off.
 */
export function useFullscreen(ref: RefObject<HTMLElement | null>) {
  const [wanted, setWanted] = useState(false);
  const [screen, setScreen] = useState(false);

  useEffect(() => {
    const follow = () => {
      const on = ref.current !== null && document.fullscreenElement === ref.current;
      setScreen(on);
      if (!on) {
        setWanted(false);
      }
    };
    document.addEventListener("fullscreenchange", follow);
    return () => document.removeEventListener("fullscreenchange", follow);
  }, [ref]);

  useEffect(() => {
    if (!wanted) {
      return;
    }
    const leave = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setWanted(false);
      }
    };
    window.addEventListener("keydown", leave);
    return () => window.removeEventListener("keydown", leave);
  }, [wanted]);

  const toggle = useCallback(() => {
    const element = ref.current;
    if (element === null) {
      return;
    }
    if (document.fullscreenElement === element) {
      setWanted(false);
      document.exitFullscreen().catch(() => {});
    } else if (wanted) {
      setWanted(false);
    } else {
      setWanted(true);
      if (document.fullscreenEnabled && typeof element.requestFullscreen === "function") {
        element.requestFullscreen().catch(() => {});
      }
    }
  }, [ref, wanted]);

  const mode: FullscreenMode = screen ? "screen" : wanted ? "window" : "off";
  return { mode, toggle };
}
