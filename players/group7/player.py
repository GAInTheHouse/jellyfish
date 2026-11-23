import struct
from math import hypot

from core.action import Action
from core.depth import Depth
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot

SIZE = 1000.0

# Memory layout (51 bytes):
# magic, birth year, birth day, x, y, 4 current velocities (vx, vy),
# known-currents mask, feed spot (x, y, samples), breed spot (x, y, samples),
# explore node
FMT = struct.Struct("<BHHff8fBffBffBB")


def delta(a, b):
    """Shortest signed distance from a to b on the wrapping ocean."""
    d = (b - a) % SIZE
    return d - SIZE if d > SIZE / 2 else d


class Player7(Player):
    """Track our position from the currents we ride, remember where the
    feeding and breeding zones are, and steer between them by season."""

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        s = snapshot
        if self.memory_size < FMT.size:
            return self.tiny(s)

        m = list(FMT.unpack_from(s.memory))
        if m[0] == 0:  # first founder turn: start with nothing known
            m[0] = 1

        # New life (founder or newborn): we haven't moved yet.
        if (m[1], m[2]) != (s.birth_year, s.birth_day_of_year):
            m[1], m[2] = s.birth_year, s.birth_day_of_year
        else:  # we drifted yesterday with the current we feel now
            m[3] = (m[3] + s.velocity[0]) % SIZE
            m[4] = (m[4] + s.velocity[1]) % SIZE
        x, y = m[3], m[4]

        # Learn this depth's current.
        d = int(s.depth)
        m[5 + 2 * d], m[6 + 2 * d] = s.velocity
        m[13] |= 1 << d

        # Average the spots where we've been in each zone (not with predators).
        if not s.in_predator_zone:
            if s.in_feeding_zone:
                self.remember(m, 14, x, y)
            if s.in_breeding_zone:
                self.remember(m, 17, x, y)

        depth = self.choose(s, m, x, y)
        FMT.pack_into(s.memory, 0, *m)
        return Action(Depth(depth))

    def remember(self, m, i, x, y):
        n = min(m[i + 2] + 1, 50)
        m[i] = (m[i] + delta(m[i], x) / n) % SIZE
        m[i + 1] = (m[i + 1] + delta(m[i + 1], y) / n) % SIZE
        m[i + 2] = n

    def choose(self, s, m, x, y):
        # First few days: try each depth once to learn all currents.
        for d in range(4):
            if not m[13] >> d & 1:
                return d

        # Breed in fall/winter if we can, otherwise go eat.
        breed = s.season in (Season.FALL, Season.WINTER) and s.reproduction_capacity > 0
        i = 17 if breed else 14

        if m[i + 2]:
            tx, ty = m[i], m[i + 1]
        else:
            # Zone unknown: visit a 4x4 grid of points until we find it.
            k = m[20] % 16
            tx, ty = (k % 4 + 0.5) * 250, (k // 4 + 0.5) * 250
            if hypot(delta(x, tx), delta(y, ty)) < 30:
                m[20] = k + 1

        # Pick the current that ends the day closest to the target.
        def dist(d):
            nx, ny = x + m[5 + 2 * d], y + m[6 + 2 * d]
            return hypot(delta(nx, tx), delta(ny, ty))

        # Inside the zone we want: also prefer slow currents, to stay longer.
        here = s.in_breeding_zone if breed else s.in_feeding_zone
        if here and not s.in_predator_zone:
            return min(
                range(4), key=lambda d: dist(d) + 2 * hypot(*m[5 + 2 * d : 7 + 2 * d])
            )

        best = min(range(4), key=dist)
        # No current gets us closer and we're far: go fast, wrap around.
        if dist(best) >= hypot(delta(x, tx), delta(y, ty)) and not s.in_feeding_zone:
            return 0
        return best

    def tiny(self, s):
        """Too little memory: sit deep in a good zone, else go fast."""
        breed = s.season in (Season.FALL, Season.WINTER) and s.reproduction_capacity > 0
        good = s.in_breeding_zone if breed else s.in_feeding_zone
        return Action(Depth.DEEP if good else Depth.SURFACE)