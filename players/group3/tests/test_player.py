"""Integration tests: Player3 running inside the real engine."""

import random

from core.args import MapArgs
from core.depth import Depth
from core.engine import Engine, Group, SimConfig
from core.geometry import torus_distance
from core.ocean import Ocean
from core.stats import GroupStats
from players.group3.memory import Mode, ZoneIndex, read_memory
from players.group3.player import Player3

MEMORY_SIZE = 1024
# Zones far apart, currents spanning the plane, predator out of the way.
FRIENDLY_MAP = MapArgs(
    feeding=(250.0, 250.0),
    breeding=(750.0, 700.0),
    predator=(250.0, 750.0),
    headings={
        Depth.SURFACE: 135,
        Depth.SHALLOW: 315,
        Depth.MEDIUM: 45,
        Depth.DEEP: 225,
    },
)


def make_engine(start_positions, days, memory_size=MEMORY_SIZE, seed=0) -> Engine:
    ocean = Ocean.generate(
        random.Random(seed),
        feeding=FRIENDLY_MAP.feeding,
        breeding=FRIENDLY_MAP.breeding,
        predator=FRIENDLY_MAP.predator,
        headings=FRIENDLY_MAP.headings,
    )
    config = SimConfig(
        memory_size=memory_size,
        lifetime_days=3 * 360,
        initial_jellyfish=len(start_positions),
        days=days,
        max_population=500,
    )
    group = Group(
        0,
        "3",
        "Group 3",
        Player3(memory_size, config.lifetime_days, random.Random(seed)),
        random.Random(seed),
        GroupStats(initial=len(start_positions)),
    )
    return Engine(ocean, [group], config, start_positions)


def test_small_memory_falls_back_without_crashing():
    engine = make_engine([(750.0, 700.0)], days=30, memory_size=8)
    engine.run()
    assert engine.groups[0].error is None
    assert engine.groups[0].alive[0].depth == Depth.DEEP


def test_originals_discover_all_currents_then_comb():
    engine = make_engine([(750.0, 700.0)], days=4)
    engine.run()
    state = read_memory(engine.groups[0].alive[0].memory)
    assert all(state.current_heading_known)
    assert state.mode == Mode.COMB_SEARCH
    for depth in Depth:
        expected_steps = round(FRIENDLY_MAP.headings[depth] / 360 * 65536)
        assert state.current_heading_steps[depth] == expected_steps


def test_dead_reckoning_matches_true_position_for_all_generations():
    """Stored position + ancestor start == real position, offspring included."""
    start = (700.0, 650.0)
    engine = make_engine([start], days=2 * 360)
    while not engine.finished:
        engine.step()
        for jellyfish in engine.groups[0].alive:
            if jellyfish.birth_t == engine.t - 1 and jellyfish.generation > 0:
                continue  # born today: memory is the parent's until its first act
            state = read_memory(jellyfish.memory)
            # Memory holds the position sensed this morning (before drifting).
            believed_x = start[0] + state.position[0]
            believed_y = start[1] + state.position[1]
            error = torus_distance(
                believed_x, believed_y, jellyfish.prev_x, jellyfish.prev_y
            )
            assert error < 0.5, (engine.t, jellyfish.id, error)
    assert engine.groups[0].error is None
    assert engine.groups[0].stats.births > 0


def test_full_life_cycle_finds_zones_and_grows():
    engine = make_engine([(750.0, 700.0), (700.0, 650.0), (800.0, 760.0)], days=3 * 360)
    engine.run()
    group = engine.groups[0]
    assert group.error is None
    assert group.stats.births > 0
    assert group.population > 3

    # Offspring inherit usable zone centers from their ancestors.
    youngest = max(group.alive, key=lambda jellyfish: jellyfish.generation)
    state = read_memory(youngest.memory)
    assert youngest.generation >= 1
    assert (
        state.zones[ZoneIndex.FEEDING].center_known or state.feeding_entry_point_known
    )
