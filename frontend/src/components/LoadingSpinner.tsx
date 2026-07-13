interface LoadingSpinnerProps {
  label?: string;
  size?: "sm" | "md";
}

export function LoadingSpinner({ label = "Loading…", size = "md" }: LoadingSpinnerProps) {
  return (
    <div className={`loading-spinner loading-spinner--${size}`} role="status" aria-live="polite">
      <span className="loading-spinner-ring" aria-hidden />
      <span className="loading-spinner-label">{label}</span>
    </div>
  );
}
