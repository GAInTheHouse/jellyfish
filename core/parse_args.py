import argparse
import os
import pathlib
from time import time

import core.constants as c
from core.args import PLAYERS, Args, MapArgs


def get_maps_dir() -> pathlib.Path:
    return pathlib.Path(os.path.curdir, "maps").resolve()


def get_map(map_path: str | None) -> MapArgs | None:
    if map_path is None:
        return None

    path = pathlib.Path(map_path).resolve()
    if not path.is_file():
        raise SystemExit(f'map file "{path}" not found')
    try:
        path.relative_to(get_maps_dir())
    except ValueError:
        raise SystemExit('map file must be inside the "maps/" directory') from None

    return MapArgs.read(path)


def parse_args(argv: list[str] | None = None) -> Args:
    parser = argparse.ArgumentParser(
        description="Run the Jellyfish migration simulator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--players",
        nargs="+",
        default=["r"],
        choices=list(PLAYERS.keys()),
        metavar="P",
        help="Players sharing the ocean: 'r' random, 'e' example, or 1-10 for a "
        "group. Repeats are allowed, e.g. --players 3 3 r",
    )
    parser.add_argument("--gui", action="store_true", help="Open the visualizer")
    parser.add_argument("--seed", type=int, help="Random seed (default: from clock)")
    parser.add_argument(
        "-T",
        "--days",
        type=int,
        default=c.DEFAULT_DAYS,
        help="Number of days (turns) to simulate",
    )
    parser.add_argument(
        "-M",
        "--memory",
        type=int,
        default=c.DEFAULT_MEMORY_BYTES,
        help=f"Jellyfish memory in bytes ({c.MIN_MEMORY_BYTES}-{c.MAX_MEMORY_BYTES})",
    )
    parser.add_argument(
        "-S",
        "--lifetime",
        type=float,
        default=c.DEFAULT_LIFETIME_YEARS,
        help="Jellyfish lifetime S in years (need not be an integer)",
    )
    parser.add_argument(
        "-J",
        "--initial",
        type=int,
        default=c.DEFAULT_INITIAL_JELLYFISH,
        help="Number of jellyfish each group starts with",
    )
    parser.add_argument(
        "--max_population",
        type=int,
        default=c.DEFAULT_MAX_POPULATION,
        help="Per-group population cap (births beyond it are skipped)",
    )
    parser.add_argument(
        "--map_path", help="JSON file under maps/ fixing zones and/or currents"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print only the JSON results"
    )

    ns = parser.parse_args(argv)

    if ns.seed is None:
        ns.seed = int(time() * 10_000) % 100_000
        if not ns.json:
            print(f"Generated seed: {ns.seed}")
    if not (c.MIN_MEMORY_BYTES <= ns.memory <= c.MAX_MEMORY_BYTES):
        parser.error(f"--memory must be in {c.MIN_MEMORY_BYTES}..{c.MAX_MEMORY_BYTES}")
    if ns.lifetime <= 0:
        parser.error("--lifetime must be > 0")
    if not (1 <= ns.days <= c.MAX_DAYS):
        parser.error(f"-T must be in 1..{c.MAX_DAYS}")
    if ns.initial < 1:
        parser.error("-J must be >= 1")
    if ns.max_population < ns.initial:
        parser.error("--max_population must be >= -J")

    return Args(
        gui=ns.gui,
        seed=ns.seed,
        players=ns.players,
        memory=ns.memory,
        lifetime_years=ns.lifetime,
        initial_jellyfish=ns.initial,
        days=ns.days,
        max_population=ns.max_population,
        map=get_map(ns.map_path),
        json_only=ns.json,
    )
