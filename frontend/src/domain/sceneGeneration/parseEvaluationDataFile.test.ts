import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { parseFrame } from "../simulation/protocol";
import {
  buildFramesFromTrajectoryData,
  buildScenarioJsonForServer,
  formatScenarioJsonForExport,
  parseScenarioFile,
} from "./parseEvaluationDataFile";

describe("parseScenarioFile", () => {
  it("parses wrapped scene and metadata", () => {
    const parsed = parseScenarioFile(
      JSON.stringify({
        scene: sampleFrames[0],
        scenario_name: "test",
        random_seed: 1,
      })
    );
    expect(parsed.scene.timestamp).toBe(0);
    expect(parsed.evaluationData).toEqual({ scenario_name: "test", random_seed: 1 });
  });

  it("parses best_scene._data tuples from backend export", () => {
    const parsed = parseScenarioFile(
      JSON.stringify({
        algorithm_desc: "Two_Step_CD_Rejection_Sampling",
        scenario_name: "3vessel_0obstacle",
        best_scene: {
          _data: [
            [
              {
                id: 0,
                type: "OSPassengerShip",
                length: 30,
                breadth: 10.5,
                height: 4.5,
                draft: 1.8,
                mass: 346612,
                safety_radius: 120,
                _is_os: true,
                is_vessel: true,
              },
              { x: 0, y: 0, speed: 14.6, heading: 1.57 },
            ],
            [
              {
                id: 1,
                type: "UnspecifiedVesselType",
                length: 158,
                breadth: 55,
                height: 24,
                draft: 9.5,
                mass: 51301592,
                safety_radius: 634,
                _is_os: false,
                is_vessel: true,
              },
              { x: 84.5, y: 9298, speed: 10.5, heading: -1.63 },
            ],
          ],
        },
      })
    );
    expect(parsed.scene.actors).toHaveLength(2);
    expect(parsed.scene.actors[0]?.name).toBe("os");
    expect(parsed.scene.actors[1]?.name).toBe("ts1");
    expect(parsed.scene.actors[0]?.isOwnShip).toBe(true);
    expect(parsed.scene.statesByActorId["0"]?.x).toBe(0);
    expect(parsed.evaluationData).toMatchObject({
      scenario_name: "3vessel_0obstacle",
      algorithm_desc: "Two_Step_CD_Rejection_Sampling",
    });
    expect(parsed.evaluationData).not.toHaveProperty("best_scene");
  });

  it("parses top-level frame shape", () => {
    const parsed = parseScenarioFile(JSON.stringify(sampleFrames[0]));
    expect(parsed.scene.actors.length).toBeGreaterThan(0);
    expect(parsed.evaluationData).toEqual({});
  });

  it("rejects metadata-only JSON", () => {
    expect(() => parseScenarioFile(JSON.stringify({ scenario_name: "no-scene" }))).toThrow(
      /scenario/i
    );
  });

  it("parses full trajectory export using first scene from trajectories.scene_list", () => {
    const parsed = parseScenarioFile(
      JSON.stringify({
        algorithm_desc: "RRTStar_algo",
        config_name: "3vessel_0obstacle",
        measurement_name: "test",
        trajectories: {
          time_step: 15,
          scene_list: [
            {
              _data: [
                [
                  {
                    id: 0,
                    type: "OSPassengerShip",
                    length: 30,
                    breadth: 12,
                    height: 4.5,
                    draft: 1.8,
                    mass: 397722,
                    safety_radius: 120,
                    _is_os: true,
                    is_vessel: true,
                  },
                  { x: 0, y: 0, speed: 4.9, heading: 1.57 },
                ],
                [
                  {
                    id: 1,
                    type: "UnspecifiedVesselType",
                    length: 169,
                    breadth: 67,
                    height: 25,
                    draft: 10,
                    mass: 71524167,
                    safety_radius: 677,
                    _is_os: false,
                    is_vessel: true,
                  },
                  { x: 5429, y: 7442, speed: 11.2, heading: -2.46 },
                ],
              ],
            },
          ],
        },
      })
    );
    expect(parsed.hasFullTrajectories).toBe(true);
    expect(parsed.scene.actors).toHaveLength(2);
    expect(parsed.scene.actors[0]?.name).toBe("os");
    expect(parsed.evaluationData).toMatchObject({
      algorithm_desc: "RRTStar_algo",
      config_name: "3vessel_0obstacle",
    });
    expect(parsed.evaluationData).not.toHaveProperty("trajectories");
  });

  it("exports server-compatible best_scene without a top-level scene field", () => {
    const parsed = parseScenarioFile(
      JSON.stringify({
        scene: sampleFrames[0],
        scenario_name: "round_trip",
      })
    );
    const exported = JSON.parse(
      formatScenarioJsonForExport(parsed.evaluationData, parsed.scene)
    ) as Record<string, unknown>;
    expect(exported).not.toHaveProperty("scene");
    expect(exported.scenario_name).toBe("round_trip");
    expect(exported.best_scene).toBeDefined();
    const roundTrip = parseScenarioFile(JSON.stringify(exported));
    expect(roundTrip.scene.actors.length).toBe(parsed.scene.actors.length);
  });
});

describe("the steering type and the block coefficient of a vessel", () => {
  function backendVessel(id: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      id,
      type: "CargoShip",
      length: 120,
      breadth: 18,
      height: 17,
      draft: 7,
      mass: 11000000,
      safety_radius: 480,
      _is_os: id === 0,
      is_vessel: true,
      _max_speed: 12.8,
      _propeller_diameter: 4.2,
      _motor_length: 6,
      ...extra,
    };
  }

  function backendObstacle(id: number): Record<string, unknown> {
    return { id, type: "SmallObstacle", length: 10, breadth: 10, height: 2, draft: 1, mass: 100, safety_radius: 20, is_vessel: false };
  }

  function sceneFile(actors: Record<string, unknown>[]): string {
    return JSON.stringify({
      scenario_name: "steering",
      best_scene: { _data: actors.map((actor, index) => [actor, { x: index * 500, y: 0, speed: 5, heading: 0 }]) },
    });
  }

  /** The actor dictionaries of `best_scene._data`, as the backend scenario loader gets them. */
  function wireActors(scenario: Record<string, unknown>): Record<string, unknown>[] {
    const bestScene = scenario.best_scene as { _data: [Record<string, unknown>, unknown][] };
    return bestScene._data.map(([actor]) => actor);
  }

  const withFields = sceneFile([
    backendVessel(0, { _steering_type: "rudder", _block_coefficient: 0.72 }),
    backendVessel(1, { _steering_type: "vectored_thrust", _block_coefficient: 0.45 }),
  ]);

  it("reads them from a backend scene file", () => {
    const { scene } = parseScenarioFile(withFields);
    expect(scene.actors[0]).toMatchObject({ steeringType: "rudder", blockCoefficient: 0.72 });
    expect(scene.actors[1]).toMatchObject({ steeringType: "vectored_thrust", blockCoefficient: 0.45 });
  });

  it("writes them back for a trajectory generation job and for an export", () => {
    const parsed = parseScenarioFile(withFields);
    const forServer = wireActors(buildScenarioJsonForServer(parsed.evaluationData, parsed.scene));
    expect(forServer[0]).toMatchObject({ _steering_type: "rudder", _block_coefficient: 0.72 });
    expect(forServer[1]).toMatchObject({ _steering_type: "vectored_thrust", _block_coefficient: 0.45 });
    expect(forServer[0]).not.toHaveProperty("steeringType");
    expect(forServer[0]).not.toHaveProperty("blockCoefficient");

    const exported = formatScenarioJsonForExport(parsed.evaluationData, parsed.scene);
    expect(wireActors(JSON.parse(exported) as Record<string, unknown>)).toEqual(forServer);

    const again = parseScenarioFile(exported);
    expect(again.scene.actors.map((actor) => [actor.steeringType, actor.blockCoefficient])).toEqual([
      ["rudder", 0.72],
      ["vectored_thrust", 0.45],
    ]);
  });

  it("leaves them absent for a scene file from before these fields, so the backend defaults them", () => {
    const parsed = parseScenarioFile(sceneFile([backendVessel(0), backendVessel(1)]));
    for (const actor of parsed.scene.actors) {
      expect(actor).not.toHaveProperty("steeringType");
      expect(actor).not.toHaveProperty("blockCoefficient");
    }
    const exported = JSON.parse(formatScenarioJsonForExport(parsed.evaluationData, parsed.scene)) as Record<string, unknown>;
    for (const actor of wireActors(exported)) {
      expect(actor).not.toHaveProperty("_steering_type");
      expect(actor).not.toHaveProperty("_block_coefficient");
      expect(actor).toMatchObject({ _max_speed: 12.8, _propeller_diameter: 4.2 });
    }
  });

  it("carries them per actor: a vessel with them, a vessel without and a static obstacle", () => {
    const parsed = parseScenarioFile(
      sceneFile([backendVessel(0, { _steering_type: "skid", _block_coefficient: 0.6 }), backendVessel(1), backendObstacle(2)])
    );
    const actors = wireActors(buildScenarioJsonForServer(parsed.evaluationData, parsed.scene));
    expect(actors[0]).toMatchObject({ _steering_type: "skid", _block_coefficient: 0.6 });
    for (const actor of actors.slice(1)) {
      expect(actor).not.toHaveProperty("_steering_type");
      expect(actor).not.toHaveProperty("_block_coefficient");
    }
    expect(actors[2]).toMatchObject({ is_vessel: false });
  });

  it("keeps them from a frame of the gateway, which names them in camel case", () => {
    const scene = parseFrame({
      ...sampleFrames[0],
      actors: sampleFrames[0].actors.map((actor, index) => (index === 0 ? { ...actor, steeringType: "rudder", blockCoefficient: 0.65 } : actor)),
    });
    const actors = wireActors(buildScenarioJsonForServer({}, scene));
    expect(actors[0]).toMatchObject({ _steering_type: "rudder", _block_coefficient: 0.65 });
    expect(actors[1]).not.toHaveProperty("_steering_type");
    expect(actors[1]).not.toHaveProperty("_block_coefficient");
  });

  it("reads them from every scene of a trajectory", () => {
    const frames = buildFramesFromTrajectoryData({
      trajectories: {
        time_step: 10,
        scene_list: [0, 1].map((step) => ({
          _data: [[backendVessel(0, { _steering_type: "rudder", _block_coefficient: 0.72 }), { x: step * 50, y: 0, speed: 5, heading: 0 }]],
        })),
      },
    });
    expect(frames.map((frame) => [frame.actors[0].steeringType, frame.actors[0].blockCoefficient])).toEqual([
      ["rudder", 0.72],
      ["rudder", 0.72],
    ]);
  });
});
