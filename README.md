# Jellyfish

Simulator for [COMS 4444, F26 Project 4: Jellyfish](https://www.cs.columbia.edu/~kar/4444f26/node22.html).

Every group writes one `Player` class that decides, each day, which ocean
current a jellyfish rides. All selected groups run **in the same ocean at the
same time** (they never interact), so you can watch strategies side by side.

---

## Setup (once)

1. Install [uv](https://docs.astral.sh/uv/) (it also installs Python for you):
   - Windows: `winget install astral-sh.uv` (then open a new terminal)
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. In this folder run `uv sync`. This creates `.venv/` with Python 3.13 and pygame.
3. **VS Code:** open the folder, install the recommended extensions when prompted
   (Python, Python Debugger, Ruff), then press **F5** and pick a launch config.

**Windows Smart App Control:** if running anything says *"An Application Control
policy has blocked this file"*, Windows is blocking the `.venv` launcher that uv
creates. Rebuild `.venv` with Python's own launcher, which is allowed:

```powershell
Remove-Item -Recurse -Force .venv
& (uv python find 3.13) -m venv .venv
uv sync
```

## Running

```bash
uv run main.py --players r e --gui                 # random + example player, with GUI
uv run main.py --players 1 2 3 4 5 6 7 8 9 10 --gui # every group in one ocean
uv run main.py --players 4 --seed 4444 -T 7200     # headless, prints a results table
uv run main.py --players 4 --json                  # headless, JSON only
uv run main.py -h                                  # all options
```

| Argument           | Default | Description                                                         |
| :----------------- | :------ | :------------------------------------------------------------------ |
| `--players P ...`  | `r`     | `r` random, `e` example, `1`-`10` groups. Repeats allowed (`3 3`).  |
| `--gui`            | off     | Open the visualizer.                                                |
| `--seed`           | clock   | Seed for zone placement, current directions, predation, `self.rng`. |
| `-T, --days`       | `3600`  | Days to simulate (360 days = 1 year).                               |
| `-M, --memory`     | `8`     | Bytes of jellyfish memory (1-1024).                                 |
| `-S, --lifetime`   | `3`     | Lifetime in years (may be fractional).                              |
| `-J, --initial`    | `10`    | Jellyfish each group starts with.                                   |
| `--max_population` | `2000`  | Per-group cap; extra births are skipped (and counted).              |
| `--map_path`       | none    | JSON under `maps/` fixing zones and/or current headings.            |

### GUI controls

| Key           | Action                                    |
| :------------ | :---------------------------------------- |
| `SPACE`       | play / pause                              |
| `→`           | advance one day                           |
| `↑` / `↓`     | faster / slower                           |
| `L`           | show one depth layer at a time            |
| `T`           | toggle trails                             |
| `G`           | linear / log population chart             |
| `1`-`9`, `0`  | show / hide group slot 1-10               |
| click         | inspect a jellyfish (memory, eating, etc) |
| scroll, `+`/`-` | zoom in / out around the cursor (`Z` resets) |
| drag          | pan while zoomed in                       |
| hover         | list every jellyfish in that grid cell    |
| `H`, `ESC`    | help, close / quit                        |

The GUI is colour-blind friendly: colour only tells groups apart. Zones are
told apart by pattern and a text label: **solid outline** = feeding,
**dashed outline** = breeding, **hatched** = predators. A zone that is open
(feeding in summer, breeding in winter) gets a thicker outline and an
"(open)" label. Deeper jellyfish are drawn smaller. In the compass, thicker
arrows are shallower, faster currents. Lines in the population chart are
labelled with their group slot number.

---

## Writing your player

Edit `players/groupN/player.py`. You may add more files in your folder.

```python
from core.action import Action
from core.depth import Depth
from core.player import Player
from core.seasons import Season
from core.snapshot import JellyfishSnapshot


class Player4(Player):
    def act(self, s: JellyfishSnapshot) -> Action:
        if s.in_feeding_zone and s.season == Season.SUMMER:
            return Action(Depth.DEEP)  # slowest current: linger and eat
        s.memory[0] = (s.memory[0] + 1) % 256  # memory is mutated in place
        return Action(Depth.SURFACE)
```

`act` is called once per living jellyfish per day. **The jellyfish's memory
(`s.memory`, a `bytearray` of `self.memory_size` bytes) is its only memory.**
Do not keep per-jellyfish state on `self` or in globals.

### What a jellyfish senses (`JellyfishSnapshot`)

| Field                                                   | Meaning                                                    |
| :------------------------------------------------------ | :--------------------------------------------------------- |
| `day_of_year`, `year`, `season`                         | calendar (day 1-360; 90-day seasons starting with spring)  |
| `birth_day_of_year`, `birth_year`                       | when this jellyfish was born                               |
| `depth`                                                 | current depth (`Depth.SURFACE/SHALLOW/MEDIUM/DEEP`)        |
| `heading`, `speed`, `velocity`                          | the current at this depth (compass °, km/day, (dx, dy))    |
| `in_feeding_zone`, `in_breeding_zone`, `in_predator_zone` | zone membership at the start of the day                  |
| `reproduction_capacity`                                 | offspring still allowed this winter                        |
| `memory`                                                | the jellyfish's memory, mutate in place                    |

Jellyfish do **not** know their x/y position or where any zone is.

### What you return (`Action`)

`Action(depth, eat=True, reproduce=True)`. The depth you choose is the
current you drift with today.

Your class also has `self.memory_size`, `self.lifetime_days` and
`self.rng` (a seeded `random.Random`; use it instead of `random` so runs
are reproducible).

---

## Rules as implemented

These are the scaffold's interpretation of the spec. Flag anything that
should change.

- Ocean is a 1000×1000 km torus. Feeding, breeding and predator zones are
  circles of radius 200 km. Feeding and breeding never overlap. The predator
  zone may overlap either, but covers at most half of its area.
- Currents: surface 40, shallow 20, medium 10, deep 5 km/day. Each direction
  is uniformly random per run (fixed by `--seed`).
- Coordinates: x grows east, y grows south. Headings are compass bearings
  (0 = N, 90 = E).
- Each day, for each jellyfish, in order:
  1. It dies of old age if it has lived `S * 360` days.
  2. It senses its zones **at its start-of-day position**.
  3. If it starts in the predator zone it is eaten with probability 5%.
  4. `act()` is called.
  5. **Eat:** if `eat`, in the feeding zone, and it is summer. The first 30
     eating days of its life (possibly across several summers) only grow
     it. Later ones count as *feed days* for this summer.
  6. **Reproduce:** if `reproduce`, in the breeding zone, in winter, and
     capacity > 0, it spawns one offspring at its location. No jellyfish is
     ever born inside the predator zone: where breeding and predator zones
     overlap, the parent keeps its capacity for a safer day. The offspring
     gets a copy of its memory and the chosen depth, and acts from the next
     day.
  7. It moves to the chosen depth and drifts with that current.
- On day 181 (first day of fall), capacity = `feed days last summer // 10`
  and the feed-day counter resets. Unused capacity is lost at the next fall.
- Initial jellyfish are born on day 1 of year 1, at random spots in the
  breeding zone but never inside the predator zone, at the surface, with
  zeroed memory. Every group gets the
  same start spots.
- Each group has its own predation RNG, so groups never affect each other.
- If a player raises an exception, returns something other than an
  `Action`, or changes the memory's length, that group is marked crashed.
  The run continues for everyone else.

## Repository layout

```
main.py               entry point (CLI + results table)
core/                 simulator (do not edit in group PRs)
  engine.py           daily turn logic and rule enforcement
  player.py           Player base class
  snapshot.py         what jellyfish can sense
  action.py           what jellyfish can do
  ocean.py zone.py current.py depth.py seasons.py geometry.py
  ui/                 pygame visualizer
players/
  random_player.py    baseline
  example_player.py   random depth every 30 days (1-byte memory demo)
  group1..group10/    YOUR code lives here
maps/                 optional fixed layouts (JSON)
tests/                pytest suite
```

## Code quality

Same as last project: PRs must pass Ruff and the tests.

```bash
uv run ruff format         # format
uv run ruff check --fix    # lint
uv run python -m pytest    # tests (plain `uv run pytest` can be blocked by Windows Smart App Control)
```
