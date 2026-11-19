from __future__ import annotations

import random
from dataclasses import dataclass
from math import pi

import core.constants as c
from core.current import Current
from core.depth import Depth
from core.geometry import circle_overlap_area, torus_distance
from core.zone import Zone, ZoneKind


def overlap_fraction(predator: Zone, other: Zone) -> float:
    """Share of `other`'s area that the predator zone covers (0..1)."""
    d = torus_distance(predator.x, predator.y, other.x, other.y)
    shared = circle_overlap_area(predator.radius, other.radius, d)
    return shared / (pi * other.radius**2)


@dataclass(frozen=True)
class Ocean:
    feeding: Zone
    breeding: Zone
    predator: Zone
    currents: dict[Depth, Current]

    @property
    def zones(self) -> list[Zone]:
        return [self.feeding, self.breeding, self.predator]

    def current_at(self, depth: Depth) -> Current:
        return self.currents[depth]

    def validate(self) -> None:
        d = torus_distance(
            self.feeding.x, self.feeding.y, self.breeding.x, self.breeding.y
        )
        if d <= self.feeding.radius + self.breeding.radius:
            raise ValueError(
                f"feeding and breeding zones must be disjoint (centres {d:.0f}km apart)"
            )
        for z in (self.feeding, self.breeding):
            share = overlap_fraction(self.predator, z)
            if share > c.MAX_PREDATOR_OVERLAP:
                raise ValueError(
                    f"predator zone covers {share:.0%} of the {z.kind.value} zone "
                    f"(max {c.MAX_PREDATOR_OVERLAP:.0%})"
                )
        for z in self.zones:
            if not (0 <= z.x < c.OCEAN_SIZE and 0 <= z.y < c.OCEAN_SIZE):
                raise ValueError(f"{z.kind.value} zone centre outside the ocean")
        if set(self.currents) != set(Depth):
            raise ValueError("need exactly one current per depth")

    @staticmethod
    def generate(
        rng: random.Random,
        feeding: tuple[float, float] | None = None,
        breeding: tuple[float, float] | None = None,
        predator: tuple[float, float] | None = None,
        headings: dict[Depth, float] | None = None,
    ) -> Ocean:
        """Build an ocean, randomising anything not supplied.

        Rules: feeding and breeding never overlap; the predator zone may
        overlap either, but cover at most MAX_PREDATOR_OVERLAP of it.
        """

        def rand_point() -> tuple[float, float]:
            return rng.uniform(0, c.OCEAN_SIZE), rng.uniform(0, c.OCEAN_SIZE)

        hs = {d: rng.uniform(0, 360) for d in Depth}
        if headings:
            hs.update(headings)

        f = feeding or rand_point()
        b = breeding
        while b is None or torus_distance(*f, *b) <= 2 * c.ZONE_RADIUS:
            if breeding is not None:
                break  # fixed by a map; validate() reports the problem
            b = rand_point()

        fz = Zone(ZoneKind.FEEDING, *f)
        bz = Zone(ZoneKind.BREEDING, *b)

        def predator_ok(p: tuple[float, float]) -> bool:
            pz = Zone(ZoneKind.PREDATOR, *p)
            return all(
                overlap_fraction(pz, z) <= c.MAX_PREDATOR_OVERLAP for z in (fz, bz)
            )

        p = predator
        if p is None:
            p = rand_point()
            while not predator_ok(p):
                p = rand_point()

        ocean = Ocean(
            feeding=fz,
            breeding=bz,
            predator=Zone(ZoneKind.PREDATOR, *p),
            currents={d: Current(d, hs[d]) for d in Depth},
        )
        ocean.validate()
        return ocean
