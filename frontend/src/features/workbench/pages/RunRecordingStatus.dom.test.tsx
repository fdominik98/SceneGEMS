import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { parseServerMessage } from "../../../domain/simulation/protocol";
import { sampleRunRecordingMessages } from "../../../test/fixtures/historyViews";
import { RunRecordingStatus } from "./RunRecordingStatus";
import { useRunRecordingStore } from "./runRecordingStore";
import { useWorkbenchTargetStore } from "./workbenchTarget";

function report(index: number) {
  const message = parseServerMessage(sampleRunRecordingMessages[index]);
  if (message.kind !== "run_recording") {
    throw new Error("not a run_recording message");
  }
  useRunRecordingStore.getState().report(message);
}

beforeEach(() => {
  useRunRecordingStore.getState().clear();
  useWorkbenchTargetStore.setState({ pending: {} });
});

describe("RunRecordingStatus in the DOM", () => {
  it("shows nothing before the gateway says anything", () => {
    const { container } = render(<RunRecordingStatus />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says the session is recorded, then opens the saved entry on the simulation page", async () => {
    const user = userEvent.setup();
    report(0);
    render(<RunRecordingStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Recording the live session as entry wb3.");
    report(1);
    await user.click(await screen.findByRole("button", { name: "Open the recorded run" }));
    expect(useWorkbenchTargetStore.getState().pending.simulation).toEqual({ page: "simulation", campaignId: "wb3", caseId: 1, step: "simulation" });
    expect(useUiStore.getState().workbenchView).toBe("simulation");
  });

  it("says why a recording failed or is not made", () => {
    report(2);
    const { rerender } = render(<RunRecordingStatus />);
    expect(screen.getByRole("alert")).toHaveTextContent("the control node refused the run record");
    report(3);
    rerender(<RunRecordingStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Live sessions are not recorded here: the gateway runs without a control node");
  });
});
