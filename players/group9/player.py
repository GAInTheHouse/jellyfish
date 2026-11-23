from ctypes import LittleEndianStructure, c_bool, c_double, c_uint32, sizeof

from core.action import Action
from core.depth import Depth
from core.geometry import torus_distance, wrap
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot

Point = c_double * 2
TRAVEL_DEPTHS = (Depth.SURFACE, Depth.SHALLOW, Depth.MEDIUM)


class Memory(LittleEndianStructure):
    """Named fields backed directly by the jellyfish's byte array."""

    _pack_ = 1
    _fields_ = [
        ("last_age", c_uint32),
        ("knows_food", c_bool),
        ("position", Point),
        ("food", Point),
        ("currents", Point * len(Depth)),
    ]

    def observe(self, s: JellyfishSnapshot) -> None:
        # A newborn's first turn starts at the position copied from its parent.
        if s.age_days > self.last_age:
            x, y = self.position
            dx, dy = s.velocity
            self.position[:] = wrap(x + dx), wrap(y + dy)
        self.last_age = s.age_days
        self.currents[s.depth][:] = s.velocity
        if s.in_feeding_zone and not s.in_predator_zone and not self.knows_food:
            self.food[:] = self.position
            self.knows_food = True

    def choose_depth(self, seek_home: bool, in_target: bool) -> Depth | None:
        for depth in Depth:
            if not any(self.currents[depth]):
                return depth  # Try each current once to learn its direction.

        if not seek_home and not self.knows_food:
            return None
        target = (0, 0) if seek_home else self.food  # The founder was born at (0, 0).
        x, y = self.position

        def distance_after_drift(depth: Depth) -> float:
            dx, dy = self.currents[depth]
            return torus_distance(x + dx, y + dy, *target)

        best = min(Depth, key=distance_after_drift)
        if in_target or distance_after_drift(best) < torus_distance(x, y, *target):
            return best
        return None


class Player9(Player):
    def act(self, s: JellyfishSnapshot) -> Action:
        seek_home = (
            s.season in (Season.FALL, Season.WINTER) and s.reproduction_capacity > 0
        )
        in_target = s.in_breeding_zone if seek_home else s.in_feeding_zone
        depth = Depth.DEEP if in_target else None
        if len(s.memory) >= sizeof(Memory):
            memory = Memory.from_buffer(s.memory)
            memory.observe(s)
            depth = memory.choose_depth(seek_home, in_target)

        if s.in_predator_zone:
            return Action(Depth.SURFACE)
        if depth is None:
            depth = self.rng.choice(TRAVEL_DEPTHS)
        return Action(depth)
