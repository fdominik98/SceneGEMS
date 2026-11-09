from functional_level.models.object_generator import FIRST_OBSTACLE_ID, FIRST_TS_ID, OS_ID, IdGenerator, obstacle_name, vessel_name
from logical_level.models.actor_variable import OSVariable, StaticObstacleVariable, TSVariable


def test_vessel_names_read_as_in_the_paper_figure():
    assert vessel_name(OS_ID, is_os=True) == "os"
    assert [vessel_name(FIRST_TS_ID + n, is_os=False) for n in range(3)] == ["ts1", "ts2", "ts3"]


def test_obstacles_count_from_one_while_their_ids_stay_in_their_range():
    generator = IdGenerator()
    ids = [generator.next_obstacle() for _ in range(2)]
    assert ids == [FIRST_OBSTACLE_ID, FIRST_OBSTACLE_ID + 1]
    assert [obstacle_name(actor_id) for actor_id in ids] == ["so1", "so2"]


def test_id_ranges_do_not_overlap():
    generator = IdGenerator()
    vessels = {generator.os_id()} | {generator.next_ts() for _ in range(FIRST_OBSTACLE_ID - FIRST_TS_ID)}
    obstacles = {generator.next_obstacle() for _ in range(99)}
    assert vessels.isdisjoint(obstacles)
    assert max(vessels) < FIRST_OBSTACLE_ID <= min(obstacles)


def test_logical_variables_take_the_same_names():
    assert OSVariable(OS_ID, None).name == "os"
    assert TSVariable(2, None).name == "ts2"
    assert StaticObstacleVariable(FIRST_OBSTACLE_ID, None).name == "so1"
