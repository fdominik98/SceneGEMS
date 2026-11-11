"""Trajectory tree builder: the per-vessel cache of the give-way domain."""

from concrete_level.trajectory_generation import trajectory_tree_builder
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, TrajectoryObjective
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, monitored_run

CROSSING = (3600.0, -3600.0)  # the target crosses from the own ship's starboard side: the own ship gives way
OUT_OF_SIGHT = (60000.0, 60000.0)  # no situation with the target


def _node(target_start) -> SceneNode:
    return SceneNode(monitored_run(target_start, 2)[1])


class TestDomainCache:
    def test_the_domain_of_a_context_set_is_computed_once(self):
        node = _node(CROSSING)
        objective = TrajectoryObjective(OWN_SHIP, node, 1)
        domain = objective._union_domain(node)
        assert domain is not None
        assert objective._union_domain(node) is domain

    def test_a_context_set_at_the_address_of_another_gets_its_own_domain(self, monkeypatch):
        """The cache is keyed by id(), which a new context set can share with one that was freed.

        Both sets get the same key here, as after such a reuse: each must still get the
        domain of its own contexts, not the one cached under the key.
        """
        encounter, clear = _node(CROSSING), _node(OUT_OF_SIGHT)
        objective = TrajectoryObjective(OWN_SHIP, encounter, 1)
        objective._domain_cache.clear()
        monkeypatch.setattr(trajectory_tree_builder, "id", lambda _: 1, raising=False)
        assert objective._union_domain(encounter) is not None
        assert objective._union_domain(clear) is None
        assert objective._union_domain(encounter) is not None
