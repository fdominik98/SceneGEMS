import { usePlaybackStore } from "../../domain/playback/playbackStore";
import { handleResetPlayback } from "./resetPlayback";

interface AnimationPlaybackControlsProps {
  /** Snap the play head to a timestamp (from the owning stream controls). */
  seek: (value: number) => void;
  /** Set playback speed multiplier. */
  setSpeed: (value: number) => void;
  /** Optional label shown above the controls. */
  title?: string;
}

/**
 * The animation playback block (step / play / reset / scrub / speed) shared by the
 * Simulation control panel and the Trajectory Generation preview tab. It operates
 * purely on the preview `frames` stream in `playbackStore`.
 */
export function AnimationPlaybackControls({
  seek,
  setSpeed,
  title = "Playback",
}: AnimationPlaybackControlsProps) {
  const isPlaying = usePlaybackStore((s) => s.isPlaying);
  const speed = usePlaybackStore((s) => s.speed);
  const currentTimestamp = usePlaybackStore((s) => s.currentTimestamp);
  const latestTimestamp = usePlaybackStore((s) => s.latestTimestamp);
  const setPlaying = usePlaybackStore((s) => s.setPlaying);
  const stepBy = usePlaybackStore((s) => s.stepBy);
  const hasFrames = usePlaybackStore((s) => s.frames.length > 0);

  const stepFrameCount = Math.max(1, Math.round(speed));
  const sliderMax = Math.max(1, latestTimestamp, currentTimestamp);

  return (
    <section className="animation-control-group" aria-label="Animation playback controls">
      <h4 className="animation-control-group-title">{title}</h4>
      <div className="toolbar-row">
        <button type="button" disabled={!hasFrames} onClick={() => stepBy(-stepFrameCount)}>
          Step Back
        </button>
        <button type="button" disabled={!hasFrames} onClick={() => setPlaying(!isPlaying)}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          disabled={!hasFrames}
          onClick={() => handleResetPlayback(setPlaying, seek)}
        >
          Reset
        </button>
        <button type="button" disabled={!hasFrames} onClick={() => stepBy(stepFrameCount)}>
          Step Forward
        </button>
      </div>

      <label className="field">
        <span>Animation Time</span>
        <input
          type="range"
          min={0}
          max={sliderMax}
          value={Math.min(currentTimestamp, sliderMax)}
          disabled={!hasFrames}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </label>

      <label className="field">
        <span>Speed ({speed.toFixed(1)}x)</span>
        <input
          type="range"
          min={0.5}
          max={240}
          step={0.5}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        />
      </label>
      <p className="meta animation-control-meta">
        Animation time: {currentTimestamp}s | Latest: {latestTimestamp}s
      </p>
    </section>
  );
}
