from functional_level.metamodels.functional_scenario import FuncObject


class IdGenerator:
    def __init__(self) -> None:
        self.__os_id = 0
        self.__ts_ids = list(range(1, 100))
        self.__obstacle_ids = list(range(100, 200))
        self.__vessel_type_ids = list(range(200, 300))
        self.__obstacle_type_ids = list(range(300, 400))

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
