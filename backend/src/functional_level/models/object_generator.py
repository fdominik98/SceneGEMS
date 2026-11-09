from functional_level.metamodels.functional_scenario import FuncObject

# The id ranges of a scenario's objects. They never overlap, so an id names one object of one kind.
OS_ID = 0
FIRST_TS_ID = 1
FIRST_OBSTACLE_ID = 100
FIRST_VESSEL_TYPE_ID = 200
FIRST_OBSTACLE_TYPE_ID = 300
OBSTACLE_TYPE_ID_END = 400


def vessel_name(actor_id: int, is_os: bool) -> str:
    """A vessel's name: the own ship is "os", a target "ts<n>" counted from 1 (ts1, ts2)."""
    return "os" if is_os else f"ts{actor_id - FIRST_TS_ID + 1}"


def obstacle_name(actor_id: int) -> str:
    """A static obstacle's name, "so<n>" counted from 1 (so1, so2), while its id stays in the obstacle range."""
    return f"so{actor_id - FIRST_OBSTACLE_ID + 1}" if actor_id >= FIRST_OBSTACLE_ID else f"so{actor_id}"


class IdGenerator:
    def __init__(self) -> None:
        self.__os_id = OS_ID
        self.__ts_ids = list(range(FIRST_TS_ID, FIRST_OBSTACLE_ID))
        self.__obstacle_ids = list(range(FIRST_OBSTACLE_ID, FIRST_VESSEL_TYPE_ID))
        self.__vessel_type_ids = list(range(FIRST_VESSEL_TYPE_ID, FIRST_OBSTACLE_TYPE_ID))
        self.__obstacle_type_ids = list(range(FIRST_OBSTACLE_TYPE_ID, OBSTACLE_TYPE_ID_END))

    def os_id(self, id=None) -> int:
        id = id or self.__os_id
        if id != self.__os_id:
            raise ValueError("OS id is not sufficient.")
        return id

    def next_ts(self, id=None) -> int:
        id = id or self.__ts_ids[0]
        if id not in self.__ts_ids:
            raise ValueError("TS id is not sufficient.")
        self.__ts_ids.remove(id)
        return id

    def next_obstacle(self, id=None) -> int:
        id = id or self.__obstacle_ids[0]
        if id not in self.__obstacle_ids:
            raise ValueError("Obstacle id is not sufficient.")
        self.__obstacle_ids.remove(id)
        return id

    def next_vessel_type(self, id=None) -> int:
        id = id or self.__vessel_type_ids[0]
        if id not in self.__vessel_type_ids:
            raise ValueError("Vessel type id is not sufficient.")
        self.__vessel_type_ids.remove(id)
        return id

    def next_obstacle_type(self, id=None) -> int:
        id = id or self.__obstacle_type_ids[0]
        if id not in self.__obstacle_type_ids:
            raise ValueError("Obstacle type id is not sufficient.")
        self.__obstacle_type_ids.remove(id)
        return id


class ObjectGenerator:
    def __init__(self) -> None:
        self.id_generator = IdGenerator()

    def new_os(self, id=None) -> FuncObject:
        return FuncObject(self.id_generator.os_id(id))

    def new_ts(self, id=None) -> FuncObject:
        return FuncObject(self.id_generator.next_ts(id))

    def new_obstacle(self, id=None) -> FuncObject:
        return FuncObject(self.id_generator.next_obstacle(id))

    def new_vessel_type(self, id=None) -> FuncObject:
        return FuncObject(self.id_generator.next_vessel_type(id))

    def new_obstacle_type(self, id=None) -> FuncObject:
        return FuncObject(self.id_generator.next_obstacle_type(id))
