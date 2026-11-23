"""Pure navigation math for group 3's jellyfish (no memory, no simulator state).

Conventions:
- A *point* / *velocity* is an (x, y) tuple in km (x east, y south).
- Positions live on a 1000 km torus and are kept wrapped onto [-500, 500).
- A *movement plan* is a list with the number of days to ride each depth,
  executed in depth order (surface first).
"""

from __future__ import annotations

from functools import lru_cache
from itertools import product
from math import ceil, cos, hypot, pi, sin, sqrt

from core import constants

Point = tuple[float, float]
MovementPlan = list[int]

OCEAN_SIZE = constants.OCEAN_SIZE
HALF_OCEAN_SIZE = OCEAN_SIZE / 2
ZONE_RADIUS = constants.ZONE_RADIUS
CURRENT_SPEEDS = constants.CURRENT_SPEEDS
NUMBER_OF_DEPTHS = len(CURRENT_SPEEDS)
HEADING_STEPS_PER_CIRCLE = 1 << 16

# Zone center estimation.
MINIMUM_USABLE_CHORD_KM = 60.0  # shorter chords are too sensitive to error
# Mirror candidates this close to the chord midpoint are treated as one point.
NEGLIGIBLE_MIRROR_OFFSET_KM = 20.0

# Travel planning.
TORUS_IMAGE_RANGE = 1  # 3x3 copies of the destination
FALLBACK_TORUS_IMAGE_RANGE = 3  # wider search when currents are near-degenerate
MAXIMUM_ROUNDING_FIX_STEPS = 4
NEGATIVE_DAYS_TOLERANCE = 1e-9

# Loiter planning.
MAXIMUM_LOITER_CYCLE_DAYS = 20
MAXIMUM_LOITER_EXCURSION_KM = 50.0

# Comb (grid search) planning.
COMB_MAIN_LEG_DAYS = 25  # 25 days at the surface = one 1000 km sweep
COMB_LANE_SPACING_KM = 333.0
MAXIMUM_COMB_SECONDARY_DAYS = 60


# ------------------------------------------------------------ torus geometry
def wrap_centered(coordinate: float) -> float:
    """Wrap one coordinate onto [-500, 500)."""
    return (coordinate + HALF_OCEAN_SIZE) % OCEAN_SIZE - HALF_OCEAN_SIZE


def wrap_point(point: Point) -> Point:
    return (wrap_centered(point[0]), wrap_centered(point[1]))


def add_vectors(first: Point, second: Point) -> Point:
    return (first[0] + second[0], first[1] + second[1])


def torus_displacement(origin: Point, destination: Point) -> Point:
    """Shortest vector from origin to destination on the torus."""
    return (
        wrap_centered(destination[0] - origin[0]),
        wrap_centered(destination[1] - origin[1]),
    )


def torus_distance(first: Point, second: Point) -> float:
    return hypot(*torus_displacement(first, second))


# ---------------------------------------------------------- current headings
def heading_degrees_to_steps(heading_degrees: float) -> int:
    """Quantize a compass heading to uint16 steps of a full circle."""
    steps = round(heading_degrees / 360.0 * HEADING_STEPS_PER_CIRCLE)
    return steps % HEADING_STEPS_PER_CIRCLE


def velocity_from_heading_steps(heading_steps: int, speed: float) -> Point:
    """Velocity of a current (compass heading: 0 = north = -y, 90 = east = +x)."""
    heading_radians = heading_steps / HEADING_STEPS_PER_CIRCLE * 2 * pi
    return (speed * sin(heading_radians), -speed * cos(heading_radians))


def velocities_from_heading_steps(heading_steps_per_depth: list[int]) -> list[Point]:
    """Velocity of the current at every depth (speeds are fixed by the rules)."""
    return [
        velocity_from_heading_steps(heading_steps, speed)
        for heading_steps, speed in zip(heading_steps_per_depth, CURRENT_SPEEDS)
    ]


# ------------------------------------------------------- zone center estimate
def approximate_border_point(position_after_crossing: Point, velocity: Point) -> Point:
    """Border point of a crossing detected today: halfway along yesterday's drift."""
    return wrap_point(
        (
            position_after_crossing[0] - velocity[0] / 2,
            position_after_crossing[1] - velocity[1] / 2,
        )
    )


def inward_direction(velocity: Point, is_entry: bool) -> Point:
    """Direction pointing into the zone at a crossing (reverse it for exits)."""
    return velocity if is_entry else (-velocity[0], -velocity[1])


def estimate_zone_center(
    first_border_point: Point,
    first_inward_direction: Point,
    second_border_point: Point,
    second_inward_direction: Point,
    known_interior_points: tuple[Point, ...] = (),
    radius: float = ZONE_RADIUS,
) -> Point | None:
    """Center of the circle through two border points, or None if unusable.

    The two points form a chord; the center lies on its perpendicular bisector
    at distance sqrt(r^2 - half_chord^2) from the midpoint, on either side.
    The true center must lie on the inward side of both crossings and within
    one radius of every known interior point. The estimate is only returned
    when exactly one of the two mirror candidates passes (a straight pass
    through the zone cannot tell them apart).
    """
    # Unwrap the second point next to the first so the chord is a plain vector.
    chord = torus_displacement(first_border_point, second_border_point)
    chord_length = hypot(*chord)
    if chord_length < MINIMUM_USABLE_CHORD_KM:
        return None

    half_chord = min(chord_length / 2, radius)  # clamp approximation overshoot
    midpoint_to_center = sqrt(radius * radius - half_chord * half_chord)
    midpoint = (
        first_border_point[0] + chord[0] / 2,
        first_border_point[1] + chord[1] / 2,
    )
    if midpoint_to_center <= NEGLIGIBLE_MIRROR_OFFSET_KM:
        return wrap_point(midpoint)  # near-diameter chord: candidates coincide

    chord_normal = (-chord[1] / chord_length, chord[0] / chord_length)
    crossings = (
        (first_border_point, first_inward_direction),
        (second_border_point, second_inward_direction),
    )

    def is_consistent(candidate_center: Point) -> bool:
        for border_point, inward in crossings:
            to_center = torus_displacement(border_point, candidate_center)
            if to_center[0] * inward[0] + to_center[1] * inward[1] <= 0:
                return False
        return all(
            torus_distance(interior_point, candidate_center) <= radius
            for interior_point in known_interior_points
        )

    consistent_centers = [
        candidate_center
        for candidate_center in (
            wrap_point(
                (
                    midpoint[0] + side * midpoint_to_center * chord_normal[0],
                    midpoint[1] + side * midpoint_to_center * chord_normal[1],
                )
            )
            for side in (1.0, -1.0)
        )
        if is_consistent(candidate_center)
    ]
    return consistent_centers[0] if len(consistent_centers) == 1 else None


# ------------------------------------------------------------ movement plans
def plan_total_days(plan: MovementPlan) -> int:
    return sum(plan)


def depth_index_for_plan_day(plan: MovementPlan, day_in_plan: int) -> int:
    """Depth to ride on a given (0-based) day of a plan; legs run in depth order."""
    days_before_leg = 0
    for depth_index, leg_days in enumerate(plan):
        if day_in_plan < days_before_leg + leg_days:
            return depth_index
        days_before_leg += leg_days
    return NUMBER_OF_DEPTHS - 1  # past the end: default to the slowest current


def plan_net_displacement(plan: MovementPlan, velocities: list[Point]) -> Point:
    return (
        sum(days * velocity[0] for days, velocity in zip(plan, velocities)),
        sum(days * velocity[1] for days, velocity in zip(plan, velocities)),
    )


# ------------------------------------------------------------ travel planning
def _solve_two_current_days(
    first_velocity: Point, second_velocity: Point, displacement: Point
) -> tuple[float, float] | None:
    """Fractional days (a, b) with a*first + b*second = displacement, both >= 0."""
    determinant = (
        first_velocity[0] * second_velocity[1] - first_velocity[1] * second_velocity[0]
    )
    if abs(determinant) < 1e-9:
        return None  # parallel currents cannot span the plane
    first_days = (
        displacement[0] * second_velocity[1] - displacement[1] * second_velocity[0]
    ) / determinant
    second_days = (
        first_velocity[0] * displacement[1] - first_velocity[1] * displacement[0]
    ) / determinant
    if first_days < -NEGATIVE_DAYS_TOLERANCE or second_days < -NEGATIVE_DAYS_TOLERANCE:
        return None
    return (max(first_days, 0.0), max(second_days, 0.0))


def _fractional_plan_candidates(
    displacement: Point, velocities: list[Point], image_range: int
) -> list[tuple[list[float], Point]]:
    """Every two-current way to reach any torus image of the destination.

    For one image, the least-days linear program has an optimum using at most
    two currents, so pairs of currents are all that need enumerating. Each
    candidate is (fractional days per depth, unwrapped displacement), and the
    list is sorted from fewest to most total days.
    """
    candidates: list[tuple[list[float], Point]] = []
    image_offsets = range(-image_range, image_range + 1)
    for horizontal_wraps in image_offsets:
        for vertical_wraps in image_offsets:
            image_displacement = (
                displacement[0] + horizontal_wraps * OCEAN_SIZE,
                displacement[1] + vertical_wraps * OCEAN_SIZE,
            )
            for first_depth in range(NUMBER_OF_DEPTHS):
                for second_depth in range(first_depth + 1, NUMBER_OF_DEPTHS):
                    solution = _solve_two_current_days(
                        velocities[first_depth],
                        velocities[second_depth],
                        image_displacement,
                    )
                    if solution is None:
                        continue
                    fractional_days = [0.0] * NUMBER_OF_DEPTHS
                    fractional_days[first_depth] = solution[0]
                    fractional_days[second_depth] = solution[1]
                    candidates.append((fractional_days, image_displacement))
    candidates.sort(key=lambda candidate: sum(candidate[0]))
    return candidates


def count_days_in_zone(
    plan: MovementPlan,
    velocities: list[Point],
    zone_center_offset: Point,
    radius: float = ZONE_RADIUS,
) -> int:
    """Days of a plan that start inside a zone (the engine senses once a day).

    `zone_center_offset` is the zone center relative to where the plan starts.
    The starting day itself is not counted: no plan can change it.
    """
    days_in_zone = 0
    position = (0.0, 0.0)
    for leg_days, velocity in zip(plan, velocities):
        for _ in range(leg_days):
            position = add_vectors(position, velocity)
            if torus_distance(position, zone_center_offset) <= radius:
                days_in_zone += 1
    return days_in_zone


def _safest_then_fastest_candidate(
    candidates: list[tuple[list[float], Point]],
    velocities: list[Point],
    predator_center_offset: Point | None,
) -> tuple[list[float], Point]:
    """Candidate with the fewest predator-zone days; ties go to the fastest."""
    if predator_center_offset is None:
        return candidates[0]
    best_candidate = candidates[0]
    fewest_predator_days: int | None = None
    for candidate in candidates:  # already sorted fastest first
        rounded_plan = [round(days) for days in candidate[0]]
        predator_days = count_days_in_zone(
            rounded_plan, velocities, predator_center_offset
        )
        if fewest_predator_days is None or predator_days < fewest_predator_days:
            fewest_predator_days, best_candidate = predator_days, candidate
        if predator_days == 0:
            break  # fastest fully safe route: nothing later can beat it
    return best_candidate


def _reduce_rounding_error(
    plan: MovementPlan, velocities: list[Point], displacement: Point
) -> MovementPlan:
    """Nudge every leg by -1 / 0 / +1 day (jointly) while the plan gets closer."""
    plan = list(plan)
    achieved = plan_net_displacement(plan, velocities)
    residual = (displacement[0] - achieved[0], displacement[1] - achieved[1])
    for _ in range(MAXIMUM_ROUNDING_FIX_STEPS):
        best_error = hypot(*residual)
        best_changes: tuple[int, ...] | None = None
        for day_changes in product((-1, 0, 1), repeat=NUMBER_OF_DEPTHS):
            if any(days + change < 0 for days, change in zip(plan, day_changes)):
                continue
            shift = plan_net_displacement(list(day_changes), velocities)
            error = hypot(residual[0] - shift[0], residual[1] - shift[1])
            if error < best_error - 1e-9:
                best_error, best_changes = error, day_changes
        if best_changes is None:
            break
        plan = [days + change for days, change in zip(plan, best_changes)]
        shift = plan_net_displacement(list(best_changes), velocities)
        residual = (residual[0] - shift[0], residual[1] - shift[1])
    return plan


def plan_travel(
    displacement: Point,
    velocities: list[Point],
    predator_center_offset: Point | None = None,
) -> MovementPlan | None:
    """Whole-day plan that covers `displacement`, safest route first.

    Among the routes to every torus image of the destination, prefer the one
    spending the fewest days in the predator zone (when its center, given
    relative to the start, is known), then the one taking the fewest days.
    Returns None when no combination of currents can reach any torus image of
    the destination (currents all but parallel).
    """
    candidates = _fractional_plan_candidates(
        displacement, velocities, TORUS_IMAGE_RANGE
    ) or _fractional_plan_candidates(
        displacement, velocities, FALLBACK_TORUS_IMAGE_RANGE
    )
    if not candidates:
        return None
    fractional_days, image_displacement = _safest_then_fastest_candidate(
        candidates, velocities, predator_center_offset
    )
    rounded_plan = [round(days) for days in fractional_days]
    return _reduce_rounding_error(rounded_plan, velocities, image_displacement)


# ------------------------------------------------------------ loiter planning
def plan_loiter(velocities: list[Point]) -> MovementPlan:
    """Repeating plan (1..20 days) with the least net drift per cycle.

    The path may never stray more than MAXIMUM_LOITER_EXCURSION_KM from where
    the cycle starts. Ties go to the shorter cycle. With degenerate currents
    this naturally falls back to riding the slowest current.
    """
    slowest_depth_only = [0] * (NUMBER_OF_DEPTHS - 1) + [1]
    best_plan = slowest_depth_only
    best_score = (float("inf"), 0)

    def search(depth_index: int, days_left: int, plan: list[int], position: Point):
        nonlocal best_plan, best_score
        if depth_index == NUMBER_OF_DEPTHS:
            total_days = sum(plan)
            if total_days == 0:
                return
            score = (round(hypot(*position), 6), total_days)
            if score < best_score:
                best_score, best_plan = score, list(plan)
            return
        velocity = velocities[depth_index]
        for leg_days in range(days_left + 1):
            leg_end = (
                position[0] + leg_days * velocity[0],
                position[1] + leg_days * velocity[1],
            )
            # The path is piecewise linear, so its farthest point is a leg end.
            if hypot(*leg_end) > MAXIMUM_LOITER_EXCURSION_KM:
                continue
            plan.append(leg_days)
            search(depth_index + 1, days_left - leg_days, plan, leg_end)
            plan.pop()

    search(0, MAXIMUM_LOITER_CYCLE_DAYS, [], (0.0, 0.0))
    return best_plan


@lru_cache(maxsize=64)
def _cached_loiter_plan(heading_steps_per_depth: tuple[int, ...]) -> tuple[int, ...]:
    velocities = velocities_from_heading_steps(list(heading_steps_per_depth))
    return tuple(plan_loiter(velocities))


def plan_loiter_for_headings(heading_steps_per_depth: list[int]) -> MovementPlan:
    """Loiter plan for stored headings.

    The search is expensive and depends only on the currents, so the result is
    memoized (a pure-function cache, not per-jellyfish state).
    """
    return list(_cached_loiter_plan(tuple(heading_steps_per_depth)))


# -------------------------------------------------------------- comb planning
def plan_comb(velocities: list[Point]) -> MovementPlan:
    """Repeating grid-search plan: a long sweep, then a sideways lane change.

    Main leg: 25 days in the fastest (surface) current. Secondary leg: the
    other current with the largest speed perpendicular to the main one, ridden
    long enough to shift the next sweep by one lane spacing.
    """
    main_depth = 0  # surface is always the fastest current
    main_velocity = velocities[main_depth]
    main_speed = hypot(*main_velocity)
    main_normal = (-main_velocity[1] / main_speed, main_velocity[0] / main_speed)

    def perpendicular_speed(depth_index: int) -> float:
        velocity = velocities[depth_index]
        return abs(velocity[0] * main_normal[0] + velocity[1] * main_normal[1])

    secondary_depth = max(range(1, NUMBER_OF_DEPTHS), key=perpendicular_speed)
    secondary_speed = perpendicular_speed(secondary_depth)
    if secondary_speed * MAXIMUM_COMB_SECONDARY_DAYS <= COMB_LANE_SPACING_KM:
        secondary_days = MAXIMUM_COMB_SECONDARY_DAYS
    else:
        secondary_days = ceil(COMB_LANE_SPACING_KM / secondary_speed)

    plan = [0] * NUMBER_OF_DEPTHS
    plan[main_depth] = COMB_MAIN_LEG_DAYS
    plan[secondary_depth] = secondary_days
    return plan
