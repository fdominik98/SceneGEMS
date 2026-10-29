import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FullscreenButton } from "./FullscreenButton";
import { useFullscreen } from "./useFullscreen";

// jsdom has no Fullscreen API, which is the case of a browser without it as it is. The other cases stub it on the
// document: the browser's answer to requestFullscreen is up to the test, and entering or leaving sets
// document.fullscreenElement and fires fullscreenchange like a browser.

function Workspace() {
  const workspace = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen(workspace);
  return (
    <div ref={workspace} data-testid="workspace" data-mode={fullscreen.mode}>
      <FullscreenButton fullscreen={fullscreen.mode !== "off"} onToggle={fullscreen.toggle} />
    </div>
  );
}

type Answer = "enter" | "refuse" | "never";

function stubFullscreenApi(answer: Answer) {
  let current: Element | null = null;
  const change = (element: Element | null) => {
    current = element;
    document.dispatchEvent(new Event("fullscreenchange"));
  };
  Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
  Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => current });
  const exitFullscreen = vi.fn(async () => change(null));
  Object.defineProperty(document, "exitFullscreen", { configurable: true, value: exitFullscreen });
  const requestFullscreen = vi.fn(function (this: Element) {
    if (answer === "never") {
      return new Promise<void>(() => {});
    }
    if (answer === "refuse") {
      return Promise.reject(new TypeError("Permissions check failed"));
    }
    change(this);
    return Promise.resolve();
  });
  Object.defineProperty(HTMLElement.prototype, "requestFullscreen", { configurable: true, value: requestFullscreen });
  return { requestFullscreen, exitFullscreen, leaveByBrowser: () => act(() => change(null)) };
}

afterEach(() => {
  for (const name of ["fullscreenEnabled", "fullscreenElement", "exitFullscreen"]) {
    Reflect.deleteProperty(document, name);
  }
  Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
});

const mode = () => screen.getByTestId("workspace").dataset.mode;

describe("useFullscreen", () => {
  it("covers the window without the Fullscreen API and leaves on the button or Escape", async () => {
    const user = userEvent.setup();
    render(<Workspace />);
    expect(mode()).toBe("off");

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(mode()).toBe("window");

    await user.click(screen.getByRole("button", { name: "Exit full screen" }));
    expect(mode()).toBe("off");

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    await user.keyboard("{Escape}");
    expect(mode()).toBe("off");
    expect(screen.getByRole("button", { name: "Full screen" })).toBeInTheDocument();
  });

  it("puts the element on the whole screen when the browser allows it and leaves through the button", async () => {
    const api = stubFullscreenApi("enter");
    const user = userEvent.setup();
    render(<Workspace />);

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(api.requestFullscreen).toHaveBeenCalledTimes(1);
    expect(api.requestFullscreen.mock.contexts[0]).toBe(screen.getByTestId("workspace"));
    expect(mode()).toBe("screen");

    await user.click(screen.getByRole("button", { name: "Exit full screen" }));
    expect(api.exitFullscreen).toHaveBeenCalledTimes(1);
    expect(mode()).toBe("off");
  });

  it("turns off when the browser leaves its full screen by itself", async () => {
    const api = stubFullscreenApi("enter");
    const user = userEvent.setup();
    render(<Workspace />);

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(mode()).toBe("screen");

    api.leaveByBrowser();
    expect(mode()).toBe("off");
    expect(screen.getByRole("button", { name: "Full screen" })).toBeInTheDocument();
  });

  it.each<{ answer: Answer; browser: string }>([
    { answer: "refuse", browser: "refuses" },
    { answer: "never", browser: "never answers" },
  ])("keeps the window covered when the browser $browser", async ({ answer }) => {
    stubFullscreenApi(answer);
    const user = userEvent.setup();
    render(<Workspace />);

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(mode()).toBe("window");
    expect(screen.getByRole("button", { name: "Exit full screen" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(mode()).toBe("off");
  });
});
