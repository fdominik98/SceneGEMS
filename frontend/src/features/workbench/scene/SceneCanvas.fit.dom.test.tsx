import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { PlaybackStoreContext } from "../../../domain/playback/playbackContext";
import { createPlaybackStore, type PlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { SceneCanvas } from "./SceneCanvas";

/** A ResizeObserver that reports a 600 by 400 canvas at once, so the canvas can fit. */
class SizedResizeObserver {
  private readonly callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element) {
    this.callback([{ target, contentRect: { width: 600, height: 400 } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", SizedResizeObserver);
});

afterAll(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  useUiStore.setState({ sceneViewMode: "cartesian" });
});

const scene = sampleFrames[0]!;
/** Another scene of the same vessels: the target far away. */
function spread(frame: SimulationFrame): SimulationFrame {
  const target = frame.statesByActorId.target_1!;
  return { ...frame, statesByActorId: { ...frame.statesByActorId, target_1: { ...target, x: target.x + 20000 } } };
}

function page(store: PlaybackStore, generatedScene: SimulationFrame) {
  return (
    <PlaybackStoreContext.Provider value={store}>
      <SceneCanvas generatedScene={generatedScene} />
    </PlaybackStoreContext.Provider>
  );
}

/** What the view is: the scale bar's length and label change with the zoom. */
function viewOf(): string {
  const bar = screen.getByLabelText("Scale bar");
  return `${bar.querySelector("text")?.textContent}|${bar.querySelector("line")?.getAttribute("x2")}`;
}

function zoomIn() {
  act(() => {
    fireEvent.wheel(screen.getByRole("img", { name: "Encounter canvas" }), { deltaY: -800, clientX: 300, clientY: 200 });
  });
}

describe("the scene page's fits", () => {
  it("keeps a zoomed view while a generation shows its samples", () => {
    const store = createPlaybackStore();
    act(() => store.getState().setActiveSceneGenerationRequestId("run"));
    const { rerender } = render(page(store, scene));
    zoomIn();
    const zoomed = viewOf();
    rerender(page(store, spread(scene)));
    expect(viewOf()).toBe(zoomed);
  });

  it("keeps a zoomed view when the scene comes back with the monitor's verdicts", () => {
    const store = createPlaybackStore();
    const { rerender } = render(page(store, scene));
    zoomIn();
    const zoomed = viewOf();
    rerender(page(store, { ...scene, ruleResults: [], metrics: undefined }));
    expect(viewOf()).toBe(zoomed);
  });

  it("fits another scene that is loaded", () => {
    const store = createPlaybackStore();
    const { rerender } = render(page(store, scene));
    zoomIn();
    const zoomed = viewOf();
    rerender(page(store, spread(scene)));
    expect(viewOf()).not.toBe(zoomed);
  });
});
