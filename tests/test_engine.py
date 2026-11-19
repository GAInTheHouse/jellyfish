import random

import pytest

from core.action import Action
from core.depth import Depth
from core.engine import Engine, Group, SimConfig
from core.geometry import torus_delta, torus_distance, wrap
from core.ocean import Ocean
from core.parse_args import parse_args
from core.player import Player
from core.runner import build_engine
from core.seasons import Season, season_of
from core.stats import GroupStats
from core.zone import Zone, ZoneKind


# ----------------------------------------------------------------- helpers
class Const(Player):
    depth = Depth.DEEP

    def act(self, s):
        return Action(self.depth)


def make_engine(player_cls, ocean, starts, **cfg) -> Engine:
    config = SimConfig(
        memory_size=cfg.get("memory", 4),
        lifetime_days=cfg.get("lifetime", 3 * 360),
        initial_jellyfish=len(starts),
        days=cfg.get("days", 360),
        max_population=cfg.get("max_population", 1000),
    )
    g = Group(
        0,
        "x",
        "X",
        player_cls(config.memory_size, config.lifetime_days, random.Random(0)),
        random.Random(0),
        GroupStats(initial=len(starts)),
    )
    return Engine(ocean, [g], config, starts)


def still_ocean(**zones) -> Ocean:
    """Feeding+breeding overlap the same spot is illegal, so callers place them."""
    o = Ocean.generate(
        random.Random(0),
        feeding=zones.get("feeding", (100, 100)),
        breeding=zones.get("breeding", (600, 600)),
        predator=zones.get("predator", (100, 600)),
    )
    return o


# ------------------------------------------------------------------- tests
def test_torus_geometry():
    assert wrap(1005) == pytest.approx(5)
    assert wrap(-5) == pytest.approx(995)
    assert torus_delta(990, 10) == pytest.approx(20)
    assert torus_delta(10, 990) == pytest.approx(-20)
    assert torus_distance(995, 995, 5, 5) == pytest.approx(14.142, abs=1e-3)


def test_zone_wraps_edges():
    z = Zone(ZoneKind.FEEDING, 990, 990)
    assert z.contains(50, 50)
    assert not z.contains(500, 500)


def test_seasons():
    assert season_of(1) == Season.SPRING
    assert season_of(91) == Season.SUMMER
    assert season_of(180) == Season.SUMMER
    assert season_of(181) == Season.FALL
    assert season_of(360) == Season.WINTER


def test_generated_zones_disjoint():
    for seed in range(200):
        o = Ocean.generate(random.Random(seed))
        assert (
            torus_distance(o.feeding.x, o.feeding.y, o.breeding.x, o.breeding.y) > 400
        )


def test_drift_follows_current():
    ocean = still_ocean()
    eng = make_engine(Const, ocean, [(300, 300)])
    vx, vy = ocean.currents[Depth.DEEP].velocity
    eng.step()  # day 1: still at SURFACE when sensing, chooses DEEP
    j = eng.groups[0].alive[0]
    assert j.depth == Depth.DEEP
    assert (j.x, j.y) == pytest.approx((wrap(300 + vx), wrap(300 + vy)))


def test_eating_maturity_and_capacity():
    # Sit at the centre of the feeding zone with zero drift risk ignored:
    # we teleport the jellyfish back each day to isolate the eating rules.
    ocean = still_ocean(feeding=(300, 300), predator=(800, 100))
    eng = make_engine(Const, ocean, [(300, 300)], days=400)
    j = eng.groups[0].alive[0]
    for _ in range(181):  # through all of summer, into day 1 of fall
        j.x, j.y = 300, 300
        eng.step()
    # 90 summer days eaten: 30 to mature, 60 counted -> capacity 6 on day 181
    assert j.eat_days_total == 90
    assert j.capacity == 6
    assert j.summer_feed_days == 0


def test_reproduction_copies_memory_and_limits_one_per_day():
    class Writer(Player):
        def act(self, s):
            s.memory[0] = 42
            return Action(Depth.DEEP)

    ocean = still_ocean(breeding=(600, 600), predator=(350, 100))
    eng = make_engine(Writer, ocean, [(600, 600)], days=360)
    eng.t = 270  # first day of winter
    parent = eng.groups[0].alive[0]
    parent.birth_t = 270
    parent.capacity = 3
    for _ in range(5):
        parent.x, parent.y = 600, 600
        eng.step()
    babies = [j for j in eng.groups[0].alive if j is not parent]
    assert len(babies) == 3
    assert parent.capacity == 0
    assert all(b.memory[0] == 42 and b.generation == 1 for b in babies)


def test_old_age():
    ocean = still_ocean()
    eng = make_engine(Const, ocean, [(300, 300)], lifetime=10, days=20)
    for _ in range(11):
        eng.step()
    assert eng.groups[0].population == 0
    assert eng.groups[0].stats.deaths_age == 1


def test_memory_resize_crashes_group_only():
    class Bad(Player):
        def act(self, s):
            s.memory.append(1)
            return Action(Depth.DEEP)

    eng = make_engine(Bad, still_ocean(), [(300, 300)])
    eng.step()
    assert eng.groups[0].error is not None
    assert eng.groups[0].population == 0


def test_runs_are_deterministic():
    argv = ["--players", "r", "e", "--seed", "7", "-T", "720", "--json"]
    a = build_engine(parse_args(argv))
    b = build_engine(parse_args(argv))
    a.run()
    b.run()
    ra, rb = a.results(), b.results()
    for r in (ra, rb):
        for g in r["groups"].values():
            g.pop("time_used_s")
    assert ra == rb


def test_predator_covers_at_most_half_of_a_zone():
    from math import pi

    from core.geometry import circle_overlap_area
    from core.ocean import overlap_fraction

    # sanity: identical circles overlap fully, distant ones not at all
    assert circle_overlap_area(200, 200, 0) == pytest.approx(pi * 200**2)
    assert circle_overlap_area(200, 200, 400) == 0

    for seed in range(300):
        o = Ocean.generate(random.Random(seed))
        assert overlap_fraction(o.predator, o.feeding) <= 0.5
        assert overlap_fraction(o.predator, o.breeding) <= 0.5

    with pytest.raises(ValueError, match="predator zone covers"):
        Ocean.generate(random.Random(0), feeding=(100, 100), predator=(110, 100))


def test_initial_jellyfish_never_spawn_in_predator_zone():
    from core.runner import spawn_points

    # predator covers (just under) half of the breeding zone
    ocean = Ocean.generate(
        random.Random(1), breeding=(500, 500), feeding=(100, 100), predator=(665, 500)
    )
    pts = spawn_points(random.Random(2), ocean, 500)
    assert all(ocean.breeding.contains(x, y) for x, y in pts)
    assert not any(ocean.predator.contains(x, y) for x, y in pts)


def test_no_births_inside_predator_zone():
    class Stay(Player):
        def act(self, s):
            return Action(Depth.DEEP)

    # breeding at (500, 500); predator overlaps its east side
    ocean = Ocean.generate(
        random.Random(0), breeding=(500, 500), feeding=(100, 100), predator=(700, 500)
    )
    eng = make_engine(Stay, ocean, [(600, 500)], days=360)
    eng.groups[0].rng = random.Random(0)
    eng.t = 270  # first day of winter
    parent = eng.groups[0].alive[0]
    parent.birth_t = 270
    parent.capacity = 3
    assert ocean.breeding.contains(600, 500) and ocean.predator.contains(600, 500)

    # survive predation for the test: keep re-adding it if eaten
    for _ in range(3):
        parent.alive, parent.x, parent.y = True, 600, 500
        eng.groups[0].alive = [parent]
        eng.step()
    assert eng.groups[0].stats.births == 0
    assert parent.capacity == 3
