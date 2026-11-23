"""Group 3's jellyfish: explore, find the feeding zone, then commute.

Design: players/group3/docs/algorithm.md. All per-jellyfish state lives in the
jellyfish memory (see memory.py); the math lives in navigation.py. Everything
here is a pure function of (snapshot, decoded memory).
"""

from __future__ import annotations

from core import constants
from core.action import Action
from core.depth import Depth
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot
from players.group3 import navigation
from players.group3.memory import (
    MAXIMUM_INTERIOR_POINTS_PER_ZONE,
    JellyfishMemory,
    Mode,
    Point,
    ZoneIndex,
    ZoneKnowledge,
    read_memory,
    required_memory_bytes,
    write_memory,
)

# Loitering jellyfish head back to their anchor beyond this distance.
MAXIMUM_DISTANCE_FROM_ANCHOR_KM = 100.0
# Re-plans allowed when a travel plan ends outside the target zone.
MAXIMUM_TRAVEL_RETRIES = 2
# Safety margin when deciding whether we can still reach the breeding zone.
BREEDING_ARRIVAL_MARGIN_DAYS = 5
# Mode changes chained within one day (guards against handler ping-pong).
MAXIMUM_MODE_TRANSITIONS_PER_DAY = 6

LAST_DAY_OF_WINTER = constants.DAYS_PER_YEAR
START_POSITION: Point = (0.0, 0.0)  # every stored position is relative to it
FALLBACK_DEPTH = Depth.DEEP
# Interior points are only remembered when this far from the stored ones.
MINIMUM_INTERIOR_POINT_SPACING_KM = 40.0
# A stored center this inconsistent with what we sense is thrown away.
CENTER_CONTRADICTION_TOLERANCE_KM = 60.0


class Player3(Player):
    """Group 3's jellyfish policy (stateless: memory is `snapshot.memory`)."""

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        if self.memory_size < required_memory_bytes(self.memory_size):
            # Not enough memory for this design: drift slowly, eat and breed.
            return Action(FALLBACK_DEPTH)

        state = read_memory(snapshot.memory)
        update_knowledge(state, snapshot)
        chosen_depth = choose_depth(state, snapshot)
        write_memory(snapshot.memory, state)
        # Eating / reproducing are no-ops outside the right zone and season.
        return Action(chosen_depth, eat=True, reproduce=True)


# ------------------------------------------------------------------ sensing
def is_original_jellyfish(snapshot: JellyfishSnapshot) -> bool:
    """Originals are the only jellyfish born on day 1 of year 1."""
    return snapshot.birth_year == 1 and snapshot.birth_day_of_year == 1


def is_newborn_first_day(snapshot: JellyfishSnapshot) -> bool:
    """True on an offspring's first act(): it has not drifted yet."""
    return snapshot.age_days == 1 and not is_original_jellyfish(snapshot)


def sensed_zone_membership(snapshot: JellyfishSnapshot) -> dict[ZoneIndex, bool]:
    return {
        ZoneIndex.FEEDING: snapshot.in_feeding_zone,
        ZoneIndex.BREEDING: snapshot.in_breeding_zone,
        ZoneIndex.PREDATOR: snapshot.in_predator_zone,
    }


def update_knowledge(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """Fold today's senses into memory before deciding anything."""
    if not state.is_initialized:
        initialize_original(state, snapshot)
    elif is_newborn_first_day(snapshot):
        initialize_newborn(state, snapshot)
    else:
        # snapshot.velocity is the current we drifted with since yesterday.
        state.position = navigation.wrap_point(
            navigation.add_vectors(state.position, snapshot.velocity)
        )
        record_zone_border_crossings(state, snapshot)

    review_zone_knowledge(state, snapshot)
    record_current_heading(state, snapshot)
    record_feeding_entry_point(state, snapshot)
    count_eating_day(state, snapshot)


def initialize_original(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """Day 1 of a first-generation jellyfish: blank memory, start exploring."""
    state.is_initialized = True
    state.mode = Mode.DISCOVER_CURRENTS
    state.position = START_POSITION
    remember_zone_membership(state, snapshot)


def initialize_newborn(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """First day of an offspring: keep the parent's map, reset personal state.

    The inherited position is already correct (born at the parent's position
    and not moved since), so there is no dead-reckoning update today.
    """
    state.mode = Mode.AT_BREEDING
    clear_plan(state)
    state.lifetime_eat_days = 0
    state.summer_feed_days = 0
    remember_zone_membership(state, snapshot)


def remember_zone_membership(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> None:
    for zone_index, is_inside in sensed_zone_membership(snapshot).items():
        state.zones[zone_index].was_inside_yesterday = is_inside


def record_current_heading(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """Store the direction of the current at today's depth if still unknown."""
    depth_index = int(snapshot.depth)
    if not state.current_heading_known[depth_index]:
        state.current_heading_known[depth_index] = True
        state.current_heading_steps[depth_index] = navigation.heading_degrees_to_steps(
            snapshot.heading
        )


def record_feeding_entry_point(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> None:
    """Remember the first spot known to be inside the feeding zone."""
    if snapshot.in_feeding_zone and not state.feeding_entry_point_known:
        state.feeding_entry_point_known = True
        state.feeding_entry_point = state.position


def count_eating_day(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """Mirror the engine's eating counters (we always eat when possible)."""
    if snapshot.season != Season.SUMMER:
        state.summer_feed_days = 0
        return
    if snapshot.in_feeding_zone:
        if state.lifetime_eat_days >= constants.EAT_DAYS_TO_MATURE:
            state.summer_feed_days += 1
        state.lifetime_eat_days += 1


# ------------------------------------------------------ zone center tracking
def record_zone_border_crossings(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> None:
    """Detect entering / exiting each zone and try to pin down its center."""
    for zone_index, is_inside in sensed_zone_membership(snapshot).items():
        zone = state.zones[zone_index]
        if is_inside != zone.was_inside_yesterday and not zone.center_known:
            record_border_crossing(
                zone,
                state.position,
                snapshot.velocity,
                is_entry=is_inside,
            )
        zone.was_inside_yesterday = is_inside


def record_border_crossing(
    zone: ZoneKnowledge,
    position: Point,
    velocity: Point,
    is_entry: bool,
) -> None:
    """Pair this crossing with the stored one; otherwise keep it for later."""
    border_point = navigation.approximate_border_point(position, velocity)
    if zone.border_crossing_known:
        estimated_center = navigation.estimate_zone_center(
            zone.border_crossing_point,
            navigation.inward_direction(
                zone.border_crossing_velocity, zone.border_crossing_is_entry
            ),
            border_point,
            navigation.inward_direction(velocity, is_entry),
            tuple(zone.interior_points),
        )
        if estimated_center is not None:
            zone.center_known = True
            zone.center = estimated_center
            zone.border_crossing_known = False
            return
    # No partner yet, or the pair was unusable: keep the latest crossing.
    zone.border_crossing_known = True
    zone.border_crossing_is_entry = is_entry
    zone.border_crossing_point = border_point
    zone.border_crossing_velocity = velocity


def review_zone_knowledge(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> None:
    """Daily upkeep per zone: collect interior points, drop disproven centers."""
    for zone_index, is_inside in sensed_zone_membership(snapshot).items():
        zone = state.zones[zone_index]
        if zone.center_known:
            discard_center_if_contradicted(zone, state.position, is_inside)
        elif is_inside:
            remember_interior_point(zone, state.position)


def remember_interior_point(zone: ZoneKnowledge, position: Point) -> None:
    """Keep a handful of well-separated positions known to be inside the zone."""
    if len(zone.interior_points) >= MAXIMUM_INTERIOR_POINTS_PER_ZONE:
        return
    is_far_from_stored_points = all(
        navigation.torus_distance(position, stored_point)
        >= MINIMUM_INTERIOR_POINT_SPACING_KM
        for stored_point in zone.interior_points
    )
    if is_far_from_stored_points:
        zone.interior_points.append(position)


def discard_center_if_contradicted(
    zone: ZoneKnowledge, position: Point, is_inside: bool
) -> None:
    """Forget a center estimate that clearly disagrees with today's sensing."""
    distance_from_center = navigation.torus_distance(position, zone.center)
    tolerance = CENTER_CONTRADICTION_TOLERANCE_KM
    is_contradicted = (
        distance_from_center > navigation.ZONE_RADIUS + tolerance
        if is_inside
        else distance_from_center < navigation.ZONE_RADIUS - tolerance
    )
    if is_contradicted:
        zone.center_known = False
        zone.border_crossing_known = False
        zone.interior_points = [position] if is_inside else []


def best_known_zone_point(
    state: JellyfishMemory, zone_index: ZoneIndex
) -> Point | None:
    """Best travel target / loiter anchor for a zone: its center if known."""
    zone = state.zones[zone_index]
    if zone.center_known:
        return zone.center
    if zone_index == ZoneIndex.BREEDING:
        return START_POSITION  # the original ancestor started inside it
    if zone_index == ZoneIndex.FEEDING and state.feeding_entry_point_known:
        return state.feeding_entry_point
    return None


# ------------------------------------------------------------ plan execution
def current_velocities(state: JellyfishMemory) -> list[Point]:
    return navigation.velocities_from_heading_steps(state.current_heading_steps)


def set_plan(state: JellyfishMemory, plan: navigation.MovementPlan, repeats: bool):
    state.plan_days_per_depth = list(plan)
    state.current_day_in_plan = 0
    state.plan_repeats = repeats


def clear_plan(state: JellyfishMemory) -> None:
    set_plan(state, [0] * navigation.NUMBER_OF_DEPTHS, repeats=False)


def is_plan_finished(state: JellyfishMemory) -> bool:
    """True when there is no day left to execute (repeating plans never end)."""
    total_days = navigation.plan_total_days(state.plan_days_per_depth)
    return total_days == 0 or state.current_day_in_plan >= total_days


def is_loitering(state: JellyfishMemory) -> bool:
    return state.plan_repeats and not is_plan_finished(state)


def follow_plan(state: JellyfishMemory) -> Depth:
    """Depth for today's plan day; advances (and wraps) the day counter."""
    if is_plan_finished(state):
        return FALLBACK_DEPTH
    depth_index = navigation.depth_index_for_plan_day(
        state.plan_days_per_depth, state.current_day_in_plan
    )
    state.current_day_in_plan += 1
    if state.plan_repeats and is_plan_finished(state):
        state.current_day_in_plan = 0
    return Depth(depth_index)


def plan_travel_to(state: JellyfishMemory, destination: Point):
    """Travel plan from the current position, or None if nothing gets there."""
    displacement = navigation.torus_displacement(state.position, destination)
    return navigation.plan_travel(displacement, current_velocities(state))


def begin_travel(
    state: JellyfishMemory, travel_mode: Mode, plan: navigation.MovementPlan | None
) -> None:
    state.mode = travel_mode
    state.travel_retry_count = 0
    if plan is None:
        clear_plan(state)
    else:
        set_plan(state, plan, repeats=False)


def begin_comb_search(state: JellyfishMemory) -> None:
    state.mode = Mode.COMB_SEARCH
    set_plan(state, navigation.plan_comb(current_velocities(state)), repeats=True)


# ------------------------------------------------------------ season helpers
def expected_reproduction_capacity(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> int:
    """Offspring we can (or will be able to) produce this coming winter.

    The engine only assigns capacity on the first day of fall, so during
    summer we predict it from our own feed-day count. Capacity still showing
    in spring is stale: it is wiped before the next winter.
    """
    if snapshot.season == Season.SUMMER:
        return state.summer_feed_days // constants.EAT_DAYS_PER_OFFSPRING
    if snapshot.season in (Season.FALL, Season.WINTER):
        return snapshot.reproduction_capacity
    return 0


def can_arrive_before_winter_ends(
    snapshot: JellyfishSnapshot, travel_days: int, days_needed_after_arrival: int = 0
) -> bool:
    arrival_day = snapshot.day_of_year + travel_days
    return arrival_day + days_needed_after_arrival <= LAST_DAY_OF_WINTER


# -------------------------------------------------------------- mode handlers
# Each handler returns today's depth, or None after switching `state.mode`
# (the new mode's handler is then run on the same day).
def choose_depth(state: JellyfishMemory, snapshot: JellyfishSnapshot) -> Depth:
    for _ in range(MAXIMUM_MODE_TRANSITIONS_PER_DAY):
        chosen_depth = MODE_HANDLERS[state.mode](state, snapshot)
        if chosen_depth is not None:
            return chosen_depth
    return FALLBACK_DEPTH


def handle_discover_currents(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    """Days 1-4 of an original: sample each depth once."""
    for depth in Depth:
        if not state.current_heading_known[depth]:
            return depth
    begin_comb_search(state)
    return None


def handle_comb_search(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    """Sweep the ocean until the feeding zone is sensed."""
    if snapshot.in_feeding_zone:
        state.mode = Mode.AT_FEEDING
        clear_plan(state)
        return None
    return follow_plan(state)


def handle_travel(
    state: JellyfishMemory,
    snapshot: JellyfishSnapshot,
    target_zone: ZoneIndex,
    arrival_mode: Mode,
) -> Depth | None:
    """Run a one-shot travel plan; re-plan a few times if it misses the zone."""
    if not is_plan_finished(state):
        return follow_plan(state)

    is_in_target_zone = sensed_zone_membership(snapshot)[target_zone]
    if not is_in_target_zone and state.travel_retry_count < MAXIMUM_TRAVEL_RETRIES:
        state.travel_retry_count += 1
        destination = best_known_zone_point(state, target_zone)
        plan = plan_travel_to(state, destination) if destination else None
        if plan is not None and navigation.plan_total_days(plan) > 0:
            set_plan(state, plan, repeats=False)
            return follow_plan(state)

    # Arrived, or out of retries / ideas: hold station anyway.
    state.mode = arrival_mode
    clear_plan(state)
    return None


def handle_travel_to_feeding(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    return handle_travel(state, snapshot, ZoneIndex.FEEDING, Mode.AT_FEEDING)


def handle_travel_to_breeding(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    return handle_travel(state, snapshot, ZoneIndex.BREEDING, Mode.AT_BREEDING)


def hold_station(
    state: JellyfishMemory, snapshot: JellyfishSnapshot, zone_index: ZoneIndex
) -> Depth:
    """Loiter around the zone's anchor, heading back whenever we stray."""
    # TODO(predator): shift the anchor out of the predator zone when it overlaps.
    if not state.plan_repeats and not is_plan_finished(state):
        return follow_plan(state)  # still on the way back to the anchor

    anchor = best_known_zone_point(state, zone_index) or state.position
    distance_from_anchor = navigation.torus_distance(state.position, anchor)
    is_in_zone = sensed_zone_membership(snapshot)[zone_index]
    if distance_from_anchor > MAXIMUM_DISTANCE_FROM_ANCHOR_KM or not is_in_zone:
        return_plan = plan_travel_to(state, anchor)
        if return_plan is not None and navigation.plan_total_days(return_plan) > 0:
            set_plan(state, return_plan, repeats=False)
            return follow_plan(state)

    if not is_loitering(state):
        loiter_plan = navigation.plan_loiter_for_headings(state.current_heading_steps)
        set_plan(state, loiter_plan, repeats=True)
    return follow_plan(state)


def try_leaving_feeding_for_breeding(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> bool:
    """Start the trip to the breeding zone when it is time; True if we left.

    - Fall / winter with capacity: go, as long as we can still arrive in winter.
    - Summer: stay and keep feeding. Only when we have drifted out anyway and
      waiting longer would make us miss the winter do we leave early.
    - Otherwise (no capacity, or spring): stay and wait for the next summer.
    """
    capacity = expected_reproduction_capacity(state, snapshot)
    if capacity < 1:
        return False
    if snapshot.season == Season.SUMMER and snapshot.in_feeding_zone:
        return False

    destination = best_known_zone_point(state, ZoneIndex.BREEDING)
    plan = plan_travel_to(state, destination)
    if plan is None:
        return False
    travel_days = navigation.plan_total_days(plan)
    if snapshot.season == Season.SUMMER:
        # Leave only if returning to feed first would risk the whole winter.
        days_needed = capacity + BREEDING_ARRIVAL_MARGIN_DAYS
        if can_arrive_before_winter_ends(snapshot, travel_days, days_needed):
            return False
    elif not can_arrive_before_winter_ends(snapshot, travel_days):
        return False

    begin_travel(state, Mode.TRAVEL_TO_BREEDING, plan)
    return True


def handle_at_feeding(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    """Wait for summer and feed; leave for the breeding zone once fed."""
    if try_leaving_feeding_for_breeding(state, snapshot):
        return None
    return hold_station(state, snapshot, ZoneIndex.FEEDING)


def handle_at_breeding(
    state: JellyfishMemory, snapshot: JellyfishSnapshot
) -> Depth | None:
    """Wait for winter and breed; head for the feeding zone once done."""
    can_still_breed = (
        snapshot.season in (Season.FALL, Season.WINTER)
        and snapshot.reproduction_capacity > 0
    )
    if can_still_breed:
        return hold_station(state, snapshot, ZoneIndex.BREEDING)

    feeding_destination = best_known_zone_point(state, ZoneIndex.FEEDING)
    if feeding_destination is None:
        begin_comb_search(state)  # should not happen: parents have fed before
        return None
    begin_travel(
        state, Mode.TRAVEL_TO_FEEDING, plan_travel_to(state, feeding_destination)
    )
    return None


MODE_HANDLERS = {
    Mode.DISCOVER_CURRENTS: handle_discover_currents,
    Mode.COMB_SEARCH: handle_comb_search,
    Mode.AT_FEEDING: handle_at_feeding,
    Mode.TRAVEL_TO_BREEDING: handle_travel_to_breeding,
    Mode.AT_BREEDING: handle_at_breeding,
    Mode.TRAVEL_TO_FEEDING: handle_travel_to_feeding,
}
