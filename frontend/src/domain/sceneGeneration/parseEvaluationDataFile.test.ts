import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import {
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
    expect(parsed.scene.actors[0]?.name).toBe("OS");
    expect(parsed.scene.actors[1]?.name).toBe("TS1");
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
    expect(parsed.scene.actors[0]?.name).toBe("OS");
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
