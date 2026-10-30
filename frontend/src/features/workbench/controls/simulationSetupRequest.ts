import { create } from "zustand";
import type { GlobalSimulatorType } from "./simulationInitConfig";

/**
 * A setup the simulation page takes from outside its controls: the stack and environment of a
 * loaded run (design doc 6.6), so the run can run again. `SimulationInitControls` applies it once
 * its vessel table has the run's vessels.
 */

export interface SimulationSetupRequest {
  /** Bumped for every request, so the same setup asked twice applies twice. */
  token: number;
  simulatorType: GlobalSimulatorType;
  /** replay: every vessel replays; usv_navigation: USV Navigation steers the own ship, the others replay. */
  mode: "replay" | "usv_navigation";
  /** The control layer every vessel runs on: none on the kinematic layer, ardupilot on ArduPilot SITL and Gazebo, or custom on Gazebo. */
  controlLayer: "none" | "ardupilot" | "custom";
  /** SITL's pace of an ArduPilot run, the setup's real-time factor; null keeps the current one. */
  speedup: number | null;
  windVector: [number, number, number];
  wave: { amplitude: number; period: number; steepness: number; east: number; north: number } | null;
}

interface SimulationSetupRequestState {
  request: SimulationSetupRequest | null;
  requestSetup: (setup: Omit<SimulationSetupRequest, "token">) => void;
}

export const useSimulationSetupRequestStore = create<SimulationSetupRequestState>()((set) => ({
  request: null,
  requestSetup: (setup) => set((state) => ({ request: { ...setup, token: (state.request?.token ?? 0) + 1 } })),
}));
