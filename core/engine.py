from __future__ import annotations

import random
import sys
import traceback
from dataclasses import dataclass, field
from time import perf_counter

import core.constants as c
from core.action import Action
from core.depth import Depth
from core.geometry import wrap
from core.jellyfish import Jellyfish
from core.ocean import Ocean
from core.player import Player
from core.seasons import Season, day_of_year, season_of, year_of
from core.snapshot import JellyfishSnapshot
from core.stats import GroupStats

FALL_FIRST_DAY = 2 * c.DAYS_PER_SEASON + 1  # day 181


@dataclass
class Group:
    """One competing team. Every group lives in the same ocean but never
    interacts with the others."""

    index: int
    key: str  # registry key, e.g. "3" or "r"
    name: str
    player: Player
    rng: random.Random
    stats: GroupStats
    alive: list[Jellyfish] = field(default_factory=list)
    error: str | None = None
    time_used: float = 0.0

    @property
    def population(self) -> int:
        return len(self.alive)


@dataclass(frozen=True)
class Event:
    """Something the GUI may want to animate (births, deaths)."""

    kind: str  # "birth" | "predator" | "age"
    group: int
    x: float
    y: float
    depth: Depth = Depth.SURFACE


@dataclass(frozen=True)
class SimConfig:
    memory_size: int
    lifetime_days: int
    initial_jellyfish: int
    days: int
    max_population: int


class Engine:
    def __init__(
        self,
        ocean: Ocean,
        groups: list[Group],
        config: SimConfig,
        start_positions: list[tuple[float, float]],
    ) -> None:
        self.ocean = ocean
        self.groups = groups
        self.config = config
        self.t = 0  # days elapsed; the next day to simulate has index t
        self.events: list[Event] = []
        self._next_id = 0

        # Every group starts from the SAME positions, so comparisons are fair.
        for g in groups:
            for x, y in start_positions:
                g.alive.append(self._new_jelly(g.index, x, y, Depth.SURFACE, None))
            g.stats.record(0, g.population)

    # ------------------------------------------------------------------ util
    def _new_jelly(
        self,
        group: int,
        x: float,
        y: float,
        depth: Depth,
        parent: Jellyfish | None,
    ) -> Jellyfish:
        self._next_id += 1
        return Jellyfish(
            id=self._next_id,
            group=group,
            x=x,
            y=y,
            depth=depth,
            memory=bytearray(parent.memory)
            if parent
            else bytearray(self.config.memory_size),
            birth_t=self.t,
            generation=parent.generation + 1 if parent else 0,
            parent_id=parent.id if parent else None,
        )

    @property
    def finished(self) -> bool:
        return self.t >= self.config.days or all(g.population == 0 for g in self.groups)

    @property
    def day_of_year(self) -> int:
        return day_of_year(self.t)

    @property
    def year(self) -> int:
        return year_of(self.t)

    @property
    def season(self) -> Season:
        return season_of(self.day_of_year)

    # ------------------------------------------------------------------ turn
    def step(self) -> None:
        """Simulate one day for every group."""
        if self.t >= self.config.days:
            return

        self.events = []
        doy = self.day_of_year

        # Summer just ended: turn last summer's eating into winter capacity.
        if doy == FALL_FIRST_DAY:
            for g in self.groups:
                for j in g.alive:
                    j.capacity = j.summer_feed_days // c.EAT_DAYS_PER_OFFSPRING
                    j.summer_feed_days = 0

        for g in self.groups:
            if g.error is None:
                self._step_group(g, doy)

        self.t += 1
        for g in self.groups:
            g.stats.record(self.t, g.population)

    def _kill(self, g: Group, j: Jellyfish, cause: str) -> None:
        j.alive = False
        j.death_t = self.t
        j.death_cause = cause
        if cause == "predator":
            g.stats.deaths_predator += 1
        elif cause == "age":
            g.stats.deaths_age += 1
        self.events.append(Event(cause, g.index, j.x, j.y, j.depth))

    def _step_group(self, g: Group, doy: int) -> None:
        ocean = self.ocean
        year = self.year
        season = season_of(doy)
        survivors: list[Jellyfish] = []
        newborns: list[Jellyfish] = []

        for j in g.alive:
            # 1. old age
            if self.t - j.birth_t >= self.config.lifetime_days:
                self._kill(g, j, "age")
                continue

            # 2. sense (at the start-of-day position)
            in_feed = ocean.feeding.contains(j.x, j.y)
            in_breed = ocean.breeding.contains(j.x, j.y)
            in_pred = ocean.predator.contains(j.x, j.y)

            # 3. predation risk for starting the day in the predator zone
            if in_pred and g.rng.random() < c.PREDATION_PROBABILITY:
                self._kill(g, j, "predator")
                continue

            cur = ocean.currents[j.depth]
            snap = JellyfishSnapshot(
                day_of_year=doy,
                year=year,
                season=season,
                birth_day_of_year=day_of_year(j.birth_t),
                birth_year=year_of(j.birth_t),
                depth=j.depth,
                heading=cur.heading,
                speed=cur.speed,
                velocity=cur.velocity,
                in_feeding_zone=in_feed,
                in_breeding_zone=in_breed,
                in_predator_zone=in_pred,
                reproduction_capacity=j.capacity,
                memory=j.memory,
            )

            # 4. ask the player
            start = perf_counter()
            try:
                action = g.player.act(snap)
                action = self._validate(action, j)
            except Exception:  # noqa: BLE001 - one broken group must not stop the run
                g.time_used += perf_counter() - start
                self._crash(g, traceback.format_exc())
                return
            g.time_used += perf_counter() - start

            # 5. eat
            if action.eat and in_feed and season == Season.SUMMER:
                g.stats.eat_days += 1
                if j.eat_days_total >= c.EAT_DAYS_TO_MATURE:
                    j.summer_feed_days += 1
                j.eat_days_total += 1

            # 6. reproduce (max one offspring per day). No jellyfish may be
            #    born inside the predator zone, so a parent standing where the
            #    breeding and predator zones overlap keeps its capacity for later.
            if (
                action.reproduce
                and in_breed
                and not in_pred
                and season == Season.WINTER
                and j.capacity > 0
            ):
                if g.population + len(newborns) < self.config.max_population:
                    j.capacity -= 1
                    j.offspring += 1
                    baby = self._new_jelly(g.index, j.x, j.y, action.depth, j)
                    newborns.append(baby)
                    g.stats.births += 1
                    g.stats.max_generation = max(
                        g.stats.max_generation, baby.generation
                    )
                    self.events.append(Event("birth", g.index, j.x, j.y, baby.depth))
                else:
                    g.stats.births_blocked += 1

            # 7. drift with the chosen current
            j.depth = action.depth
            dx, dy = ocean.currents[j.depth].velocity
            j.prev_x, j.prev_y = j.x, j.y
            j.x, j.y = wrap(j.x + dx), wrap(j.y + dy)
            survivors.append(j)

        g.alive = survivors + newborns

    def _validate(self, action: object, j: Jellyfish) -> Action:
        if not isinstance(action, Action):
            raise TypeError(f"act() must return an Action, got {action!r}")
        if not isinstance(action.depth, Depth):
            try:
                action = Action(Depth(action.depth), action.eat, action.reproduce)
            except ValueError:
                raise ValueError(f"invalid depth {action.depth!r}") from None
        if not isinstance(j.memory, bytearray) or len(j.memory) != (
            self.config.memory_size
        ):
            raise ValueError(
                f"memory length changed to {len(j.memory)} "
                f"(must stay {self.config.memory_size} bytes)"
            )
        return action

    def _crash(self, g: Group, tb: str) -> None:
        g.error = tb.strip().splitlines()[-1]
        print(f"\n[{g.name}] player crashed on day {self.t}:\n{tb}", file=sys.stderr)
        for j in g.alive:
            j.alive = False
            j.death_cause = "error"
        g.alive = []

    # ---------------------------------------------------------------- driver
    def run(self) -> None:
        while not self.finished:
            self.step()
        # if every group went extinct early, still fill t up to the end
        # (history stays at 0) so results are comparable
        while self.t < self.config.days:
            self.t += 1
            for g in self.groups:
                g.stats.record(self.t, g.population)

    def results(self) -> dict:
        return {
            "days_simulated": self.t,
            "groups": {
                g.name: {
                    "player": str(g.player),
                    "error": g.error,
                    "time_used_s": round(g.time_used, 4),
                    **g.stats.to_dict(),
                }
                for g in self.groups
            },
        }
