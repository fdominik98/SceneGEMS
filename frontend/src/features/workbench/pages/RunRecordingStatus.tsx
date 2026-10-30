import "./pages.css";
import { useRunRecordingStore } from "./runRecordingStore";
import { openInWorkbench } from "./workbenchTarget";

/**
 * Whether the gateway records the live session (design doc 6.4): recording, saved with a link
 * that opens the recorded entry on this page as a replay, failed, or unavailable.
 */
export function RunRecordingStatus() {
  const status = useRunRecordingStore((s) => s.status);
  const campaignId = useRunRecordingStore((s) => s.campaignId);
  const caseId = useRunRecordingStore((s) => s.caseId);
  const message = useRunRecordingStore((s) => s.message);

  if (status === null) {
    return null;
  }
  if (status === "recording") {
    return (
      <p className="step-line page-entry-status" role="status">
        Recording the live session{campaignId ? ` as entry ${campaignId}` : ""}.
      </p>
    );
  }
  if (status === "saved") {
    return (
      <p className="step-line page-entry-status" role="status">
        The live session is saved{campaignId ? ` as entry ${campaignId}` : ""}.{" "}
        {campaignId !== null && caseId !== null ? (
          <button type="button" className="link-btn" onClick={() => openInWorkbench({ page: "simulation", campaignId, caseId, step: "simulation" })}>
            Open the recorded run
          </button>
        ) : null}
      </p>
    );
  }
  if (status === "failed") {
    return (
      <p className="step-line error page-entry-status" role="alert">
        The live session could not be recorded{message ? `: ${message}` : "."}
      </p>
    );
  }
  return (
    <p className="step-line page-entry-status" role="status">
      Live sessions are not recorded here{message ? `: ${message}` : "."}
    </p>
  );
}
