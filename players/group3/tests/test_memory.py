"""Tests for the memory interface (dataclass <-> raw bytes)."""

import pytest

from players.group3.memory import (
    JellyfishMemory,
    Mode,
    ZoneIndex,
    read_memory,
    required_memory_bytes,
    write_memory,
)

MEMORY_SIZE = 1024


def test_layout_fits_in_maximum_memory():
    assert required_memory_bytes(MEMORY_SIZE) <= MEMORY_SIZE


def test_zeroed_memory_reads_as_uninitialized():
    state = read_memory(bytearray(MEMORY_SIZE))
    assert not state.is_initialized
    assert state.mode == Mode.DISCOVER_CURRENTS
    assert not any(state.current_heading_known)
    assert not any(zone.center_known for zone in state.zones)


def test_round_trip_preserves_every_field():
    state = JellyfishMemory(
        is_initialized=True,
        mode=Mode.TRAVEL_TO_FEEDING,
        position=(-123.5, 456.25),
        current_heading_known=[True, False, True, True],
        current_heading_steps=[1, 65535, 32768, 12345],
        feeding_entry_point_known=True,
        feeding_entry_point=(10.0, -20.0),
        plan_days_per_depth=[25, 0, 17, 300],
        current_day_in_plan=41,
        plan_repeats=True,
        travel_retry_count=2,
        lifetime_eat_days=95,
        summer_feed_days=60,
    )
    breeding = state.zones[ZoneIndex.BREEDING]
    breeding.was_inside_yesterday = True
    breeding.center_known = True
    breeding.center = (-499.5, 499.5)
    breeding.interior_points = [(0.0, 0.0), (40.5, -12.25)]
    predator = state.zones[ZoneIndex.PREDATOR]
    predator.border_crossing_known = True
    predator.border_crossing_is_entry = True
    predator.border_crossing_point = (1.5, 2.5)
    predator.border_crossing_velocity = (-40.0, 0.25)

    raw_memory = bytearray(MEMORY_SIZE)
    write_memory(raw_memory, state)
    assert len(raw_memory) == MEMORY_SIZE
    assert read_memory(raw_memory) == state


def test_position_survives_float32_storage():
    state = JellyfishMemory(is_initialized=True, position=(123.456789, -0.000123))
    raw_memory = bytearray(MEMORY_SIZE)
    write_memory(raw_memory, state)
    assert read_memory(raw_memory).position == pytest.approx(state.position, abs=1e-4)
