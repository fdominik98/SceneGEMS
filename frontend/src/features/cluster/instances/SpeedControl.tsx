import { SPEED_CHOICES } from "./speedChoices";

interface SpeedControlProps {
  /** The speed this browser asked for. */
  requested: number;
  /** The pace the control node reports (`observed_speed` of the instance), null while it reports none. */
  reported: number | null | undefined;
  disabled?: boolean;
  onChange: (speed: number) => void;
}

/** The pace of an observed simulation, as multiples of real time. The pace changes wall time only. */
export function SpeedControl({ requested, reported, disabled, onChange }: SpeedControlProps) {
  const settled = reported !== null && reported !== undefined && reported === requested;
  return (
    <div className="instances-speed">
      <div className="instances-speed-head">
        <span className="instances-speed-label" id="instances-speed-label">
          Pace
        </span>
        <span className="meta" role="status">
          {reported === null || reported === undefined
            ? "The control node reports no pace yet."
            : settled
              ? `The control node paces the run at ${reported}x real time.`
              : `The control node reports ${reported}x real time, you asked for ${requested}x.`}
        </span>
      </div>
      <div className="instances-speed-choices" role="group" aria-labelledby="instances-speed-label">
        {SPEED_CHOICES.map((speed) => (
          <button
            key={speed}
            type="button"
            className={`instances-speed-choice${speed === requested ? " instances-speed-choice--active" : ""}`}
            aria-pressed={speed === requested}
            disabled={disabled}
            onClick={() => onChange(speed)}
          >
            {speed}x
          </button>
        ))}
      </div>
      <p className="meta">The pace changes how long the run takes, not its result. The latest request counts for everyone watching this run.</p>
    </div>
  );
}
