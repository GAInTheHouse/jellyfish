"""Procedurally drawn sprites (no image assets needed).

Every function takes sizes in real screen pixels, so sprites are always drawn
at native resolution (crisp on high-DPI screens).
"""

from math import cos, pi, sin

import pygame

from core.depth import Depth
from core.ui import theme as t


def _jelly(color: tuple[int, int, int], scale: float):
    """Simple jellyfish: coloured bell with a dark outline, three tentacles."""
    w, h = int(24 * scale) + 4, int(26 * scale) + 4
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    cx = w / 2
    r = 9 * scale
    cy = r + 2

    lw = max(1, round(1.6 * scale))
    for off in (-0.55, 0.0, 0.55):
        x = cx + off * r
        pygame.draw.line(s, t.INK, (x, cy), (x, cy + 11 * scale), lw)

    bell = [
        (cx + r * cos(a), cy + r * sin(a))
        for a in (pi + pi * i / 16 for i in range(17))
    ]
    pygame.draw.polygon(s, color, bell)
    pygame.draw.polygon(s, t.INK, bell, max(1, round(1.4 * scale)))
    return s, (cx, cy)


class SpriteBank:
    """Caches sprites per (group colour, depth) at a given screen scale."""

    def __init__(self, scale: float) -> None:
        self.scale = scale
        self._jelly: dict[tuple[int, Depth], tuple[pygame.Surface, tuple]] = {}
        self._dot: dict[tuple[int, Depth], pygame.Surface] = {}

    def jelly(self, group: int, depth: Depth):
        key = (group, depth)
        if key not in self._jelly:
            self._jelly[key] = _jelly(
                t.group_color(group), t.DEPTH_SCALE[depth] * self.scale
            )
        return self._jelly[key]

    def dot(self, group: int, depth: Depth) -> pygame.Surface:
        """Cheap sprite used when thousands of jellyfish are on screen."""
        key = (group, depth)
        if key not in self._dot:
            r = (2 + 2 * t.DEPTH_SCALE[depth]) * self.scale
            n = int(2 * r + 2)
            s = pygame.Surface((n, n), pygame.SRCALPHA)
            pygame.draw.circle(s, t.INK, (n / 2, n / 2), r)
            pygame.draw.circle(s, t.group_color(group), (n / 2, n / 2), r - self.scale)
            self._dot[key] = s
        return self._dot[key]


def dashed_circle(s, color, c, R, width, dashes=36):
    """Each dash is a filled curved band (smoother than pygame.draw.arc)."""
    r_out, r_in = R, R - width
    for i in range(dashes):
        a0 = 2 * pi * i / dashes
        angles = [a0 + (pi / dashes) * k / 6 for k in range(7)]
        outer = [(c[0] + r_out * cos(a), c[1] + r_out * sin(a)) for a in angles]
        inner = [(c[0] + r_in * cos(a), c[1] + r_in * sin(a)) for a in reversed(angles)]
        pygame.draw.polygon(s, color, outer + inner)


def hatch_surface(size: tuple[int, int], scale: float) -> pygame.Surface:
    """Diagonal hatching covering `size`; masked to circles for predator zones."""
    w, h = size
    s = pygame.Surface(size, pygame.SRCALPHA)
    gap = max(4, int(14 * scale))
    lw = max(1, round(3 * scale))
    for k in range(-h, w + h, gap):
        pygame.draw.line(s, (*t.PREDATOR_HATCH, 110), (k, h), (k + h, 0), lw)
    return s


def plus_surface(scale: float) -> pygame.Surface:
    """A white '+' with a dark outline, used by the birth animation."""
    n = int(20 * scale) + 4
    s = pygame.Surface((n, n), pygame.SRCALPHA)
    arm, thick = 7.5 * scale, 3 * scale
    c = n / 2
    edge = 0.9 * scale
    for w, a, col in (
        (thick + 2 * edge, arm + edge, t.INK),
        (thick, arm, (255, 255, 255)),
    ):
        pygame.draw.rect(s, col, pygame.Rect(c - a, c - w / 2, 2 * a, w))
        pygame.draw.rect(s, col, pygame.Rect(c - w / 2, c - a, w, 2 * a))
    return s
