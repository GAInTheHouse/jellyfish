from dataclasses import dataclass

from core.depth import Depth


@dataclass(frozen=True)
class Action:
    """What a jellyfish does on one turn (one day).

    depth:     the depth (current) to ride today. The jellyfish then drifts with
               that current's velocity.
    eat:       eat if currently in the feeding zone during summer.
    reproduce: spawn one offspring if currently in the breeding zone during
               winter and reproduction capacity remains.

    Memory changes are made by mutating `snapshot.memory` in place.
    """

    depth: Depth
    eat: bool = True
    reproduce: bool = True
