"""Monitor-guided planner: the seed as the plan, the corridor shapes its search chose, previews while it repairs, and what it says about a plan that still fails."""

import json
import math
import os
import random

import pytest

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation import monitor_guided_planner
from concrete_level.trajectory_generation.maneuvering_domain import CorridorShape
from concrete_level.trajectory_generation.monitor_guided_planner import MonitorGuidedPlanner
from concrete_level.trajectory_generation.seed_trajectory import repair_window
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants, monitored_run
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories
from utils.global_constants import ONE_HOUR_IN_SEC

CROSSING = (3600.0, -3600.0)
RUN_STEPS = 120


class _Previews(list):
    """An observer that keeps the number of scenes and the step count of every preview."""

    def __call__(self, trajectories, monitored, iteration):
        assert len(monitored.monitored_scenes_with_results) == len(trajectories)
        self.append((len(trajectories), iteration))


def _planner(scene, time_step=15, timespan=ONE_HOUR_IN_SEC, **options):
    others = TrajectoryBuilder.default_trajectory_from_scene(scene, time_step, timespan)
    return MonitorGuidedPlanner(scene, others, constants(), verbose=False, **options)


def _run_nodes(steps=RUN_STEPS, **turn):
    return [SceneNode(result) for result in monitored_run(CROSSING, steps, **turn)]


def _data_scene(name):
    with open(os.path.join(os.path.dirname(__file__), "data", name), encoding="utf-8") as file:
        return ConcreteScene.from_dict(json.load(file)["best_scene"])


def _shapes_by_name(planner):
    return {actor.name: (round(math.degrees(shape.outbound_angle)), shape.width_factor) for actor, shape in planner.corridor_shapes.items()}


class TestSeedAsThePlan:
    @pytest.mark.parametrize("encounter", ["crossing_from_starboard", "head_on", "overtaking"])
    def test_a_two_vessel_encounter_needs_no_repair(self, encounter):
        """The corridor's first turn lies inside the early action window, so the seed passes every rule."""
        planner = _planner(encounter_trajectories(encounter, 60).initial_scene)
        assert planner.first_failed_step is None  # nothing planned yet
        trajectories, iterations = planner.plan_trajectory()
        assert planner.first_failed_step is None
        assert planner.corridor_shapes == {}, "the corridors keep the shape their frozen domains give them"
        assert len(trajectories) == iterations + 1 == planner.iteration_count + 1
        assert len(planner.current_best_trajectories()) == len(trajectories)

    def test_the_observer_sees_every_seed_step_and_the_plan(self):
        previews = _Previews()
        trajectories, iterations = _planner(encounter_trajectories("crossing_from_starboard", 60).initial_scene, observer=previews).plan_trajectory()
        assert previews[:3] == [(2, 1), (3, 2), (4, 3)]
        assert previews[-1] == (len(trajectories), iterations)

    def test_the_seed_stops_at_the_iteration_limit(self):
        trajectories, iterations = _planner(encounter_trajectories("crossing_from_starboard", 60).initial_scene, max_iterations=5).plan_trajectory()
        assert (len(trajectories), iterations) == (6, 5)

    def test_a_termination_signal_leaves_the_start_scene_only(self):
        planner = _planner(encounter_trajectories("crossing_from_starboard", 60).initial_scene, termination_signal=lambda: True)
        trajectories, iterations = planner.plan_trajectory()
        assert (len(trajectories), iterations) == (1, 0)


class TestRepair:
    """The seed of these planners is a recorded run in which Rule 17 fails at node 31."""

    @pytest.fixture
    def previews(self):
        return _Previews()

    @pytest.fixture
    def planner(self, previews, monkeypatch):
        failing = _run_nodes(turn_at=30, turn_s=30)
        monkeypatch.setattr(monitor_guided_planner, "search_seed_corridors", lambda *args, **kwargs: (failing, {}))
        return _planner(failing[0].scene, time_step=1, timespan=RUN_STEPS - 1, observer=previews)

    def test_a_failure_the_repair_cannot_replace_is_reported_with_the_path(self, planner, previews):
        planner._repair_one_failure = lambda nodes, *rest: nodes
        trajectories, _ = planner.plan_trajectory()
        assert len(trajectories) == RUN_STEPS
        assert planner.first_failed_step == 31

    def test_a_repaired_path_is_previewed_and_reported_clean(self, planner, previews):
        clean = _run_nodes(60)  # the own ship has to turn by second 60, so a longer straight run is not clean
        planner._repair_one_failure = lambda nodes, *rest: clean
        planner.plan_trajectory()
        assert planner.first_failed_step is None
        assert previews == [(60, 0), (60, 0)]  # after the repair round, then the installed plan

    def test_a_window_search_previews_the_path_it_repairs_once(self, planner, previews):
        """A window search can take a minute; without this the observer was left with the first seed step."""
        failing = _run_nodes(turn_at=30, turn_s=30)
        planner.WINDOW_MAX_ITERATIONS = 3
        planner._search_window(repair_window(failing, 31, False, 1.0))
        assert previews == [(RUN_STEPS, 0)]

    def test_a_preview_the_observer_dropped_is_offered_again(self, planner):
        """The worker drops previews that come within a second of the last one, as the seed's do."""
        offered = []

        def observer(trajectories, monitored, iteration):
            offered.append(len(trajectories))
            return len(offered) > 2  # dropped twice, then taken

        planner._observer = observer
        failing = _run_nodes(turn_at=30, turn_s=30)
        planner.WINDOW_MAX_ITERATIONS = 5
        planner._search_window(repair_window(failing, 31, False, 1.0))
        assert offered == [RUN_STEPS] * 3

    def test_a_stopped_window_search_previews_nothing(self, planner, previews):
        failing = _run_nodes(turn_at=30, turn_s=30)
        planner.stop = True
        assert planner._search_window(repair_window(failing, 31, False, 1.0)) is None
        assert previews == []


class TestSearchedSeed:
    """The seed search of these planners returns a recorded clean run and a reshaped corridor for the own ship."""

    SHAPE = CorridorShape(math.radians(60.0), 2.0)

    @pytest.fixture
    def previews(self):
        return _Previews()

    @pytest.fixture
    def planner(self, previews, monkeypatch):
        clean = _run_nodes(60)
        monkeypatch.setattr(monitor_guided_planner, "search_seed_corridors", lambda *args, **kwargs: (clean, {OWN_SHIP: self.SHAPE}))
        return _planner(clean[0].scene, time_step=1, timespan=RUN_STEPS - 1, observer=previews)

    def test_the_step_count_and_the_preview_follow_the_searched_seed(self, planner, previews):
        trajectories, iterations = planner.plan_trajectory()
        assert (len(trajectories), iterations) == (60, 59)
        assert previews == [(60, 59), (60, 59)]  # the searched seed, then the installed plan

    def test_the_planner_keeps_the_shapes_and_costs_the_plan_on_them(self, planner):
        planner.plan_trajectory()
        assert planner.corridor_shapes == {OWN_SHIP: self.SHAPE}
        assert planner.trajectory_objective_set[OWN_SHIP].corridor_shape == self.SHAPE
        assert planner.trajectory_objective_set[TARGET].corridor_shape is None

    def test_a_repair_works_on_the_shaped_corridors(self, planner, monkeypatch):
        failing = _run_nodes(turn_at=30, turn_s=30)
        monkeypatch.setattr(monitor_guided_planner, "search_seed_corridors", lambda *args, **kwargs: (failing, {OWN_SHIP: self.SHAPE}))
        asked = []
        monkeypatch.setattr(monitor_guided_planner, "repair_window", lambda nodes, failure, extra_phase, tolerance, shapes=None: asked.append((failure, shapes)))
        planner.plan_trajectory()
        assert asked == [(31, {OWN_SHIP: self.SHAPE})]
        assert planner.first_failed_step == 31


@pytest.mark.slow
def test_a_scene_with_a_far_second_encounter_gets_a_clean_seed():
    """Own ship head-on with TS3 while TS1 overtakes it, and overtaking TS2 itself, 5566 s on.

    The far overtaking has a domain 126 km ahead, so the corridor of the own ship does not return
    inside the hour. At its default width the own ship is back on its heading at 180 s and on
    collision course with TS2 again, while the head-on with TS3 is still running (Rule 8(c)).
    The seed search widens the corridor until the pair stays apart, and steepens the corridor
    of TS2 for the crossing with TS1 that starts at 765 s. The window repair is not needed.
    """
    scene = _data_scene("four_vessel_head_on_overtaken.json")
    random.seed(0)  # the window search samples heading changes; it does not run here
    previews = _Previews()
    planner = _planner(scene, observer=previews)
    trajectories, iterations = planner.plan_trajectory()
    assert planner.first_failed_step is None
    assert _shapes_by_name(planner) == {"os": (0, 3.0), "ts2": (60, 1.0)}
    assert len(trajectories) == iterations + 1 == 241, "the own ship holds its corridor for the whole hour"
    assert previews[-2:] == [(241, 240), (241, 240)]  # the searched seed, then the installed plan


@pytest.mark.slow
def test_a_crossing_from_abaft_the_beam_while_overtaken_gets_a_clean_seed():
    """Own ship gives way to TS2, crossing from 16 degrees abaft its starboard beam 1800 s on, while TS1 overtakes it.

    The default corridors fail twice: the own ship moves to starboard into the corridor TS1 overtakes it in
    (94 m apart at 660 s), and its sideways shift does not open the crossing with TS2 (517 m against 723 m).
    The seed search gives the own ship an 80 degree leg three times as wide, on which it passes astern of TS2
    and well clear of TS1, whose corridor keeps its shape.
    """
    scene = _data_scene("three_vessel_crossing_while_overtaken.json")
    random.seed(0)
    planner = _planner(scene)
    trajectories, iterations = planner.plan_trajectory()
    assert planner.first_failed_step is None
    assert _shapes_by_name(planner) == {"os": (80, 3.0)}
    assert len(trajectories) == iterations + 1 == 198
    vessels = {vessel.name: vessel for vessel in scene.vessels}

    def closest(first, second):
        return min(float(scene_at.get_geo_props(vessels[first], vessels[second]).o_distance) for scene_at in trajectories)

    assert closest("os", "ts2") > vessels["ts2"].safety_radius
    assert closest("os", "ts1") > 2 * vessels["ts1"].safety_radius
