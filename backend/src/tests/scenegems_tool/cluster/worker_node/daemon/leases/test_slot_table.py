import threading

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.daemon.leases.slot_table import SlotTable

KINEMATIC, SCENES = JobType.SIMULATION, JobType.SCENE_GENERATION


def test_slots_are_taken_up_to_the_count_and_given_back():
    table = SlotTable({KINEMATIC: 2, SCENES: 1})
    assert table.take_all([KINEMATIC]) is None and table.take_all([KINEMATIC]) is None
    assert table.take_all([KINEMATIC]) == KINEMATIC
    assert table.take_all([SCENES]) is None and table.take_all([SCENES]) == SCENES
    assert table.in_use() == {KINEMATIC: 2, SCENES: 1}
    table.give_back(KINEMATIC)
    assert table.free(KINEMATIC) == 1 and table.in_use() == {KINEMATIC: 1, SCENES: 1}
    assert table.take_all([KINEMATIC]) is None


def test_a_type_without_slots_is_never_taken():
    table = SlotTable({KINEMATIC: 1})
    assert not table.offers(SCENES)
    assert table.take_all([SCENES]) == SCENES
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
        taken.append(table.take_all([KINEMATIC]) is None)

    threads = [threading.Thread(target=take) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert taken.count(True) == 3
    assert table.in_use() == {KINEMATIC: 3}


# A job that takes slots of two types: a simulation judged while it runs

MONITORING = JobType.MONITORING_POST_HOC


def test_the_slots_of_a_job_are_taken_together_or_not_at_all():
    table = SlotTable({KINEMATIC: 2, MONITORING: 1})
    assert table.take_all([KINEMATIC, MONITORING]) is None
    assert table.in_use() == {KINEMATIC: 1, MONITORING: 1}
    assert table.take_all([KINEMATIC, MONITORING]) == MONITORING, "the monitoring slot is in use"
    assert table.in_use() == {KINEMATIC: 1, MONITORING: 1}, "no simulation slot was taken for the job that cannot start"
    assert table.take_all([KINEMATIC]) is None and table.take_all([KINEMATIC]) == KINEMATIC
    table.give_back_all([KINEMATIC, MONITORING])
    assert table.in_use() == {KINEMATIC: 1} and table.take_all([KINEMATIC, MONITORING]) is None


def test_a_job_that_needs_a_type_the_worker_node_does_not_offer_takes_nothing():
    table = SlotTable({KINEMATIC: 2})
    assert table.take_all([KINEMATIC, MONITORING]) == MONITORING and table.in_use() == {}
