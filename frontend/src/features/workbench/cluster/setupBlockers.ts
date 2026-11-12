import { vesselNameOf } from "../../../domain/simulation/actorNaming";
import type { StackOptionsPayload, StackOptionWire } from "../../../domain/simulation/wireTypes";
import { ASV_SYSTEM_LABELS, CONTROL_LAYER_LABELS, findStackOption } from "../controls/simulationInitConfig";
import type { ClusterRunPlan, SimulationSetup, SimulationVesselSetup } from "./simulationJobs";

/**
 * Why no job runs a setup as it is. The stack options say what one vessel's stack can do; these are the rules of a
 * whole setup, which a worker node checks only when it builds the job's stack (the resolver's resolve_instance, the
 * Gazebo layer's externally_stepped, the ArduAgent driver). A setup that breaks one fails as a job every time, so the
 * run panel names the rule and does not submit it:
 *
 * - every simulated vessel's stack runs on the simulator;
 * - the simulated vessels of a Gazebo world are all on the custom controller, or none of them is;
 * - beside a real vessel every simulated vessel runs through an ArduAgent (replay or Mission Planner on ArduPilot),
 *   and the run keeps real time;
 * - an attended job applies the setup's wind and waves, so the simulator has to have them;
 * - the pace of an attended or an ArduPilot job stays within what the vessels' stacks were measured to keep up with.
 */
export function setupBlockers(setup: SimulationSetup, plan: ClusterRunPlan, options: StackOptionsPayload | null): string[] {
  const simulated = setup.vessels.filter((vessel) => vessel.context === "simulation");
  const hasRealVessel = setup.vessels.some((vessel) => vessel.context === "real");
  const optionOf = (vessel: SimulationVesselSetup) => findStackOption(options, setup.simulatorType, vessel.asvSystem, vessel.controlLayer);
  const blockers: string[] = [];

  if (options !== null) {
    for (const vessel of simulated) {
      if (optionOf(vessel)?.available !== true) {
        blockers.push(
          `${nameOf(vessel)} cannot run ${ASV_SYSTEM_LABELS[vessel.asvSystem]} with the control layer ${CONTROL_LAYER_LABELS[vessel.controlLayer]} on ${setup.simulatorType}: pick another ASV system, control layer or simulator.`
        );
      }
    }
  }

  if (setup.simulatorType === "Gazebo") {
    const onCustom = simulated.filter((vessel) => vessel.controlLayer === "custom");
    const others = simulated.filter((vessel) => vessel.controlLayer !== "custom");
    if (onCustom.length > 0 && others.length > 0) {
      const otherLayers = [...new Set(others.map((vessel) => CONTROL_LAYER_LABELS[vessel.controlLayer]))].join(" or ");
      blockers.push(
        `A Gazebo world steps either with ArduPilot or with the custom controller, not with both: put every simulated vessel on the same control layer (now ${namesOf(others)} on ${otherLayers}, ${namesOf(onCustom)} on ${CONTROL_LAYER_LABELS.custom}).`
      );
    }
  }

  if (hasRealVessel) {
    const notThroughAnAgent = simulated.filter((vessel) => vessel.controlLayer !== "ardupilot" || (vessel.asvSystem !== "replay" && vessel.asvSystem !== "mission_planner"));
    if (notThroughAnAgent.length > 0) {
      blockers.push(
        `Beside a real vessel every simulated vessel runs through an ArduAgent, which takes replay or Mission Planner on ArduPilot (on Gazebo or ArduPilot Sim): change ${namesOf(notThroughAnAgent)}.`
      );
    }
    if (setup.speedup > 1) {
      blockers.push("A real vessel runs in real time: set the pace to 1.");
    }
  }

  if (plan.runner === "attended") {
    const lacks = (capability: "wind" | "waves") => simulated.some((vessel) => optionOf(vessel)?.[capability] === "unsupported");
    if (setup.windVector.some((component) => component !== 0) && lacks("wind")) {
      blockers.push(`${setup.simulatorType} has no wind: set the wind to zero, or pick a simulator that has it.`);
    }
    if (setup.waveSpeed > 0 && lacks("waves")) {
      blockers.push(`${setup.simulatorType} has no waves: set where the waves are going to zero, or pick a simulator that has them.`);
    }
  }

  const paced = plan.runner === "attended" || plan.runner === "ardupilot";
  if (paced && !hasRealVessel && setup.speedup > 1) {
    const slowest = slowestOf(simulated.map((vessel) => ({ vessel, option: optionOf(vessel) })));
    if (slowest !== null && setup.speedup > slowest.limit) {
      blockers.push(
        `${ASV_SYSTEM_LABELS[slowest.vessel.asvSystem]} on ${setup.simulatorType} is measured to keep up to ${slowest.limit}x real time (${nameOf(slowest.vessel)}): set the pace to ${slowest.limit} or less.`
      );
    }
  }
  return blockers;
}

/** The vessel whose stack has the lowest measured speedup, and that speedup; null when no stack of the setup has a measured one. */
function slowestOf(stacks: { vessel: SimulationVesselSetup; option: StackOptionWire | undefined }[]): { vessel: SimulationVesselSetup; limit: number } | null {
  let slowest: { vessel: SimulationVesselSetup; limit: number } | null = null;
  for (const { vessel, option } of stacks) {
    const limit = option !== undefined && !option.speedupUnlimited ? option.maxSpeedup : null;
    if (limit !== null && (slowest === null || limit < slowest.limit)) {
      slowest = { vessel, limit };
    }
  }
  return slowest;
}

function nameOf(vessel: SimulationVesselSetup): string {
  return vesselNameOf(vessel.vesselId, vessel.isOwnShip);
}

/** "os", "os and ts1", "os, ts1 and ts2". */
function namesOf(vessels: readonly SimulationVesselSetup[]): string {
  const names = vessels.map(nameOf);
  return names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
