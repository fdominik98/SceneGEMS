/** The graph's full screen switch, drawn over the top right corner of the canvas. */
export function FullscreenButton({ fullscreen, onToggle }: { fullscreen: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="cap-fullscreen" title={fullscreen ? "Leave full screen (Esc)" : "Show the graph and its details on the whole screen"} onClick={onToggle}>
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden focusable="false">
        <path
          d={fullscreen ? "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" : "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {fullscreen ? "Exit full screen" : "Full screen"}
    </button>
  );
}
