import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installOverlayScrollbars } from "./overlayScrollbars";

// jsdom has no layout, so each container gets its sizes, scroll position and box by hand: a 300x200
// scrollport at (100, 50) over content 800px tall, scrolled by 300px. Its thumb track is 200 - 2 * 2 = 196px
// long, the thumb 196 * 200 / 800 = 49px, and it can travel 147px over the 600px of scroll range.

let uninstall: () => void = () => {};

function scrollContainer(overflow = "auto", scrollTop = 300): HTMLDivElement {
  const el = document.createElement("div");
  el.style.overflowX = overflow;
  el.style.overflowY = overflow;
  Object.defineProperties(el, {
    clientWidth: { value: 300 },
    clientHeight: { value: 200 },
    scrollWidth: { value: 300 },
    scrollHeight: { value: 800 },
    scrollTop: { value: scrollTop, writable: true },
  });
  el.getBoundingClientRect = () => DOMRect.fromRect({ x: 100, y: 50, width: 300, height: 200 });
  document.body.appendChild(el);
  return el;
}

function frames(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(".overlay-scrollbars-frame")];
}

function verticalThumb(): HTMLElement {
  return document.querySelector<HTMLElement>(".overlay-scrollbar.is-vertical")!;
}

function scroll(el: Element): void {
  el.dispatchEvent(new Event("scroll"));
  vi.advanceTimersByTime(20);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame"] });
  uninstall = installOverlayScrollbars();
});

afterEach(() => {
  uninstall();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("overlay scrollbars", () => {
  it("draws a thumb over the edge of a container while it scrolls, sized and placed by its scroll position", () => {
    const el = scrollContainer();
    scroll(el);

    const [frame] = frames();
    expect(frame).toHaveClass("is-visible");
    expect(frame.style).toMatchObject({ left: "100px", top: "50px", width: "300px", height: "200px" });
    // 2px in from the right edge, 2px below the top plus 300 / 600 of the 147px of travel.
    expect(verticalThumb().style).toMatchObject({ left: "288px", top: "75.5px", width: "10px", height: "49px" });
    expect(verticalThumb()).toBeVisible();
    expect(document.querySelector(".overlay-scrollbar.is-horizontal")).not.toBeVisible();
  });

  it("shows the thumbs of the containers under a moving pointer", () => {
    const el = scrollContainer();
    const child = document.createElement("p");
    el.appendChild(child);

    child.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerType: "mouse" }));
    vi.advanceTimersByTime(40);

    expect(frames()).toHaveLength(1);
    expect(frames()[0]).toHaveClass("is-visible");
  });

  it("fades the thumbs out once scrolling rests and then removes them", () => {
    scroll(scrollContainer());

    vi.advanceTimersByTime(1100);
    expect(frames()[0]).not.toHaveClass("is-visible");
    vi.advanceTimersByTime(400);
    expect(frames()).toHaveLength(0);
  });

  it("keeps the thumbs while the pointer is over one", () => {
    scroll(scrollContainer());
    verticalThumb().dispatchEvent(new PointerEvent("pointerenter"));

    vi.advanceTimersByTime(5000);
    expect(frames()[0]).toHaveClass("is-visible");
  });

  it("scrolls the container when its thumb is dragged", () => {
    const el = scrollContainer();
    scroll(el);

    verticalThumb().dispatchEvent(new PointerEvent("pointerdown", { button: 0, pointerId: 1, clientY: 100, bubbles: true }));
    expect(verticalThumb()).toHaveClass("is-active");
    // 49px of the 147px of travel is a third of the 600px of scroll range.
    window.dispatchEvent(new PointerEvent("pointermove", { pointerId: 1, clientY: 149 }));
    expect(el.scrollTop).toBeCloseTo(500);

    window.dispatchEvent(new PointerEvent("pointerup", { pointerId: 1, clientY: 149 }));
    expect(verticalThumb()).not.toHaveClass("is-active");
    window.dispatchEvent(new PointerEvent("pointermove", { pointerId: 1, clientY: 250 }));
    expect(el.scrollTop).toBeCloseTo(500);
  });

  it("passes the wheel over a thumb on to its container", () => {
    const el = scrollContainer();
    el.scrollBy = vi.fn();
    scroll(el);

    const wheel = new WheelEvent("wheel", { deltaY: 3, deltaMode: WheelEvent.DOM_DELTA_LINE, cancelable: true });
    verticalThumb().dispatchEvent(wheel);

    expect(el.scrollBy).toHaveBeenCalledWith({ left: 0, top: 48 });
    expect(wheel.defaultPrevented).toBe(true);
  });

  it("draws nothing for a container that clips its overflow instead of scrolling", () => {
    scroll(scrollContainer("hidden"));

    expect(document.querySelector(".overlay-scrollbars-frame.is-visible")).toBeNull();
  });

  it("drops the thumbs of a container that left the page", () => {
    const el = scrollContainer();
    scroll(el);
    el.remove();
    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(20);

    expect(frames()).toHaveLength(0);
  });

  it("removes its layer when uninstalled", () => {
    scroll(scrollContainer());
    uninstall();
    uninstall = () => {};

    expect(document.querySelector(".overlay-scrollbars")).toBeNull();
  });
});
