import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { SimulationInitControls } from "./SimulationInitControls";
import type { SimulationStreamControls } from "./types";

const initialPlayback = usePlaybackStore.getState();

/** A scenario of the own ship (id 0) and two targets (ids 1 and 2), as the backend numbers them. */
function threeVessels(): SimulationFrame {
  const base = sampleFrames[0]!;
  const own = base.actors.find((actor) => actor.isOwnShip)!;
  const target = base.actors.find((actor) => !actor.isOwnShip)!;
  const state = Object.values(base.statesByActorId)[0]!;
  return {
    ...base,
    actors: [
      { ...own, id: "0", name: "os" },
      { ...target, id: "1", name: "ts1" },
      { ...target, id: "2", name: "ts2" },
    ],
    statesByActorId: { 0: state, 1: { ...state, x: state.x + 500 }, 2: { ...state, y: state.y + 500 } },
  };
}

const streamControls = { sendMessage: vi.fn() } as unknown as SimulationStreamControls;

beforeEach(() => {
  usePlaybackStore.setState(initialPlayback, true);
  usePlaybackStore.getState().setTrajectoryPreviewFrames([threeVessels()]);
});

describe("SimulationInitControls", () => {
  it("names each vessel as the scenario does, with what it is written out", () => {
    render(<SimulationInitControls streamControls={streamControls} liveSession paceApplies />);
    const table = screen.getByRole("table");
    const names = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.querySelector(".sim-vessel-name")?.textContent);
    expect(names).toEqual(["os own ship", "ts1 target ship", "ts2 target ship"]);
    expect(screen.getByRole("combobox", { name: "Kind of os, own ship" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "ASV software of ts2, target ship" })).toBeInTheDocument();
  });

  it("uses the same names and the default agent names in the agent connections", async () => {
    const user = userEvent.setup();
    render(<SimulationInitControls streamControls={streamControls} liveSession paceApplies />);
    await user.click(screen.getByRole("button", { name: /Agent connections/ }));
    expect(screen.getByRole("textbox", { name: "Agent name of os, own ship" })).toHaveValue("os_sim");
    expect(screen.getByRole("textbox", { name: "Agent name of ts1, target ship" })).toHaveValue("ts1_sim");
    expect(screen.getByRole("textbox", { name: "Topic of ts2, target ship" })).toHaveValue("waraps/unit/surface/simulation/ts2_sim");
  });
});
