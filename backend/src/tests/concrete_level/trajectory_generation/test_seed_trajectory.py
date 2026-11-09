"""Seed trajectory helpers: phases of a give-way manoeuvre, latched domains and the repair window around a failure."""

from types import SimpleNamespace

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.trajectory_generation import seed_trajectory
from concrete_level.trajectory_generation.seed_trajectory import (
    MAX_WINDOW_STEPS,
    PHASE_AFTER,
    PHASE_BEFORE,
    PHASE_INBOUND,
    PHASE_OUTBOUND,
    PHASE_PARALLEL,
    LatchedGiveWayStore,
    clone_as_root,
    detach_node,
    failure_give_way_actors,
    first_failure_index,
    latched_domains_from_nodes,
    next_phase,
    original_headings_from_root,
    phase_of_actor,
    phase_of_pose,
    repair_window,
    seed_desired_heading,
    seed_maneuver_finished,
    window_rejoins,
)
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, WindowRepairSpec
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, monitored_run

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

    # The corridor's first leg is speed times READILY_APPARENT_COURSE_CHANGE_TIME: 560 m at 8 m/s and the shipped
    # 70 s, so the give-way ship is outbound from node 70.
    def test_a_run_goes_from_before_to_outbound_for_the_give_way_ship(self, failing_nodes):
        domain = latched_domains_from_nodes(failing_nodes)[OWN_SHIP]
        assert phase_of_actor(OWN_SHIP, failing_nodes[20], domain) == PHASE_BEFORE
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

    def test_the_give_way_actors_at_a_failure_are_those_of_the_failed_encounter(self, failing_nodes):
        assert failure_give_way_actors(failing_nodes[31]) == {OWN_SHIP}

    def test_without_a_failed_rule_every_live_give_way_actor_is_named(self, clean_nodes):
        assert failure_give_way_actors(clean_nodes[10]) == {OWN_SHIP}

    @pytest.mark.parametrize("extra_phase", [False, True])
    def test_the_repair_window_surrounds_the_failure(self, failing_nodes, extra_phase):
        spec = repair_window(failing_nodes, 31, extra_phase, 5.0)
        assert (spec.start, spec.end, spec.length, spec.free_actors, spec.rejoin_tolerance) == (29, 37, 8, {OWN_SHIP}, 5.0)
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
