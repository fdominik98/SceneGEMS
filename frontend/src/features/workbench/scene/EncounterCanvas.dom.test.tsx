import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { OverlayVisibility } from "../../../app/uiStore";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { EncounterCanvas, type EncounterCanvasStream } from "./EncounterCanvas";

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

const LAYERS: OverlayVisibility = { dot: true, velocity: true, safetyRadius: true, trajectory: true, safetyDomain: true, staticAvoidanceDomain: true, maneuveringDomain: true };
const streams: EncounterCanvasStream[] = [
  { key: "preview", label: "Scene", frame: sampleFrames[0]!, frames: [sampleFrames[0]!], colorByActorId: {}, layers: LAYERS },
];

/** What the view is: the scale bar's length and label change with the zoom. */
function viewOf(): string {
  const bar = screen.getByLabelText("Scale bar");
  return `${bar.querySelector("text")?.textContent}|${bar.querySelector("line")?.getAttribute("x2")}`;
}

function show(signals: { fitSignal: number; followSignal: number }, shown: EncounterCanvasStream[] = streams) {
  return <EncounterCanvas streams={shown} layerColumns={[]} {...signals} />;
}

describe("EncounterCanvas fits", () => {
  it("keeps a view the user zoomed on a follow signal, and fits again on a fit signal", () => {
    const { rerender } = render(show({ fitSignal: 0, followSignal: 0 }));
    const fitted = viewOf();

    act(() => {
      fireEvent.wheel(screen.getByRole("img", { name: "Encounter canvas" }), { deltaY: -800, clientX: 300, clientY: 200 });
    });
    const zoomed = viewOf();
    expect(zoomed).not.toBe(fitted);

    rerender(show({ fitSignal: 0, followSignal: 1 }));
    expect(viewOf()).toBe(zoomed);

    rerender(show({ fitSignal: 1, followSignal: 1 }));
    expect(viewOf()).toBe(fitted);
  });

  it("follows a sample that spreads the vessels while the user left the view as the last fit placed it", () => {
    const { rerender } = render(show({ fitSignal: 0, followSignal: 0 }));
    const fitted = viewOf();
    const frame = sampleFrames[0]!;
    const target = frame.statesByActorId.target_1!;
    const spread = { ...frame, statesByActorId: { ...frame.statesByActorId, target_1: { ...target, x: target.x + 20000 } } };
    rerender(show({ fitSignal: 0, followSignal: 1 }, [{ ...streams[0]!, frame: spread, frames: [spread] }]));
    expect(viewOf()).not.toBe(fitted);
  });
});
