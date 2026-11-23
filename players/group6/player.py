from core.action import Action
from core.constants import DAYS_PER_YEAR
from core.depth import Depth
from core.player import Player
from core.snapshot import JellyfishSnapshot

FAST_CURRENTS = (Depth.SURFACE, Depth.SHALLOW)
# Each day gets one byte: 0 for no success, or a code for (zone, fast current).
FOOD_CODES = (1, 2)
BREEDING_CODES = (3, 4)


class Player6(Player):
    def act(self, s: JellyfishSnapshot) -> Action:
        wants_to_breed = s.reproduction_capacity > 0
        in_target = s.in_breeding_zone if wants_to_breed else s.in_feeding_zone
        codes = BREEDING_CODES if wants_to_breed else FOOD_CODES

        day = (s.year - 1) * DAYS_PER_YEAR + s.day_of_year - 1
        slot = day % len(s.memory)
        s.memory[slot] = 0
        if in_target and not s.in_predator_zone:
            if s.depth in FAST_CURRENTS:
                s.memory[slot] = codes[s.depth]
            return Action(Depth.DEEP)

        # Give each fast current one vote to start, then one per remembered success.
        votes = [1 + s.memory.count(code) for code in codes]
        return Action(self.rng.choices(FAST_CURRENTS, weights=votes)[0])
