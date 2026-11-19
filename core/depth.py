from enum import IntEnum

import core.constants as c


class Depth(IntEnum):
    """The four current layers. Lower value = closer to the surface = faster."""

    SURFACE = 0
    SHALLOW = 1
    MEDIUM = 2
    DEEP = 3

    @property
    def speed(self) -> float:
        """Current speed at this depth, in km/day."""
        return c.CURRENT_SPEEDS[self.value]

    @property
    def label(self) -> str:
        return self.name.capitalize()
