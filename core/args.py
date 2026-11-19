from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import core.constants as c
from core.depth import Depth
from core.player import Player
from players.example_player import ExamplePlayer
from players.group1.player import Player1
from players.group2.player import Player2
from players.group3.player import Player3
from players.group4.player import Player4
from players.group5.player import Player5
from players.group6.player import Player6
from players.group7.player import Player7
from players.group8.player import Player8
from players.group9.player import Player9
from players.group10.player import Player10
from players.random_player import RandomPlayer

PLAYERS: dict[str, type[Player]] = {
    "r": RandomPlayer,
    "e": ExamplePlayer,
    "1": Player1,
    "2": Player2,
    "3": Player3,
    "4": Player4,
    "5": Player5,
    "6": Player6,
    "7": Player7,
    "8": Player8,
    "9": Player9,
    "10": Player10,
}


def player_display_name(key: str) -> str:
    if key == "r":
        return "Random"
    if key == "e":
        return "Example"
    return f"Group {key}"


@dataclass
class Args:
    gui: bool
    seed: int
    players: list[str]
    memory: int
    lifetime_years: float
    initial_jellyfish: int
    days: int
    max_population: int
    map: MapArgs | None
    json_only: bool


@dataclass
class MapArgs:
    """Optional fixed ocean layout loaded from maps/*.json.

    Every key is optional; anything missing is randomised from the seed:
        {
          "feeding":  [x, y],
          "breeding": [x, y],
          "predator": [x, y],
          "currents": {"surface": 90, "shallow": 180, "medium": 0, "deep": 270}
        }
    Current values are compass headings in degrees (0 = north, 90 = east).
    """

    feeding: tuple[float, float] | None
    breeding: tuple[float, float] | None
    predator: tuple[float, float] | None
    headings: dict[Depth, float]

    @staticmethod
    def read(path: pathlib.Path) -> MapArgs:
        with open(path, "r") as f:
            data = json.load(f)

        def point(key: str) -> tuple[float, float] | None:
            v = data.get(key)
            if v is None:
                return None
            if (
                not isinstance(v, list)
                or len(v) != 2
                or not all(isinstance(n, (int, float)) for n in v)
            ):
                raise TypeError(f"'{key}' must be an [x, y] pair")
            if not all(0 <= n < c.OCEAN_SIZE for n in v):
                raise ValueError(f"'{key}' must be inside 0..{c.OCEAN_SIZE:.0f}")
            return float(v[0]), float(v[1])

        headings: dict[Depth, float] = {}
        for name, h in (data.get("currents") or {}).items():
            try:
                d = Depth[name.upper()]
            except KeyError:
                raise ValueError(f"unknown current depth '{name}'") from None
            if not isinstance(h, (int, float)):
                raise TypeError(f"heading for '{name}' must be a number")
            headings[d] = float(h) % 360

        return MapArgs(point("feeding"), point("breeding"), point("predator"), headings)
