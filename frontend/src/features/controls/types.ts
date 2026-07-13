export interface SimulationStreamControls {
  loadScenarioFromFile: (file: File | null) => Promise<void>;
  /** @deprecated Use loadScenarioFromFile */
  initializeSimulation: (file: File | null) => Promise<void>;
  startSimulation: () => void;
  resetSimulation: () => void;
  setSpeed: (value: number) => void;
  seek: (value: number) => void;
  sendMessage: (message: import("../../domain/simulation/wireTypes").ClientToServerMessage) => void;
}
