"""Seed trajectory helpers: phases of a give-way manoeuvre, latched domains and the repair window around a failure."""

import json
import math
import os
from types import SimpleNamespace

import pytest

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.trajectory_generation import seed_trajectory
from concrete_level.trajectory_generation.seed_trajectory import (
    MAX_WINDOW_STEPS,
    PHASE_AFTER,
    PHASE_BEFORE,
    PHASE_INBOUND,
    PHASE_OUTBOUND,
    PHASE_PARALLEL,
    LatchedGiveWayStore,
    build_seed_nodes,
    clone_as_root,
    detach_node,
    failure_give_way_actors,
    first_failure_index,
    follow_step,
    latched_domains_from_nodes,
    next_phase,
    original_headings_from_root,
    phase_of_actor,
    phase_of_pose,
    repair_window,
    seed_desired_heading,
    seed_maneuver_finished,
    stand_on_bound_actors,
    window_rejoins,
)
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, WindowRepairSpec
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants, monitored_run

CROSSING = (3600.0, -3600.0)


def _nodes(steps=120, **turn):
    return [SceneNode(result) for result in monitored_run(CROSSING, steps, **turn)]


@pytest.fixture
def failing_nodes():
    """The target, standing on, turns at second 30: Rule 17 fails at node 31 and the own ship gives way."""
    return _nodes(turn_at=30, turn_s=30)


@pytest.fixture
def clean_nodes():
    return _nodes(60)


def _domain():
    return SimpleNamespace(t0=10.0, along_c=50.0, near_outer=lambda across: abs(across) > 20.0, near_track=lambda across: abs(across) < 5.0)


class TestPhases:
    @pytest.mark.parametrize(
        "along, across, phase",
        [(0.0, 0.0, PHASE_BEFORE), (20.0, 0.0, PHASE_OUTBOUND), (20.0, 30.0, PHASE_PARALLEL), (60.0, 30.0, PHASE_INBOUND), (60.0, 0.0, PHASE_AFTER)],
    )
    def test_the_phase_follows_the_position_in_the_domain(self, along, across, phase):
        assert phase_of_pose(_domain(), along, across) == phase

    def test_without_a_domain_everything_is_before(self):
        assert phase_of_pose(None, 100.0, 0.0) == PHASE_BEFORE

    def test_next_phase_walks_the_order_and_stops_at_after(self):
        phases = (PHASE_BEFORE, PHASE_OUTBOUND, PHASE_PARALLEL, PHASE_INBOUND, PHASE_AFTER)
        assert [next_phase(phase) for phase in phases] == [PHASE_OUTBOUND, PHASE_PARALLEL, PHASE_INBOUND, PHASE_AFTER, PHASE_AFTER]
        assert next_phase("unknown") == PHASE_AFTER

    # The corridor's first leg is speed times half of IMMEDIATE_HEADING_CHANGE_TIME: 240 m at 8 m/s and the shipped
    # 60 s, so the give-way ship is outbound from node 30.
    def test_a_run_goes_from_before_to_outbound_for_the_give_way_ship(self, failing_nodes):
        domain = latched_domains_from_nodes(failing_nodes)[OWN_SHIP]
        assert phase_of_actor(OWN_SHIP, failing_nodes[20], domain) == PHASE_BEFORE
        assert phase_of_actor(OWN_SHIP, failing_nodes[29], domain) == PHASE_BEFORE
        assert phase_of_actor(OWN_SHIP, failing_nodes[31], domain) == PHASE_OUTBOUND
        assert phase_of_actor(OWN_SHIP, failing_nodes[80], domain) == PHASE_OUTBOUND
        assert phase_of_actor(OWN_SHIP, failing_nodes[80], None) == PHASE_BEFORE

    def test_the_desired_heading_is_the_original_one_without_a_domain_or_before_it(self, failing_nodes):
        domain = latched_domains_from_nodes(failing_nodes)[OWN_SHIP]
        assert seed_desired_heading(failing_nodes[0].scene[OWN_SHIP], None, 1.25) == 1.25
        assert seed_desired_heading(failing_nodes[0].scene[OWN_SHIP], domain, 1.25) == 1.25  # still before the manoeuvre
        assert seed_desired_heading(failing_nodes[80].scene[OWN_SHIP], domain, 1.25) != 1.25


class TestLatchedDomains:
    def test_the_give_way_ship_gets_a_domain_and_the_stand_on_ship_does_not(self, failing_nodes):
        assert set(latched_domains_from_nodes(failing_nodes)) == {OWN_SHIP}

    def test_a_domain_is_cached_and_stays_after_the_encounter_ends(self, failing_nodes):
        store = LatchedGiveWayStore()
        for node in failing_nodes[:20]:
            store.update(node.monitored_scene_with_results)
        latched = store.domains()
        assert store.domains() is latched
        store.update(failing_nodes[119].monitored_scene_with_results)
        assert set(store.domains()) == {OWN_SHIP}

    def test_the_manoeuvre_is_not_finished_without_domains_or_enough_nodes(self, failing_nodes):
        assert not seed_maneuver_finished(failing_nodes, LatchedGiveWayStore())
        store = LatchedGiveWayStore()
        for node in failing_nodes:
            store.update(node.monitored_scene_with_results)
        assert not seed_maneuver_finished(failing_nodes[:3], store)
        assert not seed_maneuver_finished(failing_nodes[:40], store)  # still outbound


class TestFailures:
    def test_the_first_failure_is_the_step_where_a_rule_fails_and_never_the_root(self, failing_nodes, clean_nodes):
        assert first_failure_index(failing_nodes) == 31
        assert first_failure_index(clean_nodes) is None

    def test_a_rule_kept_per_vessel_frees_the_vessel_that_broke_it(self, failing_nodes):
        """Rule 17 is keyed by the target with itself: the repair has to steer the target, not the own ship."""
        failed = [relation for relation, rules in failing_nodes[31].monitor_result_map_set.get_failed_rules().items() if rules]
        assert failed == [Relation(TARGET, TARGET)]
        assert failure_give_way_actors(failing_nodes[31]) == {TARGET}

    def test_a_rule_of_an_encounter_frees_its_give_way_actors(self, clean_nodes):
        results = SimpleNamespace(get_failed_rules=lambda: {Relation(OWN_SHIP, TARGET): ["a failed rule"]})
        node = SimpleNamespace(monitor_result_map_set=results, monitored_scene_with_results=clean_nodes[10].monitored_scene_with_results)
        assert failure_give_way_actors(node) == {OWN_SHIP}

    def test_a_vessel_rule_can_be_repaired_after_every_encounter_is_over(self, failing_nodes):
        """With every context OTHER nobody gives way; the fallback freed no one and the repair gave up."""
        results = SimpleNamespace(get_failed_rules=lambda: {Relation(TARGET, TARGET): ["a failed rule"]})
        over = SimpleNamespace(situation_context_set={})
        node = SimpleNamespace(monitor_result_map_set=results, monitored_scene_with_results=over)
        assert failure_give_way_actors(node) == {TARGET}

    def test_without_a_failed_rule_every_live_give_way_actor_is_named(self, clean_nodes):
        assert failure_give_way_actors(clean_nodes[10]) == {OWN_SHIP}

    @pytest.mark.parametrize("extra_phase", [False, True])
    def test_the_repair_window_surrounds_the_failure(self, failing_nodes, extra_phase):
        spec = repair_window(failing_nodes, 31, extra_phase, 5.0)
        assert (spec.start, spec.end, spec.length, spec.free_actors, spec.rejoin_tolerance) == (29, 37, 8, {TARGET}, 5.0)
        assert spec.rejoin_scene is failing_nodes[37].scene

    @pytest.mark.parametrize("index", [0, -1, 500])
    def test_no_window_for_the_root_or_an_index_outside_the_nodes(self, failing_nodes, index):
        assert repair_window(failing_nodes, index, False, 5.0) is None

    def test_no_window_when_nobody_gives_way(self):
        nodes = _nodes(5)
        for node in nodes:
            node.monitored_scene_with_results.situation_context_set.clear()
        assert repair_window(nodes, 2, False, 5.0) is None

    @pytest.mark.parametrize("start, end, expected", [(5, 10, (5, 10)), (0, 8, (0, 8)), (0, 30, (18, 26))])
    def test_a_window_is_never_longer_than_the_limit(self, start, end, expected):
        assert MAX_WINDOW_STEPS == 8
        assert seed_trajectory._clamp_window(start, end, 20, 100) == expected

    def test_a_clamped_window_ends_at_the_last_node_at_most(self):
        assert seed_trajectory._clamp_window(0, 30, 99, 100) == (97, 99)
        assert seed_trajectory._clamp_window(0, 30, 99, 98) == (97, 97)


class TestStandOn:
    """A vessel Rule 17 binds keeps its heading in the seed, whatever its corridor asks for."""

    def test_the_stand_on_vessel_is_bound_and_the_give_way_vessel_is_not(self, clean_nodes):
        assert stand_on_bound_actors(clean_nodes[10].monitored_scene_with_results, constants()) == {TARGET}

    def test_it_is_released_once_the_give_way_vessel_has_let_its_window_pass(self):
        """Rule 17(a)(ii): the own ship never turns in this run, so after IMMEDIATE_HEADING_CHANGE_TIME the target may act."""
        late = _nodes(120)[constants().IMMEDIATE_HEADING_CHANGE_TIME + 5]
        assert stand_on_bound_actors(late.monitored_scene_with_results, constants()) == set()

    def test_a_held_vessel_keeps_its_heading_and_the_others_steer(self, clean_nodes):
        scene = clean_nodes[0].scene
        wanted = {OWN_SHIP: scene[OWN_SHIP].heading - 0.5, TARGET: scene[TARGET].heading - 0.5}
        next_scene, changes = follow_step(scene, {}, wanted, 15, constants(), {TARGET})
        assert changes[TARGET] == 0.0 and next_scene[TARGET].heading == scene[TARGET].heading
        assert changes[OWN_SHIP] < 0.0

    def test_without_held_vessels_every_vessel_steers(self, clean_nodes):
        scene = clean_nodes[0].scene
        wanted = {OWN_SHIP: scene[OWN_SHIP].heading - 0.5, TARGET: scene[TARGET].heading - 0.5}
        _, changes = follow_step(scene, {}, wanted, 15, constants())
        assert changes[OWN_SHIP] < 0.0 and changes[TARGET] < 0.0


class TestHeadOnWhileOvertaken:
    """A generated scene the seed failed on: the own ship meets TS3 head-on and is overtaken by TS1.

    The seed used to fail Rule 16 at 75 s (first turn after the window), then Rule 17 at 375 s (the
    own ship turned back to its track while TS1 was still overtaking it), and TS1 never settled on
    its course again. The encounter with TS2 that starts once the own ship is back on its track
    (after 720 s) is left to the window repair and not part of this seed.
    """

    TIME_STEP = 15

    @pytest.fixture(scope="class")
    def seed(self):
        with open(os.path.join(os.path.dirname(__file__), "data", "four_vessel_head_on_overtaken.json"), encoding="utf-8") as file:
            scene = ConcreteScene.from_dict(json.load(file)["best_scene"])
        monitor = COLREGSMonitor(scene, constants(), judge_initial_scene=False)
        nodes = build_seed_nodes(monitor, self.TIME_STEP, 720.0)
        return nodes, {vessel.name: vessel for vessel in scene.vessels}

    def _headings(self, seed, name):
        nodes, vessels = seed
        return [math.degrees(node.scene[vessels[name]].heading) for node in nodes]

    def test_the_seed_fails_no_rule(self, seed):
        nodes, _ = seed
        assert len(nodes) == 49
        assert first_failure_index(nodes) is None

    def test_every_give_way_ship_turns_inside_the_early_action_window(self, seed):
        window = constants().IMMEDIATE_HEADING_CHANGE_TIME // self.TIME_STEP
        for name in ("os", "ts1", "ts3"):
            headings = self._headings(seed, name)
            assert headings[window] != pytest.approx(headings[0]), name

    def test_the_own_ship_holds_its_course_until_the_overtaking_ship_is_clear(self, seed):
        """It is past C at node 24 (360 s) and would turn back there; TS1 is clear at node 39 (585 s)."""
        headings = self._headings(seed, "os")
        assert headings[24:40] == pytest.approx([90.0] * 16)
        assert headings[40] == pytest.approx(120.0)

    def test_a_slow_turning_ship_settles_on_its_course_on_the_parallel_leg(self, seed):
        """TS1 turns 25.8 degrees a step at most; the rest of the way back used to alternate around the course."""
        headings = self._headings(seed, "ts1")
        assert headings[20:40] == pytest.approx([headings[0]] * 20)


class TestNodes:
    def test_the_original_headings_are_those_of_the_root_vessels(self, failing_nodes):
        assert original_headings_from_root(failing_nodes[0]) == {OWN_SHIP: 0.0, TARGET: failing_nodes[0].scene[TARGET].heading}

    def test_a_clone_is_a_fresh_root_with_the_same_bookkeeping(self, failing_nodes):
        source = failing_nodes[5]
        source.path_cost, source.window_depth, source.goal_distances = 9.0, 3, {OWN_SHIP: 1.0}
        clone = clone_as_root(source)
        assert (clone.path_cost, clone.window_depth, clone.goal_distances, clone.encountered) == (0.0, 0, {OWN_SHIP: 1.0}, source.encountered)
        assert clone.monitored_scene_with_results is source.monitored_scene_with_results
        assert clone.goal_distances is not source.goal_distances

    def test_detaching_resets_the_tree_links(self, failing_nodes):
        node = failing_nodes[6]
        node.id, node.parent, node.children, node.is_dead_end = 4, 3, {5}, True
        assert detach_node(node) is node
        assert (node.id, node.parent, node.children, node.is_dead_end) == (-1, None, set(), False)


class TestWindowRejoin:
    @staticmethod
    def _spec(nodes, tolerance=5.0):
        return WindowRepairSpec(seed_nodes=nodes, start=0, end=2, free_actors={OWN_SHIP}, rejoin_scene=nodes[2].scene, rejoin_tolerance=tolerance)

    def test_a_node_too_early_in_the_window_does_not_rejoin(self, failing_nodes):
        failing_nodes[2].window_depth = 1
        assert not window_rejoins(failing_nodes[2], self._spec(failing_nodes), 1)

    def test_a_node_on_the_target_pose_rejoins(self, failing_nodes):
        failing_nodes[2].window_depth = 2
        assert window_rejoins(failing_nodes[2], self._spec(failing_nodes), 1)

    def test_a_node_too_far_away_does_not_rejoin(self, failing_nodes):
        far = SimpleNamespace(window_depth=2, scene={OWN_SHIP: ActorState(500.0, 0.0, 8.0, 0.0)})
        assert not window_rejoins(far, self._spec(failing_nodes), 1)

    def test_a_node_on_the_spot_but_turned_too_far_does_not_rejoin(self, failing_nodes):
        target = failing_nodes[2].scene[OWN_SHIP]
        turned = SimpleNamespace(window_depth=2, scene={OWN_SHIP: ActorState(target.x, target.y, 8.0, 1.5)})
        assert not window_rejoins(turned, self._spec(failing_nodes), 1)
