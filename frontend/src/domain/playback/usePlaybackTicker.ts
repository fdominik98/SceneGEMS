import { useEffect, useRef } from "react";
import { usePlaybackStore } from "./playbackStore";

/** Smooth playback via requestAnimationFrame (real-time speed multiplier). */
export function usePlaybackTicker() {
  const isPlaying = usePlaybackStore((s) => s.isPlaying);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isPlaying) {
      lastTickRef.current = null;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      return;
    }

    const loop = (now: number) => {
      const state = usePlaybackStore.getState();
      if (!state.isPlaying || state.frames.length === 0) {
        lastTickRef.current = now;
        rafRef.current = requestAnimationFrame(loop);
        return;
      }
      const last = lastTickRef.current ?? now;
      const elapsedSec = (now - last) / 1000;
      lastTickRef.current = now;
      const maxT = state.frames[state.frames.length - 1]!.timestamp;
      const next = Math.min(state.playbackCursor + state.speed * elapsedSec, maxT);
      state.advancePlayback(next);
      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [isPlaying]);
}
