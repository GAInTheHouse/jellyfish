from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GroupStats:
    initial: int
    history: list[int] = field(default_factory=list)  # population at end of each day
    births: int = 0
    births_blocked: int = 0  # births skipped because of --max_population
    deaths_predator: int = 0
    deaths_age: int = 0
    eat_days: int = 0
    peak: int = 0
    peak_day: int = 0
    max_generation: int = 0
    extinct_day: int | None = None
    milestones: dict[int, int | None] = field(default_factory=dict)  # multiple -> day

    def __post_init__(self) -> None:
        self.peak = self.initial
        self.milestones = {10: None, 100: None}

    def record(self, day: int, population: int) -> None:
        self.history.append(population)
        if population > self.peak:
            self.peak, self.peak_day = population, day
        if population == 0 and self.extinct_day is None:
            self.extinct_day = day
        for mult, reached in self.milestones.items():
            if reached is None and population >= mult * self.initial:
                self.milestones[mult] = day

    def to_dict(self) -> dict:
        return {
            "final_population": self.history[-1] if self.history else self.initial,
            "peak_population": self.peak,
            "peak_day": self.peak_day,
            "births": self.births,
            "births_blocked_by_cap": self.births_blocked,
            "deaths_predator": self.deaths_predator,
            "deaths_age": self.deaths_age,
            "eat_days": self.eat_days,
            "max_generation": self.max_generation,
            "extinct_day": self.extinct_day,
            "day_reached_10J": self.milestones[10],
            "day_reached_100J": self.milestones[100],
        }
