from core.action import Action
from core.depth import Depth
from core.player import Player
from core.snapshot import JellyfishSnapshot


class ExamplePlayer(Player):
    """A minimal example: ride one random depth for 30 days, then pick another.

    It ignores the zones entirely; it exists to show how to read and write
    memory, using ONE byte:

        memory[0] bits 7-6 = current depth (0..3)
        memory[0] bits 5-0 = days left before switching (0..63)
    """

    LEG_DAYS = 30

    def act(self, s: JellyfishSnapshot) -> Action:
        packed = s.memory[0]
        depth, days_left = packed >> 6, packed & 0x3F  # unpack

        if days_left == 0:  # time to switch (also true on the very first day)
            depth = self.rng.randrange(4)
            days_left = self.LEG_DAYS

        s.memory[0] = (depth << 6) | (days_left - 1)  # pack and store
        return Action(Depth(depth))
