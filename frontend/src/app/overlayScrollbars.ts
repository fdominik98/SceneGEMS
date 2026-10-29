import "./overlayScrollbars.css";

// Overlay scrollbars for the whole console. overlayScrollbars.css hides the native scrollbars, so they take
// no room, and this draws a thin thumb over the edge of a scroll container while it scrolls or the pointer
// moves over it. The thumb widens under the pointer, can be dragged, and passes the wheel on to its
// container; keys, wheel and touch scroll natively as before. Thumbs live in one fixed layer on the body,
// clipped to the part of their container that is visible, and are removed once they fade out.

type Axis = "y" | "x";

export interface ThumbGeometry {
  offset: number;
  length: number;
}

/** Room the thumb's hit area takes across the container's edge; the visible pill is narrower (CSS). */
export const THUMB_THICKNESS = 10;
/** Gap between the thumb and the container's edges. */
export const THUMB_INSET = 2;
export const THUMB_MIN_LENGTH = 28;
/** How long thumbs stay after the last scroll or pointer move. */
const HIDE_DELAY_MS = 1100;
/** Matches the fade-out transition in overlayScrollbars.css. */
const FADE_MS = 400;

/**
 * Where the thumb sits along a track of `track` px, for a scrollport `client` px long over content
 * `scroll` px long that is scrolled by `position` px. Null when nothing overflows.
 */
export function thumbGeometry(
  client: number,
  scroll: number,
  position: number,
  track: number,
  minLength = THUMB_MIN_LENGTH
): ThumbGeometry | null {
  const range = scroll - client;
  if (range < 1 || track <= 0) {
    return null;
  }
  const length = Math.min(track, Math.max(minLength, (track * client) / scroll));
  const ratio = Math.min(1, Math.max(0, position / range));
  return { offset: ratio * (track - length), length };
}

interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface Bar {
  axis: Axis;
  thumb: HTMLDivElement;
  /** Pixels the thumb can travel along its track, from the latest layout; drag maps onto it. */
  travel: number;
}

interface Track {
  el: Element;
  frame: HTMLDivElement;
  bars: Record<Axis, Bar>;
  hovered: boolean;
  dragging: boolean;
  hideTimer: number;
  removeTimer: number;
}

const SCROLLING_OVERFLOW = new Set(["auto", "scroll", "overlay"]);

function scrollsOn(el: Element, axis: Axis): boolean {
  const overflowing = axis === "y" ? el.scrollHeight - el.clientHeight >= 1 : el.scrollWidth - el.clientWidth >= 1;
  if (!overflowing) {
    return false;
  }
  if (el === document.scrollingElement) {
    return true;
  }
  const style = getComputedStyle(el);
  return SCROLLING_OVERFLOW.has(axis === "y" ? style.overflowY : style.overflowX);
}

function intersect(a: Rect, b: Rect): Rect {
  return {
    left: Math.max(a.left, b.left),
    top: Math.max(a.top, b.top),
    right: Math.min(a.right, b.right),
    bottom: Math.min(a.bottom, b.bottom),
  };
}

/** The padding box of `el` in viewport coordinates: the area its content scrolls in. */
function scrollport(el: Element): Rect {
  if (el === document.scrollingElement) {
    const root = document.documentElement;
    return { left: 0, top: 0, right: root.clientWidth, bottom: root.clientHeight };
  }
  const box = el.getBoundingClientRect();
  const left = box.left + el.clientLeft;
  const top = box.top + el.clientTop;
  return { left, top, right: left + el.clientWidth, bottom: top + el.clientHeight };
}

/** The part of `rect` not clipped away by the viewport or by an ancestor of `el` that clips. */
function visiblePart(el: Element, rect: Rect): Rect {
  let visible = intersect(rect, { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight });
  for (let parent = el.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    const style = getComputedStyle(parent);
    if (style.display !== "contents" && (style.overflowX !== "visible" || style.overflowY !== "visible")) {
      visible = intersect(visible, scrollport(parent));
    }
    if (style.position === "fixed") {
      break;
    }
  }
  return visible;
}

/** Wheel deltas in pixels, whatever unit the event was given in. */
function wheelPixels(event: WheelEvent, el: Element): { left: number; top: number } {
  const scale =
    event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? el.clientHeight : 1;
  return { left: event.deltaX * scale, top: event.deltaY * scale };
}

/** Shows overlay scrollbars on every scroll container of the page. Returns the function that removes them. */
export function installOverlayScrollbars(): () => void {
  const layer = document.createElement("div");
  layer.className = "overlay-scrollbars";
  layer.setAttribute("aria-hidden", "true");
  document.body.appendChild(layer);

  const tracks = new Map<Element, Track>();
  const dirty = new Set<Track>();
  let layoutFrame = 0;
  let pointerFrame = 0;
  let pointerTarget: Element | null = null;

  function scheduleHide(track: Track): void {
    window.clearTimeout(track.hideTimer);
    window.clearTimeout(track.removeTimer);
    if (track.hovered || track.dragging) {
      return;
    }
    track.hideTimer = window.setTimeout(() => {
      track.frame.classList.remove("is-visible");
      track.removeTimer = window.setTimeout(() => dropTrack(track), FADE_MS);
    }, HIDE_DELAY_MS);
  }

  function dropTrack(track: Track): void {
    window.clearTimeout(track.hideTimer);
    window.clearTimeout(track.removeTimer);
    track.frame.remove();
    tracks.delete(track.el);
    dirty.delete(track);
  }

  function createBar(track: Track, axis: Axis): Bar {
    const thumb = document.createElement("div");
    thumb.className = `overlay-scrollbar is-${axis === "y" ? "vertical" : "horizontal"}`;
    const bar: Bar = { axis, thumb, travel: 0 };

    thumb.addEventListener("pointerenter", () => {
      track.hovered = true;
      scheduleHide(track);
    });
    thumb.addEventListener("pointerleave", () => {
      track.hovered = false;
      scheduleHide(track);
    });
    thumb.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        track.el.scrollBy(wheelPixels(event, track.el));
      },
      { passive: false }
    );
    thumb.addEventListener("pointerdown", (event) => startDrag(track, bar, event));
    track.frame.appendChild(thumb);
    return bar;
  }

  function startDrag(track: Track, bar: Bar, event: PointerEvent): void {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const el = track.el;
    const vertical = bar.axis === "y";
    const startPointer = vertical ? event.clientY : event.clientX;
    const startScroll = vertical ? el.scrollTop : el.scrollLeft;
    const range = vertical ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
    const pxPerPx = bar.travel > 0 ? range / bar.travel : 0;

    track.dragging = true;
    scheduleHide(track);
    bar.thumb.classList.add("is-active");
    document.documentElement.classList.add("is-dragging-scrollbar");

    const onMove = (move: PointerEvent): void => {
      if (move.pointerId !== event.pointerId) {
        return;
      }
      const scrolled = startScroll + ((vertical ? move.clientY : move.clientX) - startPointer) * pxPerPx;
      if (vertical) {
        el.scrollTop = scrolled;
      } else {
        el.scrollLeft = scrolled;
      }
    };
    const onEnd = (end: PointerEvent): void => {
      if (end.pointerId !== event.pointerId) {
        return;
      }
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
      window.removeEventListener("pointercancel", onEnd);
      track.dragging = false;
      bar.thumb.classList.remove("is-active");
      document.documentElement.classList.remove("is-dragging-scrollbar");
      scheduleHide(track);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onEnd);
    window.addEventListener("pointercancel", onEnd);
  }

  function trackFor(el: Element): Track {
    let track = tracks.get(el);
    if (!track) {
      const frame = document.createElement("div");
      frame.className = "overlay-scrollbars-frame";
      track = { el, frame, bars: {} as Record<Axis, Bar>, hovered: false, dragging: false, hideTimer: 0, removeTimer: 0 };
      track.bars = { y: createBar(track, "y"), x: createBar(track, "x") };
      layer.appendChild(frame);
      tracks.set(el, track);
    }
    return track;
  }

  function markDirty(track: Track): void {
    dirty.add(track);
    if (!layoutFrame) {
      layoutFrame = window.requestAnimationFrame(flushLayout);
    }
  }

  function reveal(el: Element): void {
    const track = trackFor(el);
    markDirty(track);
    scheduleHide(track);
  }

  function layoutBar(bar: Bar, geometry: ThumbGeometry | null, port: Rect, origin: Rect, crossGap: number): void {
    const { thumb } = bar;
    if (!geometry) {
      thumb.hidden = true;
      bar.travel = 0;
      return;
    }
    thumb.hidden = false;
    const trackLength = bar.axis === "y" ? port.bottom - port.top - 2 * THUMB_INSET - crossGap : port.right - port.left - 2 * THUMB_INSET - crossGap;
    bar.travel = trackLength - geometry.length;
    if (bar.axis === "y") {
      thumb.style.left = `${port.right - THUMB_INSET - THUMB_THICKNESS - origin.left}px`;
      thumb.style.top = `${port.top + THUMB_INSET + geometry.offset - origin.top}px`;
      thumb.style.width = `${THUMB_THICKNESS}px`;
      thumb.style.height = `${geometry.length}px`;
    } else {
      thumb.style.left = `${port.left + THUMB_INSET + geometry.offset - origin.left}px`;
      thumb.style.top = `${port.bottom - THUMB_INSET - THUMB_THICKNESS - origin.top}px`;
      thumb.style.width = `${geometry.length}px`;
      thumb.style.height = `${THUMB_THICKNESS}px`;
    }
  }

  function layoutTrack(track: Track): void {
    const { el, frame } = track;
    if (!el.isConnected) {
      dropTrack(track);
      return;
    }
    const scrollsY = scrollsOn(el, "y");
    const scrollsX = scrollsOn(el, "x");
    const port = scrollport(el);
    const visible = visiblePart(el, port);
    if ((!scrollsY && !scrollsX) || visible.right <= visible.left || visible.bottom <= visible.top) {
      frame.classList.remove("is-visible");
      return;
    }

    frame.style.left = `${visible.left}px`;
    frame.style.top = `${visible.top}px`;
    frame.style.width = `${visible.right - visible.left}px`;
    frame.style.height = `${visible.bottom - visible.top}px`;

    // With both bars shown, each track stops short of the other so the thumbs never cross in the corner.
    const crossGap = scrollsY && scrollsX ? THUMB_THICKNESS : 0;
    const height = port.bottom - port.top;
    const width = port.right - port.left;
    layoutBar(
      track.bars.y,
      scrollsY ? thumbGeometry(el.clientHeight, el.scrollHeight, el.scrollTop, height - 2 * THUMB_INSET - crossGap) : null,
      port,
      visible,
      crossGap
    );
    layoutBar(
      track.bars.x,
      scrollsX ? thumbGeometry(el.clientWidth, el.scrollWidth, el.scrollLeft, width - 2 * THUMB_INSET - crossGap) : null,
      port,
      visible,
      crossGap
    );
    frame.classList.add("is-visible");
  }

  function flushLayout(): void {
    layoutFrame = 0;
    const pending = [...dirty];
    dirty.clear();
    pending.forEach(layoutTrack);
  }

  function flushPointer(): void {
    pointerFrame = 0;
    const target = pointerTarget;
    pointerTarget = null;
    if (!target || layer.contains(target)) {
      return;
    }
    for (let el: Element | null = target; el; el = el.parentElement) {
      if (scrollsOn(el, "y") || scrollsOn(el, "x")) {
        reveal(el);
      }
    }
  }

  const onScroll = (event: Event): void => {
    const target = event.target === document ? document.scrollingElement : event.target;
    if (target instanceof Element) {
      reveal(target);
    }
  };
  const onPointerMove = (event: PointerEvent): void => {
    if (event.pointerType === "touch" || !(event.target instanceof Element)) {
      return;
    }
    pointerTarget = event.target;
    if (!pointerFrame) {
      pointerFrame = window.requestAnimationFrame(flushPointer);
    }
  };
  const onResize = (): void => {
    tracks.forEach(markDirty);
  };

  document.addEventListener("scroll", onScroll, { capture: true, passive: true });
  document.addEventListener("pointermove", onPointerMove, { capture: true, passive: true });
  window.addEventListener("resize", onResize, { passive: true });

  return () => {
    document.removeEventListener("scroll", onScroll, { capture: true });
    document.removeEventListener("pointermove", onPointerMove, { capture: true });
    window.removeEventListener("resize", onResize);
    window.cancelAnimationFrame(layoutFrame);
    window.cancelAnimationFrame(pointerFrame);
    [...tracks.values()].forEach(dropTrack);
    document.documentElement.classList.remove("is-dragging-scrollbar");
    layer.remove();
  };
}
