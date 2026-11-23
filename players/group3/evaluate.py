"""Evaluate group 3's player over a grid of seeded headless simulations.

Usage (from the repository root):
    uv run python players/group3/evaluate.py
    uv run python players/group3/evaluate.py --seeds 1 2 3 --days 1800

Every combination of seed x initial population x lifetime is run with only our
player in the ocean, and one CSV row per run is written to
players/group3/results/eval_<timestamp>.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import product
from pathlib import Path

GROUP_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = GROUP_DIRECTORY.parent.parent
RESULTS_DIRECTORY = GROUP_DIRECTORY / "results"

PLAYER_KEY = "3"
DEFAULT_SEEDS = [1, 2, 3, 4, 5]
DEFAULT_INITIAL_POPULATIONS = [10, 20, 40]
DEFAULT_LIFETIMES_YEARS = [3.0, 4.0, 5.0]
DEFAULT_DAYS = 3600
DEFAULT_MEMORY_BYTES = 1024


@dataclass(frozen=True)
class RunArguments:
    """Simulator arguments of one run."""

    seed: int
    initial_jellyfish: int
    lifetime_years: float
    days: int
    memory_bytes: int


@dataclass(frozen=True)
class RunResult:
    """One CSV row: the run arguments followed by the outcome."""

    seed: int
    initial_jellyfish: int
    lifetime_years: float
    days: int
    memory_bytes: int
    total_jellyfish: int  # initial + every birth during the run
    surviving: int
    eaten: int
    died_of_old_age: int
    births: int
    births_blocked_by_cap: int
    peak_population: int
    extinct_day: int | None
    day_reached_10J: int | None
    day_reached_100J: int | None
    player_time_seconds: float
    error: str | None


def build_run_grid(
    seeds: list[int],
    initial_populations: list[int],
    lifetimes_years: list[float],
    days: int,
    memory_bytes: int,
) -> list[RunArguments]:
    return [
        RunArguments(seed, initial_jellyfish, lifetime_years, days, memory_bytes)
        for seed, initial_jellyfish, lifetime_years in product(
            seeds, initial_populations, lifetimes_years
        )
    ]


def run_simulation(run_arguments: RunArguments) -> RunResult:
    """Run one headless simulation in a subprocess and parse its JSON output."""
    command = [
        sys.executable,
        "main.py",
        "--players",
        PLAYER_KEY,
        "--json",
        "--seed",
        str(run_arguments.seed),
        "-J",
        str(run_arguments.initial_jellyfish),
        "-S",
        str(run_arguments.lifetime_years),
        "-T",
        str(run_arguments.days),
        "-M",
        str(run_arguments.memory_bytes),
    ]
    completed = subprocess.run(
        command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(f"simulation failed: {completed.stderr.strip()}")
    group_statistics = next(iter(json.loads(completed.stdout)["groups"].values()))
    return RunResult(
        **asdict(run_arguments),
        total_jellyfish=run_arguments.initial_jellyfish + group_statistics["births"],
        surviving=group_statistics["final_population"],
        eaten=group_statistics["deaths_predator"],
        died_of_old_age=group_statistics["deaths_age"],
        births=group_statistics["births"],
        births_blocked_by_cap=group_statistics["births_blocked_by_cap"],
        peak_population=group_statistics["peak_population"],
        extinct_day=group_statistics["extinct_day"],
        day_reached_10J=group_statistics["day_reached_10J"],
        day_reached_100J=group_statistics["day_reached_100J"],
        player_time_seconds=group_statistics["time_used_s"],
        error=group_statistics["error"],
    )


def write_results_csv(results: list[RunResult], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(asdict(results[0])))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)


def print_summary(results: list[RunResult]) -> None:
    """Short console digest; the CSV has the full detail."""
    run_count = len(results)
    surviving_runs = [result for result in results if result.surviving > 0]
    growing_runs = [
        result for result in results if result.surviving > result.initial_jellyfish
    ]
    crashed_runs = [result for result in results if result.error]
    print(f"runs:                 {run_count}")
    print(f"survived to the end:  {len(surviving_runs)}")
    print(f"grew beyond initial:  {len(growing_runs)}")
    print(f"crashed:              {len(crashed_runs)}")
    print(f"total jellyfish:      {sum(result.total_jellyfish for result in results)}")
    print(f"total surviving:      {sum(result.surviving for result in results)}")
    print(f"total eaten:          {sum(result.eaten for result in results)}")
    print(f"total died of age:    {sum(result.died_of_old_age for result in results)}")


def evaluate(
    seeds: list[int],
    initial_populations: list[int],
    lifetimes_years: list[float],
    days: int = DEFAULT_DAYS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    worker_count: int | None = None,
    csv_path: Path | None = None,
) -> Path:
    """Run the whole grid, write the CSV, and return its path."""
    run_grid = build_run_grid(
        seeds, initial_populations, lifetimes_years, days, memory_bytes
    )
    # Threads are enough: each run is its own subprocess.
    with ThreadPoolExecutor(max_workers=worker_count or os.cpu_count()) as executor:
        results = list(executor.map(run_simulation, run_grid))

    if csv_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = RESULTS_DIRECTORY / f"eval_{timestamp}.csv"
    write_results_csv(results, csv_path)
    print_summary(results)
    print(f"results written to {csv_path}")
    return csv_path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    parser.add_argument(
        "--initial", type=int, nargs="+", default=DEFAULT_INITIAL_POPULATIONS
    )
    parser.add_argument(
        "--lifetimes", type=float, nargs="+", default=DEFAULT_LIFETIMES_YEARS
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--memory", type=int, default=DEFAULT_MEMORY_BYTES)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None, help="CSV path")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    evaluate(
        arguments.seeds,
        arguments.initial,
        arguments.lifetimes,
        arguments.days,
        arguments.memory,
        arguments.workers,
        arguments.output,
    )
