from dataclasses import dataclass
from enum import Enum

import core.constants as c
from core.geometry import torus_distance


class ZoneKind(Enum):
    FEEDING = "feeding"
    BREEDING = "breeding"
    PREDATOR = "predator"


@dataclass(frozen=True)
class Zone:
    kind: ZoneKind
    x: float
    y: float
    radius: float = c.ZONE_RADIUS

    def contains(self, x: float, y: float) -> bool:
        return torus_distance(self.x, self.y, x, y) <= self.radius
