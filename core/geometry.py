"""Helpers for working on the toroidal ocean."""

from math import acos, hypot, pi, sqrt

import core.constants as c


def wrap(v: float) -> float:
    """Wrap a coordinate onto [0, OCEAN_SIZE)."""
    v %= c.OCEAN_SIZE
    # float modulo can return OCEAN_SIZE for tiny negative inputs
    return 0.0 if v >= c.OCEAN_SIZE else v


def torus_delta(a: float, b: float) -> float:
    """Shortest signed displacement from a to b along one torus axis."""
    d = (b - a) % c.OCEAN_SIZE
    if d > c.OCEAN_SIZE / 2:
        d -= c.OCEAN_SIZE
    return d


def torus_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return hypot(torus_delta(x1, x2), torus_delta(y1, y2))


def circle_overlap_area(r1: float, r2: float, d: float) -> float:
    """Area shared by two circles of radii r1, r2 whose centres are d apart."""
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return pi * min(r1, r2) ** 2
    a1 = r1 * r1 * acos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = r2 * r2 * acos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    k = 0.5 * sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))
    return a1 + a2 - k
