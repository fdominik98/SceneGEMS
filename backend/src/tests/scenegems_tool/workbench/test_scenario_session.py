"""ScenarioSession: a bare scene is a scenario of its initial scene only, a trajectory file loads as planned, and the preview is plain frames."""

import json

import pytest

from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.subsystems.trajectory_generation.straight_trajectory_generator import straight_trajectory_data
from scenegems_tool.workbench.scenario_session import SCENARIO_CHUNK_BATCH_SIZE, ScenarioSession, iter_scene_batches, scenario_trajectories
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene, encounter_trajectories


@pytest.fixture
def sent():
    return []


def bare_scene_file() -> str:
    return json.dumps(EvaluationData(best_scene=encounter_scene("head_on"), timeout=1, random_seed=3).to_dict())


def trajectory_file(timespan: int = 60, time_step: int = 15) -> str:
    return json.dumps(straight_trajectory_data(encounter_scene("head_on"), time_step, timespan, "head_on", 7).to_dict())


def load(content: str, sent) -> ScenarioSession:
    return ScenarioSession("s1", "scene.json", "dir/scene.json", content, sent.append)


def chunks(sent):
    return [message for message in sent if message["type"] == "preview_trajectory_chunk"]


class TestBareScene:
    def test_it_holds_the_initial_scene_and_nothing_else(self, sent):
        session = load(bare_scene_file(), sent)
        assert len(session.trajectories) == 1
        assert session.trajectory_length == 0
        assert session.is_initialized

    def test_no_trajectory_is_invented(self, sent, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("a bare scene must not get default trajectories")

        monkeypatch.setattr(TrajectoryBuilder, "default_builder_from_scene", staticmethod(refuse))
        monkeypatch.setattr(TrajectoryBuilder, "default_trajectory_from_scene", staticmethod(refuse))
        monkeypatch.setattr(TrajectoryBuilder, "simulate_to_timespan", refuse)
        assert len(load(bare_scene_file(), sent).trajectories) == 1

    def test_the_initial_state_message_comes_first_and_reports_no_trajectory_length(self, sent):
        load(bare_scene_file(), sent)
        assert sent[0] == {"type": "initial_state", "scenarioId": "s1", "timeStep": 1, "trajectoryLength": 0}

    def test_the_scene_view_gets_the_initial_scene_as_one_frame(self, sent):
        load(bare_scene_file(), sent)
        (chunk,) = chunks(sent)
        assert (chunk["scenarioId"], chunk["fromTimestamp"], chunk["toTimestamp"]) == ("s1", 0, 0)
        assert len(chunk["frames"]) == 1

    def test_the_initial_scene_sits_at_the_own_ship(self, sent):
        own_ship_state = load(bare_scene_file(), sent).trajectories.initial_scene.os_state
        assert (own_ship_state.x, own_ship_state.y) == (0.0, 0.0)

    def test_the_preview_is_plain_the_cluster_judges_it(self, sent):
        """The gateway runs no monitor: the frames carry the states only, and a monitoring job on a worker node adds the rule results."""
        load(bare_scene_file(), sent)
        (frame,) = chunks(sent)[0]["frames"]
        assert frame["statesByActorId"]
        assert frame["ruleResults"] == frame["colregsStates"] == frame["situationContexts"] == frame["maneuverStates"] == []


class TestTrajectoryFile:
    def test_the_whole_trajectory_is_loaded(self, sent):
        session = load(trajectory_file(timespan=60), sent)
        assert session.is_initialized and len(session.trajectories) > 1
        assert session.time_step == 1
        assert session.trajectory_length >= 60
        assert sent[0]["trajectoryLength"] == session.trajectory_length

    def test_every_scene_reaches_the_preview_in_order(self, sent):
        session = load(trajectory_file(timespan=60), sent)
        frames = [frame for chunk in chunks(sent) for frame in chunk["frames"]]
        assert len(frames) == len(session.trajectories)
        assert [frame["timestamp"] for frame in frames] == sorted(frame["timestamp"] for frame in frames)
        assert [message["type"] for message in sent] == ["initial_state"] + ["preview_trajectory_chunk"] * len(chunks(sent)), "nothing else is sent"

    def test_the_session_remembers_where_the_scenario_came_from(self, sent):
        session = load(trajectory_file(), sent)
        assert (session.scenario_id, session.file_name, session.file_path) == ("s1", "scene.json", "dir/scene.json")
        assert session.loaded_at_utc.endswith("+00:00")


class TestFilesThatAreNoScenario:
    def test_text_that_is_no_json_is_a_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            scenario_trajectories("{")

    def test_json_that_is_neither_a_scene_nor_trajectories_is_refused(self, sent):
        with pytest.raises((TypeError, ValueError, KeyError)):
            load(json.dumps({"something": "else"}), sent)
        assert sent == [], "nothing was sent for a file that did not load"


class TestSceneBatches:
    def test_the_first_scene_goes_alone_and_the_rest_in_batches(self):
        trajectories = encounter_trajectories("head_on", 2 * SCENARIO_CHUNK_BATCH_SIZE + 5)
        batches = list(iter_scene_batches(trajectories, 1))
        assert [len(scenes) for scenes, _ in batches][:2] == [1, SCENARIO_CHUNK_BATCH_SIZE]
        assert batches[0][1] == [0] and batches[1][1][0] == 1
        timestamps = [timestamp for _, stamps in batches for timestamp in stamps]
        assert timestamps == list(range(len(trajectories)))

    def test_the_timestamps_follow_the_time_step(self):
        (_, first), (_, rest) = list(iter_scene_batches(encounter_trajectories("head_on", 3), 5))[:2]
        assert first == [0] and rest[:2] == [5, 10]

    def test_no_scenes_no_batches(self):
        assert list(iter_scene_batches([], 1)) == []
