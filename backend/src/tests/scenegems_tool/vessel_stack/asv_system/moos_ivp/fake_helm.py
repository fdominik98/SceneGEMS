"""A helm for the tests: MOOS-IvP exists only in its image, so the navigator and the runners are tested against this one.

FakeHelm stands where HelmProcesses stands (moos_ivp_server.Helm). It reads its goal, speed and distances from the
behaviour file it is started with and decides as crudely as a test needs: straight at the goal, 30 degrees to starboard
of that while a contact it was alerted to is within the outer distance, and it has arrived within the capture radius.
Its decisions are on the helm's grid of whole degrees, so a run with it repeats bit for bit.
"""

import math
import re
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server import ARRIVED_VARIABLE, HelmPass, MoosIvpSession, Post

STARBOARD_TURN_DEGREES = 30.0


def behaviour_value(behaviours: str, name: str) -> str:
    found = re.search(rf"^\s*{name} = (.+)$", behaviours, re.MULTILINE)
    assert found is not None, f"the behaviour file has no {name}"
    return found.group(1).strip()


class FakeHelm:
    started: List["FakeHelm"] = []  # every helm a test started, oldest first

    def __init__(self) -> None:
        self.mission: Optional[str] = None
        self.behaviours: Optional[str] = None
        self.passes: List[Tuple[float, List[Post]]] = []  # (MOOS time, posts) of every pass
        self.closed = False
        self._alerted: Set[str] = set()
        self._arrived = False

    def start(self, mission: Callable[[int], str], behaviours: str) -> None:
        self.mission = mission(9000)
        self.behaviours = behaviours
        goal_x, goal_y = behaviour_value(behaviours, "point").split(",")
        self.goal = (float(goal_x), float(goal_y))
        self.speed = float(behaviour_value(behaviours, "speed"))
        self.capture_radius = float(behaviour_value(behaviours, "capture_radius"))
        self.outer = float(behaviour_value(behaviours, "pwt_outer_dist"))
        FakeHelm.started.append(self)

    def run_pass(self, moos_time: float, posts: Sequence[Post]) -> HelmPass:
        assert not self.closed
        self.passes.append((moos_time, list(posts)))
        values: Dict[str, float] = {name: value for name, value in posts if isinstance(value, float)}
        own_x, own_y = values["NAV_X"], values["NAV_Y"]
        result = HelmPass()
        contacts = {}
        for name, value in posts:
            if name == "NODE_REPORT":
                fields = dict(part.split("=", 1) for part in str(value).split(","))
                contacts[fields["NAME"]] = (float(fields["X"]), float(fields["Y"]))
            elif name == "CONTACT_INFO":
                contact = str(value).split("contact=")[1]
                self._alerted.add(contact)
                result.life_events.append(f"iter=0,time={moos_time:.2f}, bname=avd_{contact}, btype=BHV_AvdColregsV22, event=spawn, seed={value},iter={len(self.passes)}")
        if self._arrived or math.hypot(self.goal[0] - own_x, self.goal[1] - own_y) <= self.capture_radius:
            self._arrived = True
            result.arrived = True
            result.allstop = "NothingToDo"
            return result
        compass = (90.0 - math.degrees(math.atan2(self.goal[1] - own_y, self.goal[0] - own_x))) % 360.0
        if any(name in self._alerted and math.hypot(x - own_x, y - own_y) <= self.outer for name, (x, y) in contacts.items()):
            compass = (compass + STARBOARD_TURN_DEGREES) % 360.0
        result.heading, result.speed = float(round(compass) % 360), self.speed
        return result

    def close(self) -> None:
        self.closed = True


class FakeHelmSession(MoosIvpSession):
    """The MOOS-IvP container's session with the fake helm in the place of MOOS-IvP's processes."""

    helm_factory = FakeHelm


__all__ = ["ARRIVED_VARIABLE", "FakeHelm", "FakeHelmSession", "behaviour_value"]
