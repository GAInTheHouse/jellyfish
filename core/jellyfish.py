"""Simulator-side state of one jellyfish. Players never see this object."""

from __future__ import annotations

from dataclasses import dataclass, field

import core.constants as c
from core.depth import Depth


@dataclass(eq=False)
class Jellyfish:
    id: int
    group: int
    x: float
    y: float
    depth: Depth
    memory: bytearray
    birth_t: int
    generation: int = 0
    parent_id: int | None = None

    # life cycle bookkeeping
    eat_days_total: int = 0  # every day eaten, ever (first 30 = growing)
    summer_feed_days: int = 0  # eating days after maturity in the current summer
    capacity: int = 0  # offspring still allowed this winter
    offspring: int = 0

    alive: bool = True
    death_t: int | None = None
    death_cause: str | None = None  # "predator" | "age" | "error"

    # previous position, used by the GUI to animate smoothly between days
    prev_x: float = field(default=0.0)
    prev_y: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.prev_x, self.prev_y = self.x, self.y

    @property
    def is_mature(self) -> bool:
        return self.eat_days_total >= c.EAT_DAYS_TO_MATURE
