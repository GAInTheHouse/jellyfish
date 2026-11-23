"""Group 2: map the ocean in memory, then commute between known zones.

Every jellyfish keeps its position relative to its founder's birthplace by
adding the sensed current each day. It narrows down each zone's centre on a
25 km candidate grid and offspring inherit that map.

Memory layout (needs MIN_MEMORY bytes):
    0       bit 0 initialised, bits 1-4 current known, bits 5-7 zone seen
    1-5     plan: goal, depth A, days A, depth B, days B
    6       zone readings at the last observation
    8-23    x, y (doubles, founder-relative)
    24-55   heading of each current (doubles)
    56-79   estimated feeding, breeding, predator centres (float pairs)
    100-699 candidate-centre bitmaps, 200 bytes per zone
"""

import struct
from functools import lru_cache
from itertools import pairwise
from math import atan2, cos, hypot, pi, radians, sin

from core.action import Action
from core.depth import Depth
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot

SIZE = 1000.0
RADIUS = 200.0
GRID = 40
CELL = SIZE / GRID
TOLERANCE = 36.0  # two half-cell diagonals: snapped position + snapped centre
GRID_BYTES = GRID * GRID // 8
MIN_MEMORY = 700

FEED, BREED, PRED = 0, 1, 2
GRID_OFFSET = (100, 300, 500)
CENTRE_OFFSET = (56, 64, 72)
RESOLVED_CELLS = 6
OBSERVE_EVERY = 5  # days between routine readings once feeding is located

GOAL_FEED, GOAL_BREED, GOAL_EXPLORE = 1, 2, 3
ARRIVED_KM = 50.0
PREDATOR_DAY_COST = 40.0  # travel days we would spend to avoid one predator day
PREDATOR_MARGIN = 15.0
MAX_DRIFT_OFFSET = 170.0
SUMMER_START, SUMMER_DAYS = 91, 90
EXPLORE_MAX_DAYS = 30
EXPLORE_FALLBACK_DAYS = 10
SURVIVAL = 0.95  # chance of surviving one day in the predator zone

SPEEDS = tuple(d.speed for d in Depth)
ALL_KNOWN = 0b11110
INITIALISED = 1
ROW = (1 << GRID) - 1
COS = [cos(2 * pi * i / GRID) for i in range(GRID)]
SIN = [sin(2 * pi * i / GRID) for i in range(GRID)]


def delta(a: float, b: float) -> float:
    d = (b - a) % SIZE
    return d - SIZE if d > SIZE / 2 else d


def dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return hypot(delta(x1, x2), delta(y1, y2))


def _disc_rows(limit: float, inside: bool) -> tuple[int, ...]:
    """One N-bit row per dy: cells at offset (dx, dy) on the wanted side."""
    rows = []
    for dy in range(GRID):
        row = 0
        for dx in range(GRID):
            d = dist(0, 0, dx * CELL, dy * CELL)
            if (d <= limit) == inside:
                row |= 1 << dx
        rows.append(row)
    return tuple(rows)


MAYBE_IN = _disc_rows(RADIUS + TOLERANCE, True)
MAYBE_OUT = _disc_rows(RADIUS - TOLERANCE, False)


@lru_cache(maxsize=2 * GRID * GRID)
def observation_mask(ox: int, oy: int, inside: bool) -> int:
    """Pure geometry: centres consistent with an in/out reading at a cell."""
    rows = MAYBE_IN if inside else MAYBE_OUT
    mask = 0
    for y in range(GRID):
        row = rows[(y - oy) % GRID]
        rotated = ((row << ox) | (row >> (GRID - ox))) & ROW
        mask |= rotated << (GRID * y)
    return mask


@lru_cache(maxsize=64)
def min_drift(headings: tuple[float, ...]) -> tuple[float, float]:
    """Smallest average velocity any mix of currents can achieve."""
    vs = [velocity(h, s) for h, s in zip(headings, SPEEDS)]
    best = min(vs, key=lambda v: hypot(*v))
    for i, (ax, ay) in enumerate(vs):
        for bx, by in vs[i + 1 :]:
            ex, ey = bx - ax, by - ay
            length = ex * ex + ey * ey
            if length == 0:
                continue
            t = max(0.0, min(1.0, -(ax * ex + ay * ey) / length))
            p = (ax + t * ex, ay + t * ey)
            if hypot(*p) < hypot(*best):
                best = p
    if _origin_in_hull(vs):
        return 0.0, 0.0
    return best


def _origin_in_hull(vs: list[tuple[float, float]]) -> bool:
    angles = sorted(atan2(y, x) for x, y in vs)
    gaps = [b - a for a, b in pairwise(angles)]
    gaps.append(angles[0] + 2 * pi - angles[-1])
    return max(gaps) < pi


def velocity(heading: float, speed: float) -> tuple[float, float]:
    h = radians(heading)
    return speed * sin(h), -speed * cos(h)


class Player2(Player):
    """Learn currents, find the zones, then feed and breed on a yearly cycle."""

    def act(self, s: JellyfishSnapshot) -> Action:
        if self.memory_size < MIN_MEMORY:
            return self._reactive(s)

        m = s.memory
        founder = s.birth_year == 1 and s.birth_day_of_year == 1
        if not m[0] & INITIALISED:
            self._initialise(m)
        x, y = struct.unpack_from("<dd", m, 8)

        if s.age_days == 1 and not founder:
            m[1] = m[3] = m[5] = 0  # newborn: did not drift, parent's plan is void
        elif s.age_days > 0:
            x, y = (x + s.velocity[0]) % SIZE, (y + s.velocity[1]) % SIZE
            struct.pack_into("<dd", m, 8, x, y)

        bit = 1 << (s.depth + 1)
        if not m[0] & bit:
            struct.pack_into("<d", m, 24 + 8 * s.depth, s.heading)
            m[0] |= bit

        self._observe(m, x, y, s)

        if m[0] & ALL_KNOWN != ALL_KNOWN:
            unknown = next(d for d in Depth if not m[0] & (1 << (d + 1)))
            return Action(unknown)

        headings = struct.unpack_from("<dddd", m, 24)
        vs = [velocity(h, v) for h, v in zip(headings, SPEEDS)]
        predator = self._centre(m, PRED)

        wants_breeding = s.reproduction_capacity > 0 and s.day_of_year > 180
        if wants_breeding:
            goal = GOAL_BREED
            tx, ty = self._safe_point(self._centre(m, BREED), predator)
        elif self._centre(m, FEED) is not None:
            goal = GOAL_FEED
            tx, ty = self._feeding_anchor(m, s, headings, predator)
        else:
            return Action(Depth(self._explore(m, x, y, vs, predator)))

        return Action(Depth(self._navigate(m, x, y, tx, ty, goal, vs, predator)))

    # ------------------------------------------------------------- memory
    @staticmethod
    def _initialise(m: bytearray) -> None:
        m[0] = INITIALISED
        full = b"\xff" * GRID_BYTES
        for offset in GRID_OFFSET:
            m[offset : offset + GRID_BYTES] = full

    @staticmethod
    def _centre(m: bytearray, zone: int) -> tuple[float, float] | None:
        if not m[0] & (1 << (5 + zone)):
            return None
        return struct.unpack_from("<ff", m, CENTRE_OFFSET[zone])

    def _observe(self, m: bytearray, x: float, y: float, s: JellyfishSnapshot) -> None:
        readings = (s.in_feeding_zone, s.in_breeding_zone, s.in_predator_zone)
        flags = sum(int(inside) << zone for zone, inside in enumerate(readings))
        feeding_known = m[0] & (1 << (5 + FEED))
        if feeding_known and flags == m[6] and s.day_of_year % OBSERVE_EVERY:
            return  # boundary crossings carry nearly all the information
        m[6] = flags

        ox, oy = round(x / CELL) % GRID, round(y / CELL) % GRID
        for zone, inside in enumerate(readings):
            start = GRID_OFFSET[zone]
            raw = int.from_bytes(m[start : start + GRID_BYTES], "little")
            if raw.bit_count() <= RESOLVED_CELLS:
                continue
            narrowed = raw & observation_mask(ox, oy, inside)
            if narrowed == 0:  # rounding contradiction: keep the older estimate
                continue
            seen_bit = 1 << (5 + zone)
            newly_seen = inside and not m[0] & seen_bit
            if newly_seen:
                m[0] |= seen_bit
            if narrowed != raw or newly_seen:
                m[start : start + GRID_BYTES] = narrowed.to_bytes(GRID_BYTES, "little")
                if m[0] & seen_bit:
                    cx, cy = self._circular_mean(narrowed)
                    struct.pack_into("<ff", m, CENTRE_OFFSET[zone], cx, cy)

    @staticmethod
    def _circular_mean(bits: int) -> tuple[float, float]:
        cx = sx = cy = sy = 0.0
        for iy in range(GRID):
            row = (bits >> (GRID * iy)) & ROW
            count = row.bit_count()
            if not count:
                continue
            cy += COS[iy] * count
            sy += SIN[iy] * count
            while row:
                low = row & -row
                ix = low.bit_length() - 1
                cx += COS[ix]
                sx += SIN[ix]
                row ^= low
        return (
            atan2(sx, cx) / (2 * pi) * SIZE % SIZE,
            atan2(sy, cy) / (2 * pi) * SIZE % SIZE,
        )

    @staticmethod
    def _explore(
        m: bytearray,
        x: float,
        y: float,
        vs: list[tuple[float, float]],
        predator: tuple[float, float] | None,
    ) -> int:
        """Ride the leg that rules out the most feeding candidates per day."""
        if m[1] != GOAL_EXPLORE:
            m[1], m[3], m[5] = GOAL_EXPLORE, 0, 0
        if m[3] > 0:
            m[3] -= 1
            return m[2]

        start = GRID_OFFSET[FEED]
        candidates = int.from_bytes(m[start : start + GRID_BYTES], "little")
        best_depth, best_days, best_score = 0, EXPLORE_FALLBACK_DAYS, 0.0
        for depth, (vx, vy) in enumerate(vs):
            ruled_out = 0
            exposed = 0
            for days in range(1, EXPLORE_MAX_DAYS + 1):
                px, py = (x + vx * days) % SIZE, (y + vy * days) % SIZE
                ox, oy = round(px / CELL) % GRID, round(py / CELL) % GRID
                ruled_out |= candidates & ~observation_mask(ox, oy, False)
                if predator and dist(px, py, *predator) <= RADIUS:
                    exposed += 1
                score = ruled_out.bit_count() / days * SURVIVAL**exposed
                if score > best_score:
                    best_depth, best_days, best_score = depth, days, score
        m[2], m[3] = best_depth, best_days - 1
        return best_depth

    # ------------------------------------------------------------ targets
    @staticmethod
    def _safe_point(
        centre: tuple[float, float] | None, predator: tuple[float, float] | None
    ) -> tuple[float, float]:
        """Shift a zone's centre away from an overlapping predator zone."""
        if centre is None:
            return 0.0, 0.0
        if predator is None:
            return centre
        dx, dy = delta(predator[0], centre[0]), delta(predator[1], centre[1])
        d = hypot(dx, dy)
        needed = RADIUS + PREDATOR_MARGIN - d
        if needed <= 0 or d == 0:
            return centre
        shift = min(needed, MAX_DRIFT_OFFSET)
        return (centre[0] + dx / d * shift) % SIZE, (centre[1] + dy / d * shift) % SIZE

    def _feeding_anchor(
        self,
        m: bytearray,
        s: JellyfishSnapshot,
        headings: tuple[float, ...],
        predator: tuple[float, float] | None,
    ) -> tuple[float, float]:
        """Point to hold; if drift is unavoidable, sweep across the zone in summer."""
        cx, cy = self._safe_point(self._centre(m, FEED), predator)
        dx, dy = min_drift(headings)
        if dx == 0 and dy == 0:
            return cx, cy
        k = s.day_of_year - SUMMER_START if s.season == Season.SUMMER else 0
        ox, oy = dx * (k - SUMMER_DAYS / 2), dy * (k - SUMMER_DAYS / 2)
        length = hypot(ox, oy)
        if length > MAX_DRIFT_OFFSET:
            ox, oy = ox / length * MAX_DRIFT_OFFSET, oy / length * MAX_DRIFT_OFFSET
        return (cx + ox) % SIZE, (cy + oy) % SIZE

    # --------------------------------------------------------- navigation
    def _navigate(
        self,
        m: bytearray,
        x: float,
        y: float,
        tx: float,
        ty: float,
        goal: int,
        vs: list[tuple[float, float]],
        predator: tuple[float, float] | None,
    ) -> int:
        if m[1] != goal:
            m[1], m[3], m[5] = goal, 0, 0
        if m[3] > 0:
            m[3] -= 1
            return m[2]
        if m[5] > 0:
            m[5] -= 1
            return m[4]
        if dist(x, y, tx, ty) <= ARRIVED_KM:
            return self._hold(x, y, tx, ty, vs, predator)

        plan = self._plan(x, y, tx, ty, vs, predator)
        if plan is None:
            return self._hold(x, y, tx, ty, vs, predator)
        a, days_a, b, days_b = plan
        m[2], m[3], m[4], m[5] = a, days_a, b, days_b
        if m[3] > 0:
            m[3] -= 1
            return m[2]
        m[5] -= 1
        return m[4]

    @staticmethod
    def _hold(
        x: float,
        y: float,
        tx: float,
        ty: float,
        vs: list[tuple[float, float]],
        predator: tuple[float, float] | None,
    ) -> int:
        """One-day greedy step toward the target, refusing predator water."""

        def score(i: int) -> float:
            nx, ny = x + vs[i][0], y + vs[i][1]
            cost = dist(nx, ny, tx, ty)
            if predator and dist(nx, ny, *predator) <= RADIUS + PREDATOR_MARGIN:
                cost += 1000.0
            return cost

        return min(range(4), key=score)

    @staticmethod
    def _plan(
        x: float,
        y: float,
        tx: float,
        ty: float,
        vs: list[tuple[float, float]],
        predator: tuple[float, float] | None,
    ) -> tuple[int, int, int, int] | None:
        """Best two-current route, checking every wrap-around image of the target."""
        dx, dy = delta(x, tx), delta(y, ty)
        routes = []
        for wx in range(-2, 3):
            for wy in range(-2, 3):
                gx, gy = dx + wx * SIZE, dy + wy * SIZE
                for i in range(4):
                    for j in range(i + 1, 4):
                        det = vs[i][0] * vs[j][1] - vs[i][1] * vs[j][0]
                        if abs(det) < 1e-6:
                            continue
                        p = (gx * vs[j][1] - gy * vs[j][0]) / det
                        q = (vs[i][0] * gy - vs[i][1] * gx) / det
                        if p < -0.5 or q < -0.5:
                            continue
                        na, nb = max(0, round(p)), max(0, round(q))
                        if 0 < na + nb and na <= 255 and nb <= 255:
                            routes.append((na + nb, i, na, j, nb))
        if not routes:
            return None
        routes.sort()
        if predator is None:
            _, i, na, j, nb = routes[0]
            return i, na, j, nb

        best, best_cost = None, float("inf")
        for total, i, na, j, nb in routes[:12]:
            for a, days_a, b, days_b in ((i, na, j, nb), (j, nb, i, na)):
                exposed = _exposure(x, y, vs[a], days_a, predator)
                mx = x + vs[a][0] * days_a
                my = y + vs[a][1] * days_a
                exposed += _exposure(mx, my, vs[b], days_b, predator)
                cost = total + PREDATOR_DAY_COST * exposed
                if cost < best_cost:
                    best, best_cost = (a, days_a, b, days_b), cost
        return best

    # ----------------------------------------------------- small-memory
    @staticmethod
    def _reactive(s: JellyfishSnapshot) -> Action:
        """Memoryless fallback for runs too small to hold the map."""
        if s.in_predator_zone:
            return Action(Depth.SURFACE)
        if s.in_feeding_zone and s.season == Season.SUMMER:
            return Action(Depth.DEEP)
        if s.in_breeding_zone and s.reproduction_capacity > 0:
            return Action(Depth.DEEP)
        return Action(Depth((s.day_of_year // 30) % 4))


def _exposure(
    x: float,
    y: float,
    v: tuple[float, float],
    days: int,
    predator: tuple[float, float],
) -> int:
    """Approximate days of a straight leg spent in the predator zone."""
    stride = max(1, days // 25)
    hits = 0
    for t in range(0, days, stride):
        if dist(x + v[0] * t, y + v[1] * t, *predator) <= RADIUS:
            hits += stride
    return hits
