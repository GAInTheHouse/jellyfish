"""Colours, layout and fonts for the visualizer.

Design rule: colour is only ever used to tell *groups* apart. Everything
else (zones, depths, seasons) is distinguished by line style, pattern, size
or a text label, so the GUI stays readable for colour-blind viewers.
"""

import pygame

from core.depth import Depth
from core.zone import ZoneKind

# --- window / layout (logical pixels; window is scaled to fit the screen) ---
SCREEN_W, SCREEN_H = 1440, 900
OCEAN_X, OCEAN_Y = 24, 24
OCEAN_PX = 852
PANEL_X = OCEAN_X + OCEAN_PX + 28
PANEL_W = SCREEN_W - PANEL_X - 24

FPS = 60
TURNS_PER_SECOND = [1, 2, 5, 10, 20, 30, 60, 120, 240, 480, 1000]
DEFAULT_TPS_INDEX = 4

# --- colours ------------------------------------------------------------------
BG = (236, 239, 243)
PANEL_BG = (255, 255, 255)
PANEL_EDGE = (204, 210, 219)
LIGHT_FILL = (241, 243, 246)
TEXT = (22, 27, 36)
TEXT_DIM = (80, 89, 104)
TEXT_FAINT = (128, 136, 148)
INK = (30, 38, 52)  # dark strokes: outlines, arrows, markers

OCEAN = (62, 124, 186)
GRID_MAJOR = (98, 152, 206)  # every 100 km
GRID_MINOR = (78, 138, 196)  # finer cells when zoomed in
ZONE_LINE = (255, 255, 255)
PREDATOR_HATCH = (16, 24, 40)

GROUP_COLORS = [
    (255, 110, 199),  # hot pink
    (0, 229, 255),  # cyan
    (255, 214, 10),  # gold
    (118, 255, 122),  # mint
    (255, 150, 60),  # orange
    (180, 140, 255),  # lavender
    (255, 255, 255),  # white
    (64, 156, 255),  # azure
    (220, 255, 80),  # chartreuse
    (255, 120, 120),  # salmon
    (150, 255, 230),  # aqua
    (255, 190, 230),  # blush
]


def group_color(i: int) -> tuple[int, int, int]:
    return GROUP_COLORS[i % len(GROUP_COLORS)]


ZONE_LABELS = {
    ZoneKind.FEEDING: "FEEDING",
    ZoneKind.BREEDING: "BREEDING",
    ZoneKind.PREDATOR: "PREDATORS",
}
ZONE_STYLE_HINT = {
    ZoneKind.FEEDING: "solid outline",
    ZoneKind.BREEDING: "dashed outline",
    ZoneKind.PREDATOR: "hatched",
}

# jellyfish get smaller the deeper they are (size, not colour, shows depth)
DEPTH_SCALE = {
    Depth.SURFACE: 1.0,
    Depth.SHALLOW: 0.82,
    Depth.MEDIUM: 0.66,
    Depth.DEEP: 0.52,
}
# compass arrow thickness per depth
DEPTH_WIDTH = {Depth.SURFACE: 5, Depth.SHALLOW: 4, Depth.MEDIUM: 3, Depth.DEEP: 2}
DEPTH_SHORT = {
    Depth.SURFACE: "Su",
    Depth.SHALLOW: "Sh",
    Depth.MEDIUM: "Me",
    Depth.DEEP: "De",
}


class Fonts:
    """Fonts rendered at the real on-screen pixel size, so text stays crisp."""

    def __init__(self, scale: float = 1.0) -> None:
        sans = "segoeui,helveticaneue,arial"
        mono = "consolas,menlo,dejavusansmono,couriernew"

        def sz(px: int) -> int:
            return max(8, round(px * scale))

        self.title = pygame.font.SysFont(sans, sz(30), bold=True)
        self.h2 = pygame.font.SysFont(sans, sz(19), bold=True)
        self.body = pygame.font.SysFont(sans, sz(16))
        self.body_bold = pygame.font.SysFont(sans, sz(16), bold=True)
        self.small = pygame.font.SysFont(sans, sz(14))
        self.mono = pygame.font.SysFont(mono, sz(15))
        self.mono_small = pygame.font.SysFont(mono, sz(14))
        self.big = pygame.font.SysFont(sans, sz(24), bold=True)
