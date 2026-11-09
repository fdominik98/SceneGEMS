import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { useHistoryStore } from "../../history/historyStore";
import { PageEntryStatus } from "./PageEntryStatus";
import { useTrajectoryPageStore } from "./pageStore";

const ENTRY = "9fef90f7-2e6d-4f2b-af34-7fa03012f128";
const initialPage = useTrajectoryPageStore.getState();
const initialUi = useUiStore.getState();

describe("PageEntryStatus", () => {
  beforeEach(() => {
    useTrajectoryPageStore.setState(initialPage, true);
    useUiStore.setState(initialUi, true);
  });

  it("names the loaded case and links its entry, shortened, to Campaign History", async () => {
    const user = userEvent.setup();
    // The master's case id is 7; the case is the first of its class.
    useTrajectoryPageStore.setState({ loaded: { page: "trajectoryGeneration", campaignId: ENTRY, caseId: 7, caseIndex: 0, step: "trajectory_generation" } });
    render(<PageEntryStatus store={useTrajectoryPageStore} />);
    expect(screen.getByText(/Case 1 of/)).toBeInTheDocument();
    const link = screen.getByRole("button", { name: "entry 9fef90f7" });
    expect(link).toHaveAttribute("title", `Open entry ${ENTRY} in Campaign History`);
    await user.click(link);
    expect(useUiStore.getState().section).toBe("history");
    expect(useHistoryStore.getState().entryId).toBe(ENTRY);
  });

  it("reports a failed load as an alert", () => {
    useTrajectoryPageStore.setState({ status: "failed", message: "The entry is gone." });
    render(<PageEntryStatus store={useTrajectoryPageStore} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The entry is gone.");
  });
});

describe("PageEntryStatus of a target stored before case indexes", () => {
  it("does not show the master's case id as a case number", () => {
    useTrajectoryPageStore.setState({ status: "shown", message: null, loaded: { page: "trajectoryGeneration", campaignId: ENTRY, caseId: 7, step: "trajectory_generation" } });
    render(<PageEntryStatus store={useTrajectoryPageStore} />);
    expect(screen.getByText(/A case of/)).toBeInTheDocument();
    expect(screen.queryByText(/Case 7/)).not.toBeInTheDocument();
  });
});
