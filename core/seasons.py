from enum import IntEnum

import core.constants as c


class Season(IntEnum):
    SPRING = 0
    SUMMER = 1
    FALL = 2
    WINTER = 3

    @property
    def label(self) -> str:
        return self.name.capitalize()


def day_of_year(t: int) -> int:
    """1-based day of the year (1..360) for simulation day index t (0-based)."""
    return t % c.DAYS_PER_YEAR + 1


def year_of(t: int) -> int:
    """1-based year for simulation day index t (0-based)."""
    return t // c.DAYS_PER_YEAR + 1


def season_of(doy: int) -> Season:
    """Season for a 1-based day of year. Days 1-90 spring, 91-180 summer, ..."""
    return Season((doy - 1) // c.DAYS_PER_SEASON)
