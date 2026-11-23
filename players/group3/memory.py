"""Memory interface for group 3's jellyfish.

The rest of the player only ever sees `JellyfishMemory` (a plain data class).
`read_memory` / `write_memory` are the only code that touches the raw bytes.

All positions are relative to the starting position of the original ancestor
and wrapped onto [-500, 500) km per axis (see navigation.wrap_centered).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from functools import cache

NUMBER_OF_DEPTHS = 4
HEADING_STEPS_PER_CIRCLE = 1 << 16  # headings are stored as uint16 steps
MAXIMUM_INTERIOR_POINTS_PER_ZONE = 6

Point = tuple[float, float]


class Mode(IntEnum):
    """What the jellyfish is currently trying to achieve."""

    DISCOVER_CURRENTS = 0  # originals, days 1-4: visit every depth once
    COMB_SEARCH = 1  # originals: sweep the ocean looking for the feeding zone
    AT_FEEDING = 2  # hold station in the feeding zone (wait / feed)
    TRAVEL_TO_BREEDING = 3
    AT_BREEDING = 4  # hold station in the breeding zone (wait / breed)
    TRAVEL_TO_FEEDING = 5


class ZoneIndex(IntEnum):
    """Index of each zone inside `JellyfishMemory.zones`."""

    FEEDING = 0
    BREEDING = 1
    PREDATOR = 2


@dataclass
class ZoneKnowledge:
    """Everything remembered about one circular zone."""

    was_inside_yesterday: bool = False
    # Estimated center, set once two usable border crossings were seen.
    center_known: bool = False
    center: Point = (0.0, 0.0)
    # Latest border crossing that has not been paired into a center yet.
    border_crossing_known: bool = False
    border_crossing_is_entry: bool = False
    border_crossing_point: Point = (0.0, 0.0)
    border_crossing_velocity: Point = (0.0, 0.0)
    # A few spread-out positions sensed inside the zone. They tell the two
    # mirror-image center candidates of a chord apart.
    interior_points: list[Point] = field(default_factory=list)


@dataclass
class JellyfishMemory:
    """Decoded view of the whole jellyfish memory."""

    is_initialized: bool = False  # False only for zeroed (day-1 original) memory
    mode: Mode = Mode.DISCOVER_CURRENTS

    # Dead-reckoned own position.
    position: Point = (0.0, 0.0)

    # Direction of the current at each depth, in uint16 steps of a circle.
    current_heading_known: list[bool] = field(
        default_factory=lambda: [False] * NUMBER_OF_DEPTHS
    )
    current_heading_steps: list[int] = field(
        default_factory=lambda: [0] * NUMBER_OF_DEPTHS
    )

    zones: list[ZoneKnowledge] = field(
        default_factory=lambda: [ZoneKnowledge() for _ in ZoneIndex]
    )

    # First position sensed inside the feeding zone: the travel target used
    # until the feeding zone center is known.
    feeding_entry_point_known: bool = False
    feeding_entry_point: Point = (0.0, 0.0)

    # Movement plan: days to spend at each depth, in depth order.
    plan_days_per_depth: list[int] = field(
        default_factory=lambda: [0] * NUMBER_OF_DEPTHS
    )
    current_day_in_plan: int = 0
    plan_repeats: bool = False  # comb / loiter plans repeat, travel plans run once
    travel_retry_count: int = 0

    # Own bookkeeping of eating, mirroring the engine (capacity is hidden in summer).
    lifetime_eat_days: int = 0
    summer_feed_days: int = 0


# --------------------------------------------------------------- byte layout
@dataclass(frozen=True)
class FieldFormats:
    """`struct` codes used for each kind of stored value."""

    flags: str
    small_integer: str
    heading: str
    day_count: str
    coordinate: str


def choose_field_formats(memory_size: int) -> FieldFormats:
    """Pick how many bytes each kind of value gets for a given memory size.

    Placeholder: this iteration targets the maximum 1024-byte memory, so the
    widths are hard-coded. A later iteration can shrink them as memory_size drops.
    """
    return FieldFormats(
        flags="I",  # uint32 bitmask
        small_integer="B",  # uint8 (mode, retry counter)
        heading="H",  # uint16 steps per circle
        day_count="H",  # uint16 days
        coordinate="f",  # float32 km
    )


FLAG_COUNT = 2 + NUMBER_OF_DEPTHS + 4 * len(ZoneIndex) + 1
# center, border crossing point, border crossing velocity, interior points
POINTS_PER_ZONE = 3 + MAXIMUM_INTERIOR_POINTS_PER_ZONE


@cache
def _build_struct(formats: FieldFormats) -> struct.Struct:
    """Fixed-order layout; must match _flatten_values / _restore_values."""
    layout = "<"
    layout += formats.flags
    layout += formats.small_integer * 2  # mode, travel_retry_count
    layout += formats.coordinate * 2  # position
    layout += formats.heading * NUMBER_OF_DEPTHS
    layout += formats.coordinate * (2 * POINTS_PER_ZONE * len(ZoneIndex))
    layout += formats.small_integer * len(ZoneIndex)  # interior point counts
    layout += formats.coordinate * 2  # feeding_entry_point
    layout += formats.day_count * NUMBER_OF_DEPTHS  # plan_days_per_depth
    layout += formats.day_count  # current_day_in_plan
    layout += formats.day_count * 2  # lifetime_eat_days, summer_feed_days
    return struct.Struct(layout)


def required_memory_bytes(memory_size: int) -> int:
    """Bytes the layout needs; the player falls back if memory is smaller."""
    return _build_struct(choose_field_formats(memory_size)).size


def _collect_flags(state: JellyfishMemory) -> list[bool]:
    """All booleans in a fixed order (packed into one bitmask)."""
    flags = [state.is_initialized, state.plan_repeats]
    flags += state.current_heading_known
    for zone in state.zones:
        flags += [
            zone.was_inside_yesterday,
            zone.center_known,
            zone.border_crossing_known,
            zone.border_crossing_is_entry,
        ]
    flags.append(state.feeding_entry_point_known)
    return flags


def _pack_flags(flags: list[bool]) -> int:
    return sum(1 << bit for bit, is_set in enumerate(flags) if is_set)


def _unpack_flags(bitmask: int) -> list[bool]:
    return [bool(bitmask >> bit & 1) for bit in range(FLAG_COUNT)]


def _clamp_day_count(days: int) -> int:
    return max(0, min(0xFFFF, int(days)))


def _flatten_values(state: JellyfishMemory) -> list[int | float]:
    values: list[int | float] = [_pack_flags(_collect_flags(state))]
    values += [int(state.mode), min(0xFF, state.travel_retry_count)]
    values += state.position
    values += [
        steps % HEADING_STEPS_PER_CIRCLE for steps in state.current_heading_steps
    ]
    for zone in state.zones:
        values += zone.center
        values += zone.border_crossing_point
        values += zone.border_crossing_velocity
        stored_points = zone.interior_points[:MAXIMUM_INTERIOR_POINTS_PER_ZONE]
        unused_slots = MAXIMUM_INTERIOR_POINTS_PER_ZONE - len(stored_points)
        for interior_point in stored_points + [(0.0, 0.0)] * unused_slots:
            values += interior_point
    for zone in state.zones:
        values.append(min(len(zone.interior_points), MAXIMUM_INTERIOR_POINTS_PER_ZONE))
    values += state.feeding_entry_point
    values += [_clamp_day_count(days) for days in state.plan_days_per_depth]
    values.append(_clamp_day_count(state.current_day_in_plan))
    values += [
        _clamp_day_count(state.lifetime_eat_days),
        _clamp_day_count(state.summer_feed_days),
    ]
    return values


def _restore_values(values: tuple[int | float, ...]) -> JellyfishMemory:
    remaining = iter(values)

    def take_point() -> Point:
        return (float(next(remaining)), float(next(remaining)))

    def take_integers(count: int) -> list[int]:
        return [int(next(remaining)) for _ in range(count)]

    flags = iter(_unpack_flags(int(next(remaining))))
    state = JellyfishMemory()
    state.is_initialized = next(flags)
    state.plan_repeats = next(flags)
    state.current_heading_known = [next(flags) for _ in range(NUMBER_OF_DEPTHS)]

    state.mode = Mode(int(next(remaining)))
    state.travel_retry_count = int(next(remaining))
    state.position = take_point()
    state.current_heading_steps = take_integers(NUMBER_OF_DEPTHS)

    for zone in state.zones:
        zone.was_inside_yesterday = next(flags)
        zone.center_known = next(flags)
        zone.border_crossing_known = next(flags)
        zone.border_crossing_is_entry = next(flags)
        zone.center = take_point()
        zone.border_crossing_point = take_point()
        zone.border_crossing_velocity = take_point()
        zone.interior_points = [
            take_point() for _ in range(MAXIMUM_INTERIOR_POINTS_PER_ZONE)
        ]
    for zone in state.zones:
        interior_point_count = int(next(remaining))
        zone.interior_points = zone.interior_points[:interior_point_count]

    state.feeding_entry_point_known = next(flags)
    state.feeding_entry_point = take_point()
    state.plan_days_per_depth = take_integers(NUMBER_OF_DEPTHS)
    state.current_day_in_plan = int(next(remaining))
    state.lifetime_eat_days, state.summer_feed_days = take_integers(2)
    return state


# ------------------------------------------------------------ public interface
def read_memory(raw_memory: bytearray) -> JellyfishMemory:
    """Decode the raw bytes. Zeroed memory decodes to `is_initialized=False`."""
    layout = _build_struct(choose_field_formats(len(raw_memory)))
    return _restore_values(layout.unpack_from(raw_memory, 0))


def write_memory(raw_memory: bytearray, state: JellyfishMemory) -> None:
    """Encode `state` into the raw bytes in place (length never changes)."""
    layout = _build_struct(choose_field_formats(len(raw_memory)))
    layout.pack_into(raw_memory, 0, *_flatten_values(state))
