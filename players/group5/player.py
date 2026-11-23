"""Group 5 uses a compass, three remembered places, and short rides on currents.

Spring and summer are for finding and holding food. In fall, jellyfish with
offspring capacity head for a nursery. A sighting corrects the estimated map;
if danger overlaps the destination, the jellyfish aims for the safer side.
"""

from math import cos, floor, hypot, sin, tau

from core.action import Action
from core.constants import OCEAN_SIZE, ZONE_RADIUS
from core.depth import Depth
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot

# All distances below are in map cells. One complete trip around the ocean is 256.
_CELL = OCEAN_SIZE / 256
_RADIUS = ZONE_RADIUS / _CELL
_FOOD, _NURSERY, _DANGER = 2, 4, 6
_DEPTHS = tuple(Depth)
_SEARCH_DEPTHS = (Depth.SURFACE, Depth.SHALLOW, Depth.MEDIUM)

# Two compass readings per byte. Zero means unseen; 1..15 name compass sectors.
# This lookup contains only geometry and the four speeds given by the game.
_SECTORS = 15
_DRIFT = tuple(
    ((0.0, 0.0),)
    + tuple(
        (
            depth.speed / _CELL * sin(tau * i / _SECTORS),
            -depth.speed / _CELL * cos(tau * i / _SECTORS),
        )
        for i in range(_SECTORS)
    )
    for depth in _DEPTHS
)

Point = tuple[float, float]


def _wrap(offset: float) -> float:
    """Shortest signed displacement along one axis of the ocean."""
    return (offset + 128) % 256 - 128


def _distance_sq(point: Point, x: float, y: float) -> float:
    dx = _wrap(point[0] - x)
    dy = _wrap(point[1] - y)
    return dx * dx + dy * dy


def _read_site(memory: bytearray, site: int) -> Point | None:
    x, y = memory[site], memory[site + 1]
    if x == y == 0:
        return None
    return x - 128, y - 128


def _write_site(memory: bytearray, site: int, x: float, y: float) -> None:
    x_byte = (128 + round(x)) % 256
    y_byte = (128 + round(y)) % 256
    if x_byte == y_byte == 0:
        x_byte = 1  # Keep (0, 0) available for an undiscovered site.
    memory[site], memory[site + 1] = x_byte, y_byte


def _correct_center(x: float, y: float, inside: bool) -> Point:
    """Use today's zone reading to correct the center estimated from drift."""
    distance = hypot(x, y)
    if distance == 0 or inside == (distance <= _RADIUS):
        return x, y
    # Inside puts the center within one radius; outside puts it farther away.
    correction = _RADIUS - distance
    if abs(correction) <= 6:
        edge = _RADIUS / distance
        stored_distance = hypot(round(x * edge), round(y * edge))
        if inside != (stored_distance <= _RADIUS):
            correction += -1 if inside else 1  # Cross the boundary after byte rounding.
    scale = 1 + max(-6.0, min(6.0, correction)) / distance
    return x * scale, y * scale


def _observe_currents(s: JellyfishSnapshot) -> tuple[int, int, int, int]:
    sector = 1 + round(s.heading * _SECTORS / 360) % _SECTORS
    slot, half = divmod(s.depth, 2)
    shift = 4 * half
    s.memory[slot] = (s.memory[slot] & ~(15 << shift)) | (sector << shift)
    first, second = s.memory[0], s.memory[1]
    return first & 15, first >> 4, second & 15, second >> 4


def _danger_cost(danger: Point | None, x: float, y: float) -> float:
    if danger is None:
        return 0.0
    # We saw part of a predator zone. Give that spot a berth smaller than its radius.
    return 3 * max(0.0, (0.9 * _RADIUS) ** 2 - _distance_sq(danger, x, y))


class Player5(Player):
    """Spend summer at food and spend winter capacity at a safe nursery.

    Each jellyfish keeps its compass in bytes 0..1. The remaining six bytes
    hold the relative positions of food, nursery and danger, two bytes each.
    Offspring inherit these bearings and sites from their parent.
    """

    def act(self, s: JellyfishSnapshot) -> Action:
        breeding = (
            s.season in (Season.FALL, Season.WINTER) and s.reproduction_capacity > 0
        )
        inside = s.in_breeding_zone if breeding else s.in_feeding_zone
        if len(s.memory) < 8:
            return self._simple(s, breeding, inside)

        headings = _observe_currents(s)
        site = _NURSERY if breeding else _FOOD
        self._update_map(s, site)
        danger = _read_site(s.memory, _DANGER)
        if s.in_predator_zone:
            return Action(self._escape(headings, danger))

        # Sample each layer once. The currents then stay fixed for the whole run.
        if 0 in headings:
            return Action(Depth(headings.index(0)))
        currents = tuple(_DRIFT[d][headings[d]] for d in _DEPTHS)
        center = _read_site(s.memory, site)
        if center is None:
            return self._explore(s)

        goal = self._safe_side(center, danger)
        if inside:
            return Action(self._hold(goal, danger, currents))
        if _distance_sq(goal, 0, 0) <= 4:
            goal = center  # The estimated safe side was just outside the patch.
        goal = self._detour(goal, danger)
        course = self._travel(goal, danger, currents)
        return self._explore(s) if course is None else Action(course)

    @staticmethod
    def _safe_side(goal: Point, danger: Point | None) -> Point:
        """If two zones overlap, aim for the half of the useful patch facing away."""
        if danger is None:
            return goal
        dx, dy = _wrap(goal[0] - danger[0]), _wrap(goal[1] - danger[1])
        separation = hypot(dx, dy)
        clearance = 1.25 * _RADIUS - separation
        if separation == 0 or clearance <= 0:
            return goal
        shift = min(clearance, 0.55 * _RADIUS) / separation
        return _wrap(goal[0] + dx * shift), _wrap(goal[1] + dy * shift)

    @staticmethod
    def _detour(goal: Point, danger: Point | None) -> Point:
        """If the direct route cuts across danger, pass on the nearer side."""
        if danger is None:
            return goal
        gx, gy = goal
        length_sq = gx * gx + gy * gy
        if length_sq == 0:
            return goal
        # Use the image of the hazard nearest the middle of this wrapped route.
        hx = gx / 2 + _wrap(danger[0] - gx / 2)
        hy = gy / 2 + _wrap(danger[1] - gy / 2)
        along = (hx * gx + hy * gy) / length_sq
        if not 0 < along < 1:
            return goal
        if hypot(hx - along * gx, hy - along * gy) >= 1.1 * _RADIUS:
            return goal

        # Two waypoints on opposite sides of the disk, perpendicular to its
        # bearing to the destination. Continue toward the nearer waypoint.
        dx, dy = _wrap(gx - hx), _wrap(gy - hy)
        length = hypot(dx, dy)
        if length == 0:
            return goal
        offset = 1.35 * _RADIUS / length
        left = (_wrap(hx - dy * offset), _wrap(hy + dx * offset))
        right = (_wrap(hx + dy * offset), _wrap(hy - dx * offset))
        return min((left, right), key=lambda p: p[0] * p[0] + p[1] * p[1])

    def _update_map(self, s: JellyfishSnapshot, target: int) -> None:
        # A baby starts where its parent spawned, before the parent's drift.
        first_turn = s.age_days == 0 or (
            s.age_days == 1 and (s.birth_year, s.birth_day_of_year) != (1, 1)
        )
        vx, vy = (0.0, 0.0) if first_turn else s.velocity
        # Round stochastically so repeated fractional steps do not bias the map.
        step_x = floor(vx / _CELL + self.rng.random())
        step_y = floor(vy / _CELL + self.rng.random())

        for site, inside in (
            (_FOOD, s.in_feeding_zone),
            (_NURSERY, s.in_breeding_zone),
            (_DANGER, s.in_predator_zone),
        ):
            old = _read_site(s.memory, site)
            if old is None:
                if inside:
                    inset = (0.5 if site == _DANGER else 0.25) * _RADIUS / s.speed
                    _write_site(s.memory, site, vx * inset, vy * inset)
                continue
            if first_turn:
                continue  # The parent already recorded this observation at the birth site.
            x, y = _wrap(old[0] - step_x), _wrap(old[1] - step_y)
            if not inside and site in (target, _DANGER) and x * x + y * y <= 4:
                # Check arrival before correction. Keep off-season sites for later visits.
                s.memory[site] = s.memory[site + 1] = 0
                continue
            if (
                inside
                and site != _DANGER
                and not s.in_predator_zone
                and hypot(x, y) > 0.7 * _RADIUS
            ):
                # We already found a safe patch near the rim. Anchor here instead
                # of crossing the zone again to reach an older estimate.
                inset = 0.25 * _RADIUS / s.speed
                x, y = vx * inset, vy * inset
            x, y = _correct_center(x, y, inside)
            _write_site(s.memory, site, x, y)

    @staticmethod
    def _escape(headings: tuple[int, ...], danger: Point | None) -> Depth:
        """Take the current that opens the most distance from the dangerous spot."""
        best_depth, best_distance = Depth.SURFACE, -1.0
        if danger is not None:
            for depth in _DEPTHS:
                if headings[depth]:
                    vx, vy = _DRIFT[depth][headings[depth]]
                    distance = _distance_sq(danger, 3 * vx, 3 * vy)
                    if distance > best_distance:
                        best_depth, best_distance = depth, distance
        return best_depth

    @staticmethod
    def _hold(goal: Point, danger: Point | None, currents: tuple[Point, ...]) -> Depth:
        """Inside a useful patch, just score tomorrow's four possible positions."""
        best_depth, best_score = Depth.DEEP, float("inf")
        for depth, (vx, vy) in zip(_DEPTHS, currents):
            score = _distance_sq(goal, vx, vy) + _danger_cost(danger, vx, vy)
            if score < best_score:
                best_depth, best_score = depth, score
        return best_depth

    @staticmethod
    def _travel(
        goal: Point, danger: Point | None, currents: tuple[Point, ...]
    ) -> Depth | None:
        """Try a short ride, with the option to change currents once along the way."""
        distance = _distance_sq(goal, 0, 0)
        short_leg = 2 if distance < (0.5 * _RADIUS) ** 2 else 8
        for days in (short_leg, 24):
            best_depth, best_score = None, distance
            legs = tuple((vx * days, vy * days) for vx, vy in currents)
            for depth, (x, y) in zip(_DEPTHS, legs):
                # How close could we come if we switched at the end of this ride?
                first_distance = _distance_sq(goal, x, y)
                closest = first_distance
                for vx, vy in legs:
                    end_x, end_y = x + vx, y + vy
                    cost = _distance_sq(goal, end_x, end_y) + _danger_cost(
                        danger, end_x, end_y
                    )
                    closest = min(closest, cost)
                # Prefer a safe first leg; break ties in favor of progress today.
                risk = max(
                    _danger_cost(danger, x / 2, y / 2), _danger_cost(danger, x, y)
                )
                score = 0.9 * closest + 0.1 * first_distance + risk
                if score < best_score:
                    best_depth, best_score = depth, score
            if best_depth is not None:
                return best_depth
        return None

    def _simple(self, s: JellyfishSnapshot, breeding: bool, inside: bool) -> Action:
        """In small-memory games remember the current that last entered the target."""
        if s.in_predator_zone:
            return Action(Depth.SURFACE)
        if inside:
            if s.depth != Depth.DEEP:
                s.memory[0] = (breeding << 2) | s.depth
            return Action(Depth.DEEP)
        if s.depth == Depth.DEEP:
            last_target, entry_depth = divmod(s.memory[0], 4)
            if last_target == breeding:
                return Action(Depth(entry_depth))
        return self._explore(s)

    def _explore(self, s: JellyfishSnapshot) -> Action:
        # Ride one current for a while, so the search covers new water.
        if s.depth == Depth.DEEP or self.rng.randrange(12) == 0:
            return Action(self.rng.choice(_SEARCH_DEPTHS))
        return Action(s.depth)
