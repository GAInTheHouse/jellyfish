from core.action import Action
from core.depth import Depth
from core.player import Player
from core.snapshot import JellyfishSnapshot


class RandomPlayer(Player):
    """Baseline: each day, ride a random current. Ignores memory entirely."""

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        return Action(depth=self.rng.choice(list(Depth)))
