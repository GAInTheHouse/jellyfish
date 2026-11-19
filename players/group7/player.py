from core.action import Action
from core.player import Player
from core.snapshot import JellyfishSnapshot


class Player7(Player):
    """Group 7's jellyfish.

    Called once per living jellyfish per day. Read what the jellyfish senses
    from `snapshot`, update `snapshot.memory` in place if you want to
    remember something, and return an Action choosing today's depth.

    Do not keep per-jellyfish state on `self`: memory is the only memory.
    """

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        # TODO(group 7): replace this. For now: stay at the current depth.
        return Action(depth=snapshot.depth)
