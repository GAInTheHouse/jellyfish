from dataclasses import dataclass
from math import cos, radians, sin

from core.depth import Depth


@dataclass(frozen=True)
class Current:
    """A band of water at one depth moving at a fixed velocity.

    Coordinate convention (same as the GUI): x grows to the EAST, y grows to
    the SOUTH. `heading` is a compass bearing in degrees: 0 = north,
    90 = east, 180 = south, 270 = west.
    """

    depth: Depth
    heading: float

    @property
    def speed(self) -> float:
        return self.depth.speed

    @property
    def velocity(self) -> tuple[float, float]:
        """(dx, dy) in km/day."""
        h = radians(self.heading)
        return self.speed * sin(h), -self.speed * cos(h)
