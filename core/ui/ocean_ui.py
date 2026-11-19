"""Pygame visualizer for the jellyfish simulator.

Controls
  SPACE      play / pause            RIGHT     advance one day
  UP / DOWN  faster / slower         L         cycle depth layer filter
  T          toggle trails           G         linear / log chart
  1-9, 0     show / hide group 1-10  click     inspect a jellyfish
  H          help                    ESC       deselect / quit

Rendering note: the layout is designed on a 1440 x 900 "logical" canvas, but
everything (text included) is drawn directly at the window's real pixel size
via `Canvas`, and the process is made DPI-aware on Windows. That keeps fonts
crisp instead of being stretched by pygame or by Windows display scaling.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from math import cos, log10, pi, sin
from time import perf_counter

import pygame

import core.constants as c
from core.args import Args
from core.depth import Depth
from core.engine import Engine
from core.geometry import torus_delta, wrap
from core.jellyfish import Jellyfish
from core.seasons import Season, day_of_year, season_of, year_of
from core.ui import theme as t
from core.ui.sprites import SpriteBank, dashed_circle, hatch_surface, plus_surface
from core.zone import ZoneKind

LOD_THRESHOLD = 3500  # above this many visible jellyfish, draw dots
STEP_BUDGET_S = 0.030  # max simulation time per frame
DEATH_SECONDS = 1.4  # length of the "eaten by a predator" animation
BIRTH_SECONDS = 1.2  # length of the "new baby" animation
MAX_ANIMS = 200  # per animation kind, so fast playback stays smooth
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25  # per mouse-wheel notch
TOOLTIP_ROWS = 12  # jellyfish listed individually in the cell tooltip
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass_name(heading: float) -> str:
    return COMPASS[round(heading / 45) % 8]


def enable_dpi_awareness() -> None:
    """Stop Windows from bitmap-stretching (blurring) the window."""
    if sys.platform != "win32":
        return
    os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def initial_scale() -> float:
    """Largest logical->pixel scale whose window fits on the desktop."""
    forced = os.environ.get("JELLY_UI_SCALE")
    if forced:
        return float(forced)
    sizes = pygame.display.get_desktop_sizes()
    w, h = sizes[0] if sizes else (t.SCREEN_W, t.SCREEN_H)
    # leave room for the title bar and taskbar
    return max(0.5, min((w - 60) / t.SCREEN_W, (h - 120) / t.SCREEN_H))


class Canvas:
    """Draws using logical (1440x900) coordinates at native resolution."""

    def __init__(self, screen: pygame.Surface, s: float, ox: float, oy: float):
        self.screen, self.s, self.ox, self.oy = screen, s, ox, oy

    def P(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.s, self.oy + y * self.s

    def W(self, w: float) -> int:
        return max(1, round(w * self.s))

    def R(self, r) -> pygame.Rect:
        x, y, w, h = r
        X, Y = self.P(x, y)
        return pygame.Rect(round(X), round(Y), round(w * self.s), round(h * self.s))

    def rect(self, color, r, width: float = 0, radius: float = 0) -> None:
        pygame.draw.rect(
            self.screen,
            color,
            self.R(r),
            self.W(width) if width else 0,
            border_radius=round(radius * self.s),
        )

    def line(self, color, a, b, width: float = 1) -> None:
        pygame.draw.line(self.screen, color, self.P(*a), self.P(*b), self.W(width))

    def lines(self, color, pts, width: float = 1) -> None:
        pygame.draw.lines(
            self.screen, color, False, [self.P(*p) for p in pts], self.W(width)
        )

    def circle(self, color, ctr, r: float, width: float = 0) -> None:
        pygame.draw.circle(
            self.screen, color, self.P(*ctr), r * self.s, self.W(width) if width else 0
        )

    def polygon(self, color, pts, width: float = 0) -> None:
        pygame.draw.polygon(
            self.screen, color, [self.P(*p) for p in pts], self.W(width) if width else 0
        )

    def text(self, font, s: str, color=t.TEXT, **anchor) -> pygame.Rect:
        """Blit text anchored at a logical point; returns its LOGICAL rect."""
        surf = font.render(s, True, color)
        ((key, pt),) = anchor.items()
        X, Y = self.P(*pt)
        rect = surf.get_rect(**{key: (round(X), round(Y))})
        self.screen.blit(surf, rect)
        return pygame.Rect(
            (rect.x - self.ox) / self.s,
            (rect.y - self.oy) / self.s,
            rect.w / self.s,
            rect.h / self.s,
        )


@dataclass
class Anim:
    """A running birth or death animation."""

    group: int
    depth: Depth
    x: float
    y: float
    born: float
    spin: int


class OceanUI:
    def __init__(self, engine: Engine, args: Args) -> None:
        enable_dpi_awareness()
        pygame.init()
        pygame.display.set_caption("Jellyfish - COMS 4444 Project 4")
        s = initial_scale()
        self.screen = pygame.display.set_mode(
            (round(t.SCREEN_W * s), round(t.SCREEN_H * s)), pygame.RESIZABLE
        )
        self.clock = pygame.time.Clock()
        self.engine = engine
        self.args = args

        self.running = True
        self.paused = True
        self.tps_index = t.DEFAULT_TPS_INDEX
        self.acc = 0.0  # fractional progress towards the next day
        self.layer: Depth | None = None  # None = all depths
        self.show_trails = False
        self.log_chart = False
        self.show_help = False
        self.hidden: set[int] = set()
        self.selected: Jellyfish | None = None
        self.dying: list[Anim] = []
        self.births: list[Anim] = []

        # camera: zoom factor and the km coordinate at the view's top-left
        self.zoom = 1.0
        self.view_x = self.view_y = 0.0
        self.drag_from: tuple[int, int] | None = None
        self.drag_view = (0.0, 0.0)
        self.dragged = False

        self.layout(*self.screen.get_size())

    def layout(self, win_w: int, win_h: int) -> None:
        """(Re)build everything that depends on the window's pixel size."""
        s = min(win_w / t.SCREEN_W, win_h / t.SCREEN_H)
        ox = (win_w - t.SCREEN_W * s) / 2
        oy = (win_h - t.SCREEN_H * s) / 2
        self.cv = Canvas(self.screen, s, ox, oy)
        self.fonts = t.Fonts(s)
        self.ocean = self.cv.R((t.OCEAN_X, t.OCEAN_Y, t.OCEAN_PX, t.OCEAN_PX))
        self.ks = self.ocean.w / c.OCEAN_SIZE  # screen pixels per km at zoom 1
        self.banks: dict[float, SpriteBank] = {}
        self.zone_layer: pygame.Surface | None = None
        self.zone_key: tuple | None = None
        self.hatch = hatch_surface(self.ocean.size, s)
        self.trails = pygame.Surface(self.ocean.size, pygame.SRCALPHA)
        self.plus_sprite = plus_surface(s)

    # ---------------------------------------------------------------- camera
    @property
    def span(self) -> float:
        """Kilometres visible across the ocean view."""
        return c.OCEAN_SIZE / self.zoom

    @property
    def kz(self) -> float:
        """Screen pixels per km at the current zoom."""
        return self.ks * self.zoom

    @property
    def sprites(self) -> SpriteBank:
        """Jellyfish grow a little when zoomed in (sqrt, capped)."""
        g = round(min(self.zoom, 4) ** 0.5, 2)
        if g not in self.banks:
            self.banks[g] = SpriteBank(self.cv.s * g)
        return self.banks[g]

    @property
    def cell_km(self) -> int:
        """Size of a grid cell (hover unit); finer when zoomed in."""
        return 100 if self.zoom < 2 else 50 if self.zoom < 4 else 25

    def _rel(self, v: float, origin: float) -> float:
        """Torus offset of v from the view's left/top edge, in km. Things just
        outside the view on either side get small negative / large values."""
        d = (v - origin) % c.OCEAN_SIZE
        cut = self.span + (c.OCEAN_SIZE - self.span) / 2
        return d - c.OCEAN_SIZE if d > cut else d

    def kxy(self, x: float, y: float) -> tuple[float, float]:
        """Ocean km -> screen pixels (respects zoom, pan and wrap-around)."""
        return (
            self.ocean.x + self._rel(x, self.view_x) * self.kz,
            self.ocean.y + self._rel(y, self.view_y) * self.kz,
        )

    def screen_to_km(self, px: float, py: float) -> tuple[float, float]:
        return (
            wrap(self.view_x + (px - self.ocean.x) / self.kz),
            wrap(self.view_y + (py - self.ocean.y) / self.kz),
        )

    def set_zoom(self, z: float, anchor: tuple[float, float] | None = None) -> None:
        """Zoom keeping the km point under `anchor` (screen px) fixed."""
        z = min(MAX_ZOOM, max(1.0, z))
        if anchor is None:
            anchor = self.ocean.center
        wx, wy = self.screen_to_km(*anchor)
        self.zoom = z
        if z == 1.0:
            self.view_x = self.view_y = 0.0
            return
        self.view_x = wrap(wx - (anchor[0] - self.ocean.x) / self.kz)
        self.view_y = wrap(wy - (anchor[1] - self.ocean.y) / self.kz)

    # ================================================================ loop
    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(t.FPS) / 1000
            self.handle_events()
            self.advance(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()

    @property
    def tps(self) -> int:
        return t.TURNS_PER_SECOND[self.tps_index]

    def advance(self, dt: float) -> None:
        if self.paused or self.engine.finished:
            self.acc = 1.0
            return
        if self.acc >= 1.0:
            self.acc = 0.0
        self.acc += dt * self.tps
        steps = int(self.acc)
        self.acc -= steps
        t0 = perf_counter()
        for _ in range(steps):
            self.step_once()
            if perf_counter() - t0 > STEP_BUDGET_S or self.engine.finished:
                self.acc = 1.0 if self.engine.finished else 0.0
                break
        if self.tps > 30:
            self.acc = 1.0  # too fast to interpolate meaningfully

    def step_once(self) -> None:
        self.engine.step()
        now = perf_counter()
        busy = sum(len(g.alive) for g in self.engine.groups) > 600
        for e in self.engine.events:
            if e.kind not in ("predator", "birth") or e.group in self.hidden:
                continue
            if self.layer is not None and e.depth != self.layer:
                continue
            if e.kind == "predator":
                spin = 1 if (int(e.x) + int(e.y)) % 2 else -1
                self.dying.append(Anim(e.group, e.depth, e.x, e.y, now, spin))
            elif not busy or (int(e.x * 7 + e.y) % 4 == 0):  # thin out when busy
                self.births.append(Anim(e.group, e.depth, e.x, e.y, now, 1))
        self.dying = self.dying[-MAX_ANIMS:]
        self.births = self.births[-MAX_ANIMS:]

        if self.show_trails:
            for g in self.engine.groups:
                if g.index in self.hidden:
                    continue
                col = (*t.group_color(g.index), 150)
                n = max(2, round(2 * self.cv.s))
                for j in g.alive:
                    if self.layer is None or j.depth == self.layer:
                        self.trails.fill(
                            col, (int(j.x * self.ks), int(j.y * self.ks), n, n)
                        )
        if self.engine.finished:
            self.paused = True

    # ============================================================== events
    def handle_events(self) -> None:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.VIDEORESIZE:
                self.layout(*self.screen.get_size())
            elif ev.type == pygame.KEYDOWN:
                self.on_key(ev.key)
            elif ev.type == pygame.MOUSEWHEEL:
                pos = pygame.mouse.get_pos()
                if self.ocean.collidepoint(pos):
                    self.set_zoom(self.zoom * ZOOM_STEP**ev.y, pos)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.ocean.collidepoint(ev.pos):
                    self.drag_from = ev.pos
                    self.drag_view = (self.view_x, self.view_y)
                    self.dragged = False
            elif ev.type == pygame.MOUSEMOTION and self.drag_from is not None:
                dx = ev.pos[0] - self.drag_from[0]
                dy = ev.pos[1] - self.drag_from[1]
                if abs(dx) + abs(dy) > 4 * self.cv.s:
                    self.dragged = True
                if self.dragged and self.zoom > 1:
                    self.view_x = wrap(self.drag_view[0] - dx / self.kz)
                    self.view_y = wrap(self.drag_view[1] - dy / self.kz)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self.drag_from is not None and not self.dragged:
                    self.on_click(ev.pos)
                self.drag_from = None

    def on_key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.selected or self.show_help:
                self.selected, self.show_help = None, False
            else:
                self.running = False
        elif key == pygame.K_SPACE:
            if not self.engine.finished:
                self.paused = not self.paused
        elif key == pygame.K_RIGHT:
            self.paused = True
            if not self.engine.finished:
                self.step_once()
                self.acc = 1.0
        elif key == pygame.K_UP:
            self.tps_index = min(len(t.TURNS_PER_SECOND) - 1, self.tps_index + 1)
        elif key == pygame.K_DOWN:
            self.tps_index = max(0, self.tps_index - 1)
        elif key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.set_zoom(self.zoom * ZOOM_STEP)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.set_zoom(self.zoom / ZOOM_STEP)
        elif key == pygame.K_z:
            self.set_zoom(1.0)
        elif key == pygame.K_l:
            order = [None, *Depth]
            self.layer = order[(order.index(self.layer) + 1) % len(order)]
        elif key == pygame.K_t:
            self.show_trails = not self.show_trails
            self.trails.fill((0, 0, 0, 0))
        elif key == pygame.K_g:
            self.log_chart = not self.log_chart
        elif key == pygame.K_h:
            self.show_help = not self.show_help
        elif pygame.K_0 <= key <= pygame.K_9:
            idx = 9 if key == pygame.K_0 else key - pygame.K_1
            if idx < len(self.engine.groups):
                self.hidden ^= {idx}

    def visible_jellies(self):
        for g in self.engine.groups:
            if g.index in self.hidden:
                continue
            for j in g.alive:
                if self.layer is None or j.depth == self.layer:
                    yield j

    def on_click(self, pos: tuple[int, int]) -> None:
        best, best_d = None, (14.0 * self.cv.s) ** 2
        for j in self.visible_jellies():
            px, py = self.kxy(*self.interp(j))
            d = (px - pos[0]) ** 2 + (py - pos[1]) ** 2
            if d < best_d:
                best, best_d = j, d
        self.selected = best

    # ============================================================= drawing
    def interp(self, j: Jellyfish) -> tuple[float, float]:
        f = min(1.0, self.acc)
        if f >= 1.0:
            return j.x, j.y
        return (
            wrap(j.prev_x + torus_delta(j.prev_x, j.x) * f),
            wrap(j.prev_y + torus_delta(j.prev_y, j.y) * f),
        )

    def card(self, rect) -> None:
        self.cv.rect(t.PANEL_BG, rect, radius=10)
        self.cv.rect(t.PANEL_EDGE, rect, 1, radius=10)

    def chip(self, font, label: str, center: tuple[float, float], clamp=None):
        """White label box drawn in screen pixels."""
        surf = font.render(label, True, t.TEXT)
        s = self.cv.s
        box = surf.get_rect(center=(round(center[0]), round(center[1])))
        box = box.inflate(round(16 * s), round(8 * s))
        if clamp is not None:
            box.clamp_ip(clamp)
        pygame.draw.rect(self.screen, t.PANEL_BG, box, border_radius=round(6 * s))
        pygame.draw.rect(
            self.screen, t.INK, box, max(1, round(s)), border_radius=round(6 * s)
        )
        self.screen.blit(surf, surf.get_rect(center=box.center))
        return box

    def draw(self) -> None:
        self.screen.fill(t.BG)
        self.screen.set_clip(self.ocean)
        self.draw_ocean()
        self.screen.set_clip(None)
        pygame.draw.rect(self.screen, t.INK, self.ocean, max(1, round(self.cv.s)))
        self.draw_axis_labels()
        self.draw_panel()
        if self.selected:
            self.draw_inspector()
        self.draw_cell_tooltip()
        if self.show_help:
            self.draw_help()
        if self.engine.finished:
            self.draw_banner()

    # ---------------------------------------------------------------- ocean
    def draw_ocean(self) -> None:
        self.screen.fill(t.OCEAN, self.ocean)
        self.draw_grid()
        self.draw_zones(self.engine.season)
        if self.show_trails and self.zoom == 1.0:
            self.trails.fill((0, 0, 0, 2), special_flags=pygame.BLEND_RGBA_SUB)
            self.screen.blit(self.trails, self.ocean)
        self.draw_hover_cell()
        self.draw_jellies()
        self.draw_births()
        self.draw_deaths()
        self.draw_zone_labels(self.engine.season)
        self.draw_ocean_hud()

    def draw_grid(self) -> None:
        """Grid lines every `cell_km`; these squares are the hover cells."""
        step, o, kz = self.cell_km, self.ocean, self.kz
        for origin, horizontal in ((self.view_x, False), (self.view_y, True)):
            v = (origin // step) * step
            while v <= origin + self.span:
                p = (o.y if horizontal else o.x) + (v - origin) * kz
                col = t.GRID_MAJOR if round(v) % 100 == 0 else t.GRID_MINOR
                if horizontal:
                    pygame.draw.line(self.screen, col, (o.left, p), (o.right, p))
                else:
                    pygame.draw.line(self.screen, col, (p, o.top), (p, o.bottom))
                v += step

    def zone_copies(self, x: float, y: float):
        """Screen centres of every torus copy of a zone that may be visible."""
        r = (c.ZONE_RADIUS + 10) * self.kz
        cx, cy = self.kxy(x, y)
        full = c.OCEAN_SIZE * self.kz
        o = self.ocean
        for ox in (-full, 0, full):
            for oy in (-full, 0, full):
                px, py = cx + ox, cy + oy
                if (
                    px + r >= o.left
                    and px - r <= o.right
                    and py + r >= o.top
                    and py - r <= o.bottom
                ):
                    yield px - o.x, py - o.y  # relative to the ocean view

    @staticmethod
    def zone_open(kind: ZoneKind, season: Season) -> bool:
        return (kind == ZoneKind.FEEDING and season == Season.SUMMER) or (
            kind == ZoneKind.BREEDING and season == Season.WINTER
        )

    def draw_zones(self, season: Season) -> None:
        """Zones are drawn onto one cached layer, rebuilt only when the view
        or the open/closed state changes (cheap enough while dragging)."""
        opens = tuple(self.zone_open(z.kind, season) for z in self.engine.ocean.zones)
        key = (round(self.view_x, 3), round(self.view_y, 3), self.zoom, opens)
        if key != self.zone_key or self.zone_layer is None:
            self.zone_layer = self.build_zone_layer(season)
            self.zone_key = key
        self.screen.blit(self.zone_layer, self.ocean)

    def build_zone_layer(self, season: Season) -> pygame.Surface:
        s = self.cv.s
        layer = pygame.Surface(self.ocean.size, pygame.SRCALPHA)
        for z in self.engine.ocean.zones:
            R = z.radius * self.kz
            active = self.zone_open(z.kind, season)
            width = round((5 if active else 2) * s)
            for cx, cy in self.zone_copies(z.x, z.y):
                if z.kind == ZoneKind.PREDATOR:
                    mask = pygame.Surface(self.ocean.size, pygame.SRCALPHA)
                    pygame.draw.circle(mask, (255, 255, 255, 255), (cx, cy), R)
                    hatch = self.hatch.copy()
                    hatch.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                    layer.blit(hatch, (0, 0))
                    pygame.draw.circle(
                        layer, (*t.PREDATOR_HATCH, 230), (cx, cy), R, round(3 * s)
                    )
                    continue
                fill = pygame.Surface(self.ocean.size, pygame.SRCALPHA)
                pygame.draw.circle(
                    fill, (255, 255, 255, 45 if active else 25), (cx, cy), R
                )
                layer.blit(fill, (0, 0))
                if z.kind == ZoneKind.FEEDING:
                    pygame.draw.circle(layer, t.ZONE_LINE, (cx, cy), R, width)
                else:
                    dashed_circle(layer, t.ZONE_LINE, (cx, cy), R, width)
        return layer

    def draw_zone_labels(self, season: Season) -> None:
        inner = self.ocean.inflate(-round(12 * self.cv.s), -round(12 * self.cv.s))
        for z in self.engine.ocean.zones:
            label = t.ZONE_LABELS[z.kind]
            if self.zone_open(z.kind, season):
                label += " (open)"
            # label the copy nearest the middle of the view
            copies = list(self.zone_copies(z.x, z.y))
            if not copies:
                continue
            mid = (self.ocean.w / 2, self.ocean.h / 2)
            cx, cy = min(
                copies, key=lambda p: (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2
            )
            centre = (cx + self.ocean.x, cy + self.ocean.y)
            self.chip(self.fonts.body_bold, label, centre, clamp=inner)

    def draw_jellies(self) -> None:
        visible = [
            g for g in self.engine.groups if g.index not in self.hidden and g.alive
        ]
        lod = sum(len(g.alive) for g in visible) > LOD_THRESHOLD and self.zoom < 2
        blit = self.screen.blit
        bank = self.sprites
        o = self.ocean
        pad = 40 * self.cv.s

        # deep first so surface jellyfish are drawn on top
        for depth in reversed(list(Depth)):
            if self.layer is not None and depth != self.layer:
                continue
            for g in visible:
                if lod:
                    surf = bank.dot(g.index, depth)
                    ax = ay = surf.get_width() / 2
                else:
                    surf, (ax, ay) = bank.jelly(g.index, depth)
                for j in g.alive:
                    if j.depth != depth:
                        continue
                    px, py = self.kxy(*self.interp(j))
                    if -pad < px - o.x < o.w + pad and -pad < py - o.y < o.h + pad:
                        blit(surf, (round(px - ax), round(py - ay)))

        if self.selected is not None and self.selected.alive:
            s = self.cv.s
            px, py = self.kxy(*self.interp(self.selected))
            pygame.draw.circle(self.screen, t.PANEL_BG, (px, py), 15 * s, round(3 * s))
            pygame.draw.circle(self.screen, t.INK, (px, py), 18 * s, max(1, round(s)))

    def draw_births(self) -> None:
        """New baby: it pops up from small to full size with a bounce, small
        sparks fly outward, and a '+' floats up and fades. Distinct in shape
        from the death animation, so it reads without colour."""
        now = perf_counter()
        s = self.cv.s
        keep = []
        for b in self.births:
            f = (now - b.born) / BIRTH_SECONDS
            if f >= 1:
                continue
            keep.append(b)
            px, py = self.kxy(b.x, b.y)

            # 1. sparks fly outward
            if f < 0.6:
                g = f / 0.6
                for k in range(6):
                    a = k * pi / 3 + 0.3
                    r = (6 + 16 * g) * s
                    sx, sy = px + cos(a) * r, py + sin(a) * r
                    size = max(1.0, (2.5 * (1 - g)) * s)
                    pygame.draw.circle(self.screen, t.PANEL_BG, (sx, sy), size + s)
                    pygame.draw.circle(
                        self.screen, t.INK, (sx, sy), size + s, max(1, round(s))
                    )

            # 2. baby pops up with an overshoot, then settles
            grow = min(1.0, f / 0.45)
            scale = 0.25 + 0.75 * grow + 0.25 * sin(pi * grow) * (1 - grow * 0.4)
            sprite, _ = self.sprites.jelly(b.group, b.depth)
            img = pygame.transform.rotozoom(sprite, 0, scale)
            if f > 0.7:
                img.set_alpha(int(255 * (1 - (f - 0.7) / 0.3)))
            bx, by = (
                px + 14 * s * grow,
                py - 14 * s * grow,
            )  # pops out beside the parent
            self.screen.blit(img, img.get_rect(center=(bx, by)))

            # 3. a '+' floats up and fades
            plus = self.plus_sprite.copy()
            plus.set_alpha(255 if f < 0.7 else int(255 * (1 - f) / 0.3))
            self.screen.blit(
                plus, plus.get_rect(center=(px + 28 * s, py - 30 * s - 18 * s * f))
            )
        self.births = keep

    def draw_deaths(self) -> None:
        """Eaten jellyfish: a bite ring, then the body tips over, shrinks,
        sinks and fades while bubbles rise. Shape-based, so it reads without
        relying on colour."""
        now = perf_counter()
        s = self.cv.s
        keep = []
        for d in self.dying:
            f = (now - d.born) / DEATH_SECONDS
            if f >= 1:
                continue
            keep.append(d)
            px, py = self.kxy(d.x, d.y)

            # 1. bite: a quick expanding double ring
            if f < 0.35:
                g = f / 0.35
                r = (8 + 20 * g) * s
                a = int(255 * (1 - g))
                ring = pygame.Surface((int(2 * r + 8), int(2 * r + 8)), pygame.SRCALPHA)
                rc = (ring.get_width() / 2, ring.get_height() / 2)
                pygame.draw.circle(
                    ring, (255, 255, 255, a), rc, r, max(2, round(4 * s))
                )
                pygame.draw.circle(ring, (*t.INK, a), rc, r + 2 * s, max(1, round(s)))
                self.screen.blit(ring, ring.get_rect(center=(px, py)))

            # 2. body tips over, shrinks, sinks and fades
            sprite, _ = self.sprites.jelly(d.group, d.depth)
            img = pygame.transform.rotozoom(sprite, d.spin * 170 * f, 1 - 0.5 * f)
            img.set_alpha(int(255 * (1 - f) ** 1.2))
            self.screen.blit(img, img.get_rect(center=(px, py + 18 * s * f)))

            # 3. bubbles rise
            for k in range(3):
                bf = f - 0.1 * k
                if not 0 < bf < 0.85:
                    continue
                bx = px + (k - 1) * 6 * s + sin(bf * 14 + k) * 2 * s
                by = py - 30 * s * bf
                br = (2 + 0.8 * k) * s
                pygame.draw.circle(self.screen, t.PANEL_BG, (bx, by), br)
                pygame.draw.circle(self.screen, t.INK, (bx, by), br, max(1, round(s)))
        self.dying = keep

    # ------------------------------------------------------------ hover cell
    def hovered_cell(self) -> tuple[int, int] | None:
        pos = pygame.mouse.get_pos()
        if self.drag_from is not None or not self.ocean.collidepoint(pos):
            return None
        if not pygame.mouse.get_focused():
            return None
        x, y = self.screen_to_km(*pos)
        return int(x // self.cell_km), int(y // self.cell_km)

    def jellies_in_cell(self, cell: tuple[int, int]) -> list[Jellyfish]:
        out = []
        for j in self.visible_jellies():
            x, y = self.interp(j)
            if int(x // self.cell_km) == cell[0] and int(y // self.cell_km) == cell[1]:
                out.append(j)
        return out

    def draw_hover_cell(self) -> None:
        cell = self.hovered_cell()
        if cell is None:
            return
        px, py = self.kxy(cell[0] * self.cell_km, cell[1] * self.cell_km)
        size = self.cell_km * self.kz
        rect = pygame.Rect(round(px), round(py), round(size), round(size))
        pygame.draw.rect(self.screen, t.PANEL_BG, rect, max(2, round(2 * self.cv.s)))

    def draw_cell_tooltip(self) -> None:
        cell = self.hovered_cell()
        if cell is None:
            return
        f, s, eng = self.fonts, self.cv.s, self.engine
        jellies = self.jellies_in_cell(cell)
        k = self.cell_km
        x0, y0 = cell[0] * k, cell[1] * k
        lines: list[tuple[str, tuple[int, int, int] | None]] = []
        head = f"Cell x {x0}-{x0 + k}, y {y0}-{y0 + k} km"
        sub = f"{len(jellies)} jellyfish" if jellies else "no jellyfish"
        counts: dict[int, int] = {}
        for j in jellies:
            counts[j.group] = counts.get(j.group, 0) + 1
        for gi, n in sorted(counts.items()):
            lines.append((f"{eng.groups[gi].name}: {n}", t.group_color(gi)))
        shown = sorted(jellies, key=lambda j: (j.group, j.id))[:TOOLTIP_ROWS]
        detail = [
            f"#{j.id:<6}{j.depth.label:<8}age {eng.t - j.birth_t:>4}d  "
            f"ate {j.eat_days_total:>3}  cap {j.capacity}"
            for j in shown
        ]
        if len(jellies) > TOOLTIP_ROWS:
            detail.append(f"... and {len(jellies) - TOOLTIP_ROWS} more")

        pad, lh = round(10 * s), f.mono_small.get_linesize()
        widths = [f.body_bold.size(head)[0], f.small.size(sub)[0]]
        widths += [f.small.size(text)[0] + round(22 * s) for text, _ in lines]
        widths += [f.mono_small.size(text)[0] + round(22 * s) for text in detail]
        w = max(widths) + 2 * pad
        h = (
            2 * pad
            + f.body_bold.get_linesize()
            + f.small.get_linesize()
            + len(lines) * f.small.get_linesize()
            + (round(6 * s) + len(detail) * lh if detail else 0)
        )
        mx, my = pygame.mouse.get_pos()
        box = pygame.Rect(mx + round(18 * s), my + round(18 * s), w, h)
        if box.right > self.ocean.right:  # keep it over the ocean, not the panel
            box.right = mx - round(18 * s)
        box.clamp_ip(self.screen.get_rect())
        pygame.draw.rect(self.screen, t.PANEL_BG, box, border_radius=round(8 * s))
        pygame.draw.rect(
            self.screen, t.INK, box, max(1, round(s)), border_radius=round(8 * s)
        )

        x, y = box.x + pad, box.y + pad
        self.screen.blit(f.body_bold.render(head, True, t.TEXT), (x, y))
        y += f.body_bold.get_linesize()
        self.screen.blit(f.small.render(sub, True, t.TEXT_DIM), (x, y))
        y += f.small.get_linesize()
        sw = round(12 * s)
        for text, col in lines:
            r = pygame.Rect(x, y + (f.small.get_linesize() - sw) // 2, sw, sw)
            pygame.draw.rect(self.screen, col, r, border_radius=round(2 * s))
            pygame.draw.rect(
                self.screen, t.INK, r, max(1, round(s)), border_radius=round(2 * s)
            )
            self.screen.blit(f.small.render(text, True, t.TEXT), (x + round(20 * s), y))
            y += f.small.get_linesize()
        if detail:
            y += round(6 * s)
            for j, text in zip(shown + [None], detail):
                if j is not None:
                    r = pygame.Rect(x, y + (lh - sw) // 2, sw, sw)
                    pygame.draw.rect(self.screen, t.group_color(j.group), r)
                    pygame.draw.rect(self.screen, t.INK, r, max(1, round(s)))
                self.screen.blit(
                    f.mono_small.render(text, True, t.TEXT if j else t.TEXT_DIM),
                    (x + round(20 * s), y),
                )
                y += lh

    def draw_ocean_hud(self) -> None:
        layer = "all depths" if self.layer is None else self.layer.label
        if self.show_trails and self.zoom > 1:
            trails = "Trails: zoom out to see  [T]"
        else:
            trails = f"Trails: {'on' if self.show_trails else 'off'}  [T]"
        zoom = (
            "Zoom 1x  (scroll to zoom)"
            if self.zoom == 1
            else f"Zoom {self.zoom:.1f}x  (drag to pan, Z to reset)"
        )
        chips = [f"Showing: {layer}  [L]", trails, zoom]
        s = self.cv.s
        x = self.ocean.x + 10 * s
        for label in chips:
            w = self.fonts.small.size(label)[0] + 16 * s
            box = self.chip(self.fonts.small, label, (x + w / 2, self.ocean.y + 22 * s))
            x = box.right + 6 * s

    def draw_axis_labels(self) -> None:
        f, s, o = self.fonts.small, self.cv.s, self.ocean
        tick = 200 if self.zoom < 2 else 100 if self.zoom < 4 else 50
        v = (self.view_x // tick) * tick
        while v <= self.view_x + self.span + 0.5:
            px = o.x + (v - self.view_x) * self.kz
            if o.left - 1 <= px <= o.right + 1:
                km = round(v) % 1000
                if km == 0 and v - self.view_x > self.span / 2:
                    km = 1000  # right-hand edge of the unzoomed ocean
                label = f.render(str(km), True, t.TEXT_DIM)
                self.screen.blit(
                    label, label.get_rect(midtop=(px, o.bottom + round(3 * s)))
                )
            v += tick
        self.cv.text(
            f,
            "1000 x 1000 km ocean, wraps around every edge",
            t.TEXT_DIM,
            topright=(t.OCEAN_X + t.OCEAN_PX, 4),
        )

    # ---------------------------------------------------------------- panel
    def draw_panel(self) -> None:
        cv, f = self.cv, self.fonts
        x0, w = t.PANEL_X, t.PANEL_W
        self.card((x0 - 12, 12, w + 24, t.SCREEN_H - 24))

        cv.text(f.title, "Jellyfish", topleft=(x0, 20))
        cfg = self.engine.config
        cv.text(
            f.small,
            f"seed {self.args.seed}   memory {cfg.memory_size} B   lifetime "
            f"{self.args.lifetime_years:g} y   start {cfg.initial_jellyfish} per group",
            t.TEXT_DIM,
            topleft=(x0 + 2, 60),
        )

        self.draw_calendar(x0, 92, w - 190)
        self.draw_currents(x0 + w - 170, 92)
        y = self.draw_groups(x0, 302)
        top = max(y + 16, 580)
        self.draw_chart(x0, top, w, t.SCREEN_H - 56 - top)
        cv.text(
            f.small,
            "SPACE play   → step   ↑↓ speed   scroll zoom   drag pan   L depth   H help",
            t.TEXT_DIM,
            topleft=(x0, t.SCREEN_H - 42),
        )

    def draw_calendar(self, x0: int, y0: int, w: int) -> None:
        cv, f, eng = self.cv, self.fonts, self.engine
        t_shown = max(0, eng.t - 1) if eng.finished else eng.t
        doy = day_of_year(t_shown)
        season = season_of(doy)
        cv.text(
            f.big,
            f"Day {doy}, Year {year_of(t_shown)}, {season.label}",
            topleft=(x0, y0),
        )

        # season bar: four labelled segments, current one filled dark
        bar_y, bar_h = y0 + 40, 26
        seg_w = w / 4
        for sn in Season:
            r = (x0 + sn.value * seg_w, bar_y, seg_w - 3, bar_h)
            cur = sn == season
            cv.rect(t.INK if cur else t.LIGHT_FILL, r, radius=4)
            cv.rect(t.PANEL_EDGE, r, 1, radius=4)
            cx = r[0] + r[2] / 2
            cv.text(
                f.small,
                sn.label,
                t.PANEL_BG if cur else t.TEXT_DIM,
                center=(cx, bar_y + bar_h / 2),
            )
        mx = x0 + w * (doy - 1) / c.DAYS_PER_YEAR
        b = bar_y + bar_h
        cv.polygon(t.INK, [(mx, b + 2), (mx - 6, b + 10), (mx + 6, b + 10)])

        hint = {
            Season.SPRING: "Nothing to eat or breed yet.",
            Season.SUMMER: "Feeding zone is open.",
            Season.FALL: "Capacity set from last summer.",
            Season.WINTER: "Breeding zone is open.",
        }[season]
        cv.text(f.small, hint, t.TEXT_DIM, topleft=(x0, b + 14))

        if eng.finished:
            status = "Finished"
        elif self.paused:
            status = f"Paused  ({self.tps} days/s, SPACE to play)"
        else:
            status = f"Playing at {self.tps} days/s"
        cv.text(f.body_bold, status, topleft=(x0, b + 36))

        bar = (x0, b + 62, w, 8)
        cv.rect(t.LIGHT_FILL, bar, radius=4)
        cv.rect(t.PANEL_EDGE, bar, 1, radius=4)
        frac = eng.t / eng.config.days
        if frac > 0:
            cv.rect(t.INK, (x0, b + 62, w * frac, 8), radius=4)
        cv.text(
            f.small,
            f"{eng.t} of {eng.config.days} days",
            t.TEXT_DIM,
            topleft=(x0, b + 74),
        )

    def draw_currents(self, x0: int, y0: int) -> None:
        cv, f = self.cv, self.fonts
        cv.text(f.body_bold, "Currents", topleft=(x0, y0))
        cx, cy, R = x0 + 75, y0 + 70, 38
        cv.circle(t.LIGHT_FILL, (cx, cy), R + 8)
        cv.circle(t.PANEL_EDGE, (cx, cy), R + 8, 1)
        for lab, (dx, dy) in {
            "N": (0, -1),
            "E": (1, 0),
            "S": (0, 1),
            "W": (-1, 0),
        }.items():
            cv.text(
                f.small,
                lab,
                t.TEXT_FAINT,
                center=(cx + dx * (R + 18), cy + dy * (R + 18)),
            )

        for d in Depth:
            if self.layer is not None and self.layer != d:
                continue
            cur = self.engine.ocean.currents[d]
            vx, vy = cur.velocity
            L = R * (0.35 + 0.65 * cur.speed / c.CURRENT_SPEEDS[0])
            ex, ey = cx + vx / cur.speed * L, cy + vy / cur.speed * L
            cv.line(t.INK, (cx, cy), (ex, ey), t.DEPTH_WIDTH[d])
            ang = (cur.heading - 90) * pi / 180
            for side in (-1, 1):
                hx = ex - 8 * cos(ang + side * 0.5)
                hy = ey - 8 * sin(ang + side * 0.5)
                cv.line(t.INK, (ex, ey), (hx, hy), 2)
        cv.circle(t.INK, (cx, cy), 3)

        y = cy + R + 26
        for d in Depth:
            cur = self.engine.ocean.currents[d]
            col = t.TEXT if self.layer in (None, d) else t.TEXT_FAINT
            cv.line(col, (x0 - 6, y + 8), (x0 + 10, y + 8), t.DEPTH_WIDTH[d])
            cv.text(
                f.mono_small,
                f"{d.label:<8}{cur.speed:>3.0f} {compass_name(cur.heading):<2}",
                col,
                topleft=(x0 + 16, y),
            )
            y += 18

    def draw_groups(self, x0: int, y0: int) -> int:
        cv, f = self.cv, self.fonts
        cv.text(f.h2, "Populations", topleft=(x0, y0))
        cols = [
            ("alive", 220),
            ("peak", 278),
            ("born", 336),
            ("eaten", 394),
            ("old age", 460),
            ("gen", 506),
        ]
        y = y0 + 30
        for name, cx in cols:
            cv.text(f.small, name, t.TEXT_DIM, topright=(x0 + cx, y))
        y += 20
        cv.line(t.PANEL_EDGE, (x0, y - 2), (x0 + t.PANEL_W, y - 2))
        for g in self.engine.groups:
            hidden = g.index in self.hidden
            tc = t.TEXT_FAINT if hidden else t.TEXT
            sw = (x0, y + 4, 16, 16)
            if not hidden:
                cv.rect(t.group_color(g.index), sw, radius=3)
            cv.rect(t.INK, sw, 1, radius=3)
            key = "0" if g.index == 9 else str(g.index + 1) if g.index < 9 else ""
            cv.text(f.body, g.name, tc, topleft=(x0 + 24, y + 1))
            if key:
                cv.text(f.small, f"[{key}]", t.TEXT_FAINT, topleft=(x0 + 130, y + 3))
            st = g.stats
            vals = [
                g.population,
                st.peak,
                st.births,
                st.deaths_predator,
                st.deaths_age,
                st.max_generation,
            ]
            for (_, cx), v in zip(cols, vals):
                cv.text(f.mono, str(v), tc, topright=(x0 + cx, y + 3))
            y += 24
            if g.error:
                cv.text(
                    f.small,
                    f"crashed: {g.error[:60]}",
                    t.TEXT,
                    topleft=(x0 + 24, y - 4),
                )
                y += 18
            elif g.population == 0 and st.extinct_day is not None:
                cv.text(
                    f.small,
                    f"extinct on day {st.extinct_day}",
                    t.TEXT_DIM,
                    topleft=(x0 + 24, y - 4),
                )
                y += 18
        return y

    def draw_chart(self, x0: int, y0: int, w: int, h: int) -> None:
        if h < 80:
            return
        cv, f, eng = self.cv, self.fonts, self.engine
        cv.text(f.h2, "Population over time", topleft=(x0, y0))
        cv.text(
            f.small,
            f"{'log' if self.log_chart else 'linear'} scale [G]   shaded = summer",
            t.TEXT_DIM,
            topright=(x0 + w, y0 + 4),
        )
        ax, ay, aw, ah = x0 + 40, y0 + 30, w - 64, h - 52
        bottom, right = ay + ah, ax + aw
        cv.rect(t.PANEL_BG, (ax, ay, aw, ah))

        days = eng.config.days
        years = days / c.DAYS_PER_YEAR
        if years <= 60:
            for yr in range(int(years) + 1):
                d0 = yr * c.DAYS_PER_YEAR + Season.SUMMER.value * c.DAYS_PER_SEASON
                if d0 >= days:
                    continue
                d1 = min(days, d0 + c.DAYS_PER_SEASON)
                rx0 = ax + aw * d0 / days
                rx1 = ax + aw * d1 / days
                cv.rect(t.LIGHT_FILL, (rx0, ay, max(1, rx1 - rx0), ah))

        vis = [g for g in eng.groups if g.index not in self.hidden]

        ymax = max([10] + [g.stats.peak for g in vis])

        def ypx(v: float) -> float:
            if self.log_chart:
                return bottom - ah * log10(1 + v) / log10(1 + ymax)
            return bottom - ah * v / ymax

        for frac in (0, 0.5, 1):
            v = (
                ymax * frac
                if not self.log_chart
                else (10 ** (log10(1 + ymax) * frac) - 1)
            )
            yy = ypx(v)
            cv.line(t.PANEL_EDGE, (ax, yy), (right, yy))
            cv.text(f.small, f"{v:.0f}", t.TEXT_DIM, midright=(ax - 6, yy))
        cv.rect(t.PANEL_EDGE, (ax, ay, aw, ah), 1)

        n_px = max(1, int(aw * cv.s))
        for g in vis:
            hist = g.stats.history
            n = len(hist)
            if n < 2:
                continue
            step = max(1, n // n_px)
            pts = [(ax + aw * i / days, ypx(hist[i])) for i in range(0, n, step)]
            pts.append((ax + aw * (n - 1) / days, ypx(hist[-1])))
            cv.lines(t.INK, pts, 4)  # outline so light colours show
            cv.lines(t.group_color(g.index), pts, 2)
            ex, ey = pts[-1]
            key = "0" if g.index == 9 else str(g.index + 1)
            cv.text(f.small, key, t.TEXT, midleft=(min(ex + 4, right + 4), ey))

        nx = ax + aw * eng.t / days
        cv.line(t.TEXT_FAINT, (nx, ay), (nx, bottom), 1)
        step_yr = max(1, int(years) // 10)
        for yr in range(0, int(years) + 1, step_yr):
            xx = ax + aw * yr * c.DAYS_PER_YEAR / days
            if xx < right - 10:
                cv.text(f.small, f"y{yr + 1}", t.TEXT_DIM, topleft=(xx + 2, bottom + 3))

    # ------------------------------------------------------------ overlays
    def draw_inspector(self) -> None:
        j = self.selected
        assert j is not None
        cv, f, eng = self.cv, self.fonts, self.engine
        g = eng.groups[j.group]
        rx, ry, rw = t.OCEAN_X + 12, t.OCEAN_Y + t.OCEAN_PX - 222, 440
        self.card((rx, ry, rw, 210))
        x, y = rx + 14, ry + 10
        cv.rect(t.group_color(j.group), (x, y + 4, 16, 16), radius=3)
        cv.rect(t.INK, (x, y + 4, 16, 16), 1, radius=3)
        cv.text(f.h2, f"{g.name}, jellyfish #{j.id}", topleft=(x + 24, y))
        cv.text(f.small, "ESC to close", t.TEXT_DIM, topright=(rx + rw - 12, ry + 12))
        y += 30
        age = (eng.t if j.alive else (j.death_t or eng.t)) - j.birth_t
        status = "alive" if j.alive else f"died ({j.death_cause}) on day {j.death_t}"
        lines = [
            f"status    {status}",
            f"depth     {j.depth.label}",
            f"position  ({j.x:6.1f}, {j.y:6.1f}) km  (hidden from player)",
            f"age       {age} / {eng.config.lifetime_days} days, generation {j.generation}",
            f"eaten     {j.eat_days_total} days ({'mature' if j.is_mature else 'growing'})",
            f"summer    {j.summer_feed_days} feed days, capacity {j.capacity}",
            f"offspring {j.offspring}",
        ]
        for line in lines:
            cv.text(f.mono_small, line, topleft=(x, y))
            y += 18
        mem = j.memory[:24].hex(" ") + ("..." if len(j.memory) > 24 else "")
        cv.text(f.mono_small, f"memory    {mem}", t.TEXT_DIM, topleft=(x, y + 2))

    def draw_help(self) -> None:
        cv, f = self.cv, self.fonts
        w, h = 560, 520
        rx = t.OCEAN_X + (t.OCEAN_PX - w) / 2
        ry = t.OCEAN_Y + (t.OCEAN_PX - h) / 2
        self.card((rx, ry, w, h))
        x, y = rx + 24, ry + 20
        cv.text(f.h2, "Controls", topleft=(x, y))
        y += 34
        rows = [
            ("SPACE", "play / pause"),
            ("RIGHT", "advance one day"),
            ("UP / DOWN", "faster / slower"),
            ("scroll, + / -", "zoom in / out (Z resets)"),
            ("drag", "pan while zoomed in"),
            ("hover", "list the jellyfish in a grid cell"),
            ("L", "show one depth at a time"),
            ("T", "toggle trails"),
            ("G", "linear / log population chart"),
            ("1-9, 0", "show / hide groups 1-10"),
            ("click", "inspect a jellyfish"),
            ("H / ESC", "close help / quit"),
        ]
        for k, v in rows:
            cv.text(f.mono, k, topleft=(x, y + 1))
            cv.text(f.body, v, t.TEXT_DIM, topleft=(x + 150, y))
            y += 26
        y += 8
        cv.text(f.h2, "Legend", topleft=(x, y))
        y += 28
        for kind in ZoneKind:
            cv.text(
                f.body,
                f"{t.ZONE_LABELS[kind].capitalize()}: {t.ZONE_STYLE_HINT[kind]}",
                t.TEXT_DIM,
                topleft=(x, y),
            )
            y += 22
        cv.text(
            f.body,
            "Smaller jellyfish = deeper. Thicker outline = zone is open.",
            t.TEXT_DIM,
            topleft=(x, y),
        )

    def draw_banner(self) -> None:
        cv, f = self.cv, self.fonts
        w = 470
        rx = t.OCEAN_X + (t.OCEAN_PX - w) / 2
        ry = t.OCEAN_Y + 52
        self.card((rx, ry, w, 66))
        cv.text(f.h2, "Simulation complete", center=(rx + w / 2, ry + 22))
        cv.text(
            f.small,
            "Close the window (or ESC) to print results to the terminal.",
            t.TEXT_DIM,
            center=(rx + w / 2, ry + 46),
        )
