import { describe, expect, it } from "vitest";
import { resolveGlobalErrorMessage } from "./globalErrorMessage";

describe("resolveGlobalErrorMessage", () => {
  it("prefers page-local error over playback error", () => {
    expect(resolveGlobalErrorMessage("Scene generation failed.", "Backend disconnected.")).toBe(
      "Scene generation failed."
    );
  });

  it("falls back to playback error when page-local one is missing", () => {
    expect(resolveGlobalErrorMessage(null, "Failed to connect to WARAPS")).toBe(
      "Failed to connect to WARAPS"
    );
  });

  it("returns null when both error messages are absent", () => {
    expect(resolveGlobalErrorMessage(null, null)).toBeNull();
  });
});
