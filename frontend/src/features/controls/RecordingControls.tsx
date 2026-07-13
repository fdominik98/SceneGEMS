import { useRef } from "react";
import { useRecordingStore } from "../../domain/playback/recordingStore";

export function RecordingControls() {
  const isRecording = useRecordingStore((s) => s.isRecording);
  const previewCount = useRecordingStore((s) => s.previewRecording.length);
  const simulationCount = useRecordingStore((s) => s.simulationRecording.length);
  const startRecording = useRecordingStore((s) => s.startRecording);
  const stopRecording = useRecordingStore((s) => s.stopRecording);
  const exportRecording = useRecordingStore((s) => s.exportRecording);
  const clearRecording = useRecordingStore((s) => s.clearRecording);
  const importRecordingForReplay = useRecordingStore((s) => s.importRecordingForReplay);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className="recording-controls">
      <h4 className="animation-control-group-title">Record &amp; replay</h4>
      <p className="meta">
        Preview: {previewCount} frames · Simulation: {simulationCount} frames
      </p>
      <div className="toolbar-row">
        {!isRecording ? (
          <button type="button" onClick={startRecording}>
            Start recording
          </button>
        ) : (
          <button type="button" className="primary-btn" onClick={stopRecording}>
            Stop recording
          </button>
        )}
        <button
          type="button"
          disabled={previewCount === 0 && simulationCount === 0}
          onClick={exportRecording}
        >
          Export recording
        </button>
        <button type="button" onClick={clearRecording}>
          Clear
        </button>
        <button type="button" onClick={() => fileInputRef.current?.click()}>
          Import replay
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            void (async () => {
              const text = await file.text();
              const ok = importRecordingForReplay(text);
              if (!ok) {
                window.alert("Could not import recording file.");
              }
            })();
            e.target.value = "";
          }}
        />
      </div>
    </div>
  );
}
