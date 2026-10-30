import threading

import pytest

from scenegems_tool.cluster.node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.protocol.jobs import JobType

KINEMATIC, SCENES = JobType.SIMULATION, JobType.SCENE_GENERATION


def test_slots_are_taken_up_to_the_count_and_given_back():
    table = SlotTable({KINEMATIC: 2, SCENES: 1})
    assert table.try_take(KINEMATIC) and table.try_take(KINEMATIC)
    assert not table.try_take(KINEMATIC)
    assert table.try_take(SCENES) and not table.try_take(SCENES)
    assert table.in_use() == {KINEMATIC: 2, SCENES: 1}
    table.give_back(KINEMATIC)
    assert table.free(KINEMATIC) == 1 and table.in_use() == {KINEMATIC: 1, SCENES: 1}
    assert table.try_take(KINEMATIC)


def test_a_type_without_slots_is_never_taken():
    table = SlotTable({KINEMATIC: 1})
    assert not table.offers(SCENES)
    assert not table.try_take(SCENES)
    assert table.free(SCENES) == 0


def test_giving_back_a_free_slot_is_an_error():
    table = SlotTable({KINEMATIC: 1})
    with pytest.raises(ValueError):
        table.give_back(KINEMATIC)
    with pytest.raises(ValueError):
        table.give_back(SCENES)


def test_zero_slots_are_refused():
    with pytest.raises(ValueError):
        SlotTable({KINEMATIC: 0})


def test_concurrent_takers_never_exceed_the_count():
    table = SlotTable({KINEMATIC: 3})
    taken = []
    barrier = threading.Barrier(16)

    def take():
        barrier.wait()
        taken.append(table.try_take(KINEMATIC))

    threads = [threading.Thread(target=take) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert taken.count(True) == 3
    assert table.in_use() == {KINEMATIC: 3}
