from __future__ import annotations

import random
from collections import Counter
from math import cos, pi, sin, sqrt

import core.constants as c
from core.args import PLAYERS, Args, player_display_name
from core.engine import Engine, Group, SimConfig
from core.geometry import wrap
from core.ocean import Ocean
from core.stats import GroupStats


def spawn_points(rng: random.Random, ocean: Ocean, n: int) -> list[tuple[float, float]]:
    """n random points in the breeding zone, never inside the predator zone."""
    b = ocean.breeding
    pts: list[tuple[float, float]] = []
    while len(pts) < n:
        r = b.radius * sqrt(rng.random())
        a = rng.uniform(0, 2 * pi)
        x, y = wrap(b.x + r * cos(a)), wrap(b.y + r * sin(a))
        if not ocean.predator.contains(x, y):
            pts.append((x, y))
    return pts


def build_engine(args: Args) -> Engine:
    rng = random.Random(args.seed)
    m = args.map
    ocean = Ocean.generate(
        rng,
        feeding=m.feeding if m else None,
        breeding=m.breeding if m else None,
        predator=m.predator if m else None,
        headings=m.headings if m else None,
    )
    start = spawn_points(rng, ocean, args.initial_jellyfish)

    config = SimConfig(
        memory_size=args.memory,
        lifetime_days=max(1, round(args.lifetime_years * c.DAYS_PER_YEAR)),
        initial_jellyfish=args.initial_jellyfish,
        days=args.days,
        max_population=args.max_population,
    )

    totals = Counter(args.players)
    seen: Counter[str] = Counter()
    groups = []
    for i, key in enumerate(args.players):
        seen[key] += 1
        name = player_display_name(key)
        if totals[key] > 1:
            name += f" #{seen[key]}"
        player = PLAYERS[key](
            config.memory_size,
            config.lifetime_days,
            random.Random(f"{args.seed}:player:{i}"),
        )
        groups.append(
            Group(
                index=i,
                key=key,
                name=name,
                player=player,
                rng=random.Random(f"{args.seed}:world:{i}"),
                stats=GroupStats(initial=args.initial_jellyfish),
            )
        )

    return Engine(ocean, groups, config, start)


class JellyRunner:
    def __init__(self, args: Args):
        self.args = args
        self.engine = build_engine(args)

    def run(self) -> dict:
        self.engine.run()
        return self.engine.results()

    def run_gui(self) -> dict:
        # imported lazily so headless runs don't need a display / pygame init
        from core.ui.ocean_ui import OceanUI

        OceanUI(self.engine, self.args).run()
        return self.engine.results()
