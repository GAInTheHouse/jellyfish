from __future__ import annotations

import random
from abc import ABC, abstractmethod

from core.action import Action
from core.snapshot import JellyfishSnapshot


class Player(ABC):
    """Base class for every group's jellyfish policy.

    The simulator creates ONE instance of your class per run and calls
    `act` once per living jellyfish per day. Your class must be stateless
    between calls: the jellyfish's memory is `snapshot.memory` and nothing
    else. Do NOT store per-jellyfish information on `self` (you are not told
    which jellyfish is calling, and graders will check).

    Things you MAY use:
      self.memory_size     number of bytes in snapshot.memory
      self.lifetime_days   S * 360, the fixed lifespan of every jellyfish
      self.rng             a seeded random.Random (use it instead of `random`
                           so runs are reproducible)
    """

    def __init__(self, memory_size: int, lifetime_days: int, rng: random.Random):
        self.memory_size = memory_size
        self.lifetime_days = lifetime_days
        self.rng = rng

    def __str__(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def act(self, snapshot: JellyfishSnapshot) -> Action:
        """Decide what one jellyfish does today."""
        raise NotImplementedError
