from dataclasses import dataclass

from core.depth import Depth
from core.seasons import Season


@dataclass(frozen=True)
class JellyfishSnapshot:
    """Everything a single jellyfish can sense at the start of a day.

    This is the ONLY information your player gets. Notably, jellyfish do NOT
    know their (x, y) position or where the zones are.
    """

    # calendar
    day_of_year: int  # 1..360
    year: int  # 1-based
    season: Season
    birth_day_of_year: int
    birth_year: int

    # body
    depth: Depth
    heading: float  # compass bearing of the current at this depth (0=N, 90=E)
    speed: float  # km/day of the current at this depth
    velocity: tuple[float, float]  # (dx, dy) km/day, x east / y south

    # zones
    in_feeding_zone: bool
    in_breeding_zone: bool
    in_predator_zone: bool

    reproduction_capacity: int  # offspring still allowed this winter

    # The jellyfish's entire memory. Mutate it in place, e.g.
    #   snapshot.memory[0] = 7
    # Its length is fixed; every value must stay in 0..255.
    memory: bytearray

    @property
    def age_days(self) -> int:
        """Convenience: days since birth (derivable from the fields above)."""
        return (self.year - self.birth_year) * 360 + (
            self.day_of_year - self.birth_day_of_year
        )
