import random

from core import snapshot, current
from core.depth import Depth
from core.player import Player
from core.action import Action
from core.seasons import Season
from math import cos, radians, sin
from math import atan2, cos, sin, tau
from itertools import combinations, product
from core.snapshot import JellyfishSnapshot


class Player8(Player):
    """Group 8's jellyfish.

    Called once per living jellyfish per day. Read what the jellyfish senses
    from `snapshot`, update `snapshot.memory` in place if you want to
    remember something, and return an Action choosing today's depth.

    Do not keep per-jellyfish state on `self`: memory is the only memory.
    """

    def __init__(self, memory_size: int, lifetime_days: int, rng: random.Random) -> None:
        super().__init__(memory_size, lifetime_days, rng)
        self.current_speeds = [40, 20, 10, 5]
        self.first_k_days = 4
        self.mandatory_exploration_days = 30
        self.visited_flag = 1
        self.breeding_flag = 2
        self.feeding_flag = 4
        self.predator_flag = 8

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        return self.act_as_per_highest_memory(snapshot)

    def act_as_per_highest_memory(self, s: JellyfishSnapshot) -> Action:
        """
        We have 1024 memory bytes | Value range	0–255
        Bytes 0–3: headings
        Bytes 4–7: position
        Bytes 8–107: observations for the 100 grid cells
        1 byte = 8 bits | 1-visited_flag 2-breeding_flag 3-feeding_flag 4-predator_flag
        Using total 107/1024 bytes
        """
        should_log = random.random() > 0.99
        x, y = self.update_position(s)
        self.set_heading(s)
        self.update_grid_cell(s, x, y)
        if s.day_of_year < 10 or should_log:
            print("Memory:", self.decode_memory(s.memory))
            print("coordinates:", x, y)
            print("year and day_of_year:", s.year, s.day_of_year)
            print("bd year and day_of_year:", s.birth_year, s.birth_day_of_year)
            print("season:", s.season)
            print()

        # Exploration and data gathering and refinement
        if s.year == 1 and s.day_of_year <= self.first_k_days:
            return self.do_mandatory_first_four_steps(s)
        if s.year == 1 and s.day_of_year <= self.mandatory_exploration_days:
            depth = self.explore_grid(s, x, y)
            action = Action(depth) if depth is not None else Action(Depth.DEEP)
            return action

        # Alternate between feeding and breeding
        if s.season == Season.SPRING:
            if s.in_feeding_zone:
                return self.stay_put(s, x, y, self.feeding_flag)
            else:
                return self.move_to_feeding_zone(s, x, y)
        if s.season == Season.SUMMER:
            if s.in_feeding_zone:
                return self.stay_put(s, x, y, self.feeding_flag)
            else:
                return self.move_to_feeding_zone(s, x, y)
        if s.season == Season.FALL:
            if s.in_breeding_zone:
                return self.stay_put(s, x, y, self.breeding_flag)
            else:
                return self.move_to_breeding_zone(s, x, y)
        if s.season == Season.WINTER:
            if s.in_breeding_zone:
                return self.stay_put(s, x, y, self.breeding_flag)
            else:
                return self.move_to_breeding_zone(s, x, y)

        return Action(random.choice(list(Depth)))

    @staticmethod
    def update_grid_cell(s: JellyfishSnapshot, x: float, y: float):
        column = int((x % 1000) // 100)
        row = int((y % 1000) // 100)
        cell = row * 10 + column
        flags = 1  # Visited
        if s.in_breeding_zone:
            flags |= 2
        if s.in_feeding_zone:
            flags |= 4
        if s.in_predator_zone:
            flags |= 8
        s.memory[8 + cell] |= flags

    @staticmethod
    def get_current_coordinates(m: bytearray):
        """
        saved value looks like 4:12 5:34 6:88 7:56 (byte:value)
        x = 1234 | y = 8856
        x_in_km = 123.4 | y_in_km = 885.6
        """
        x = int.from_bytes(m[4:6], "little") / 10
        y = int.from_bytes(m[6:8], "little") / 10
        return x, y

    @staticmethod
    def do_mandatory_first_four_steps(s: JellyfishSnapshot):
        assert s.day_of_year <= 4
        if s.year == s.birth_year and s.day_of_year == 1:
            return Action(Depth.SURFACE)
        if s.year == s.birth_year and s.day_of_year == 2:
            return Action(Depth.SHALLOW)
        if s.year == s.birth_year and s.day_of_year == 3:
            return Action(Depth.MEDIUM)
        return Action(Depth.DEEP)

    @staticmethod
    def set_heading(s: JellyfishSnapshot):
        if s.depth == Depth.SURFACE:
            s.memory[0] = 1 + (round(s.heading * 255 / 360) % 255)
        if s.depth == Depth.SHALLOW:
            s.memory[1] = 1 + (round(s.heading * 255 / 360) % 255)
        if s.depth == Depth.MEDIUM:
            s.memory[2] = 1 + (round(s.heading * 255 / 360) % 255)
        if s.depth == Depth.DEEP:
            s.memory[3] = 1 + (round(s.heading * 255 / 360) % 255)
        return None

    @staticmethod
    def update_position(s: JellyfishSnapshot):
        x = int.from_bytes(s.memory[4:6], "little") / 10
        y = int.from_bytes(s.memory[6:8], "little") / 10
        is_offspring = s.birth_year > 1 or s.birth_day_of_year > 1
        # Offsprings get their first turn the day after birth.
        if is_offspring:
            first_turn = s.age_days == 1
        else:
            first_turn = s.age_days == 0
        if not first_turn:
            dx, dy = s.velocity
            x = (x + dx) % 1000
            y = (y + dy) % 1000
        x_units = round(x * 10) % 10000
        y_units = round(y * 10) % 10000
        s.memory[4:6] = x_units.to_bytes(2, "little")
        s.memory[6:8] = y_units.to_bytes(2, "little")
        return x_units / 10, y_units / 10

    @staticmethod
    def explore_grid(s: JellyfishSnapshot, x: float, y: float) -> Depth | None:
        heading_slots = (
            (Depth.SURFACE, 0),
            (Depth.SHALLOW, 1),
            (Depth.MEDIUM, 2),
            (Depth.DEEP, 3),
        )
        velocities = {}
        for depth, slot in heading_slots:
            angle = radians((s.memory[slot] - 1) * 360 / 255)
            velocities[depth] = (depth.speed * sin(angle), -depth.speed * cos(angle))
        # Fastest pairs first, using the faster depth as the first leg.
        pairs = list(combinations(
            sorted(velocities, key=lambda current_depth: current_depth.speed, reverse=True), 2
        ))

        visited = 1
        targets = []
        for target_cell in range(100):
            if s.memory[8 + target_cell] & visited:
                continue
            target_x = (target_cell % 10) * 100 + 50
            target_y = (target_cell // 10) * 100 + 50
            dx = (target_x - x + 500) % 1000 - 500
            dy = (target_y - y + 500) % 1000 - 500
            targets.append((dx * dx + dy * dy, dx, dy))

        # which cell to go; since sorted try for nearest cell
        for _, dx, dy in sorted(targets):
            # which pair of currents should we select
            for first, second in pairs:
                ax, ay = velocities[first]
                bx, by = velocities[second]
                determinant = ax * by - ay * bx
                if abs(determinant) < 1e-9:
                    continue
                best_route = None
                # which side of torus should we move
                for wrap_x, wrap_y in product((-1000, 0, 1000), repeat=2):
                    tx = dx + wrap_x
                    ty = dy + wrap_y
                    # Solve days_a * (ax, ay) + days_b * (bx, by) = (tx, ty).
                    days_a = (tx * by - ty * bx) / determinant
                    days_b = (ax * ty - ay * tx) / determinant
                    if days_a < -1e-9 or days_b < -1e-9:
                        continue
                    a, b = round(days_a), round(days_b)
                    if a + b == 0:
                        continue
                    # Confirm the rounded route ends inside the target cell.
                    error_x = a * ax + b * bx - tx
                    error_y = a * ay + b * by - ty
                    if abs(error_x) >= 50 or abs(error_y) >= 50:
                        continue
                    if best_route is None or a + b < sum(best_route):
                        best_route = (a, b)
                if best_route is not None:
                    return first if best_route[0] > 0 else second
        return None

    def stay_put(self, s: JellyfishSnapshot, x: float, y: float, zone_flag: int) -> Action:
        target = self.estimate_zone_center(s.memory, zone_flag)
        if target is None:
            return Action(Depth.DEEP)
        velocities = self.current_velocities(s)
        depth = self.best_next_depth(velocities, x, y, target)
        return Action(depth)

    def move_to_breeding_zone(self, s: JellyfishSnapshot, x: float, y: float) -> Action:
        target = self.estimate_zone_center(s.memory, 2)  # Breeding
        if target is None:
            return Action(Depth.DEEP)
        return Action(self.depth_toward(s, x, y, target))

    def move_to_feeding_zone(self, s: JellyfishSnapshot, x: float, y: float) -> Action:
        target = self.estimate_zone_center(s.memory, 4)  # Feeding
        if target is None:
            depth = self.explore_grid(s, x, y)
            return Action(depth if depth is not None else Depth.SURFACE)
        return Action(self.depth_toward(s, x, y, target))

    @staticmethod
    def wrapped_mean(values: list[float]) -> float:
        angles = [value * tau / 1000 for value in values]
        angle = atan2(sum(sin(a) for a in angles), sum(cos(a) for a in angles))
        return (angle * 1000 / tau) % 1000

    def estimate_zone_center(self, memory: bytearray, zone_flag: int) -> tuple[float, float] | None:
        xs, ys = [], []
        for cell, flags in enumerate(memory[8:108]):
            if flags & zone_flag:
                row, column = divmod(cell, 10)
                xs.append(column * 100 + 50)
                ys.append(row * 100 + 50)
        if not xs:
            return None
        return self.wrapped_mean(xs), self.wrapped_mean(ys)

    def best_next_depth(
            self, velocities: dict[Depth, tuple[float, float]],
            x: float, y: float, target: tuple[float, float]
        ) -> Depth:
        target_x, target_y = target
        def distance_after_move(depth: Depth) -> float:
            vx, vy = velocities[depth]
            dx = self.wrapped_delta(x + vx, target_x)
            dy = self.wrapped_delta(y + vy, target_y)
            return dx * dx + dy * dy
        return min(velocities, key=distance_after_move)

    @staticmethod
    def wrapped_delta(start: float, end: float) -> float:
        return (end - start + 500) % 1000 - 500

    @staticmethod
    def current_velocities(s: JellyfishSnapshot) -> dict[Depth, tuple[float, float]]:
        slots = (
            (Depth.SURFACE, 0),
            (Depth.SHALLOW, 1),
            (Depth.MEDIUM, 2),
            (Depth.DEEP, 3),
        )
        velocities = {}
        for depth, slot in slots:
            angle = radians((s.memory[slot] - 1) * 360 / 255)
            velocities[depth] = (
                depth.speed * sin(angle),
                -depth.speed * cos(angle),
            )
        velocities[s.depth] = s.velocity
        return velocities

    def depth_toward(self, s: JellyfishSnapshot, x: float, y: float, target: tuple[float, float]) -> Depth:
        velocities = self.current_velocities(s)
        dx = self.wrapped_delta(x, target[0])
        dy = self.wrapped_delta(y, target[1])
        best_depth = None
        best_score = (float("inf"), float("inf"))

        for first, second in combinations(velocities, 2):
            ax, ay = velocities[first]
            bx, by = velocities[second]
            determinant = ax * by - ay * bx
            if abs(determinant) < 1e-9:
                continue

            for wrap_x, wrap_y in product((-1000, 0, 1000), repeat=2):
                tx, ty = dx + wrap_x, dy + wrap_y
                days_a = (tx * by - ty * bx) / determinant
                days_b = (ax * ty - ay * tx) / determinant
                if days_a < -1e-9 or days_b < -1e-9:
                    continue

                a, b = round(days_a), round(days_b)
                if a + b == 0:
                    continue

                error_x = a * ax + b * bx - tx
                error_y = a * ay + b * by - ty
                error_squared = error_x * error_x + error_y * error_y
                score = (a + b, error_squared)
                if error_squared <= 20 ** 2 and score < best_score:
                    best_score = score
                    best_depth = first if a > 0 else second

        if best_depth is not None:
            return best_depth

        return self.best_next_depth(velocities, x, y, target)

    def decode_memory(self, memory: bytearray) -> str:
        x, y = self.get_current_coordinates(memory)
        lines = [
            f"Position: ({x:.1f}, {y:.1f}) km",
            f"Position bytes: x={list(memory[4:6])}, y={list(memory[6:8])}",
            "",
            "Current headings:",
        ]

        for depth, encoded in zip(Depth, memory[:4]):
            if encoded == 0:
                lines.append(f"  {depth.name}: unseen")
            else:
                heading = (encoded - 1) * 360 / 255
                lines.append(f"  {depth.name}: {heading:.1f}° (byte {encoded})")

        lines.extend(("", "Visited cells (row, column):"))
        zone_flags = ((2, "breeding"), (4, "feeding"), (8, "predator"))
        visited_count = 0

        for cell, flags in enumerate(memory[8:108]):
            if not flags & 1:
                continue

            visited_count += 1
            row, column = divmod(cell, 10)
            zones = [name for bit, name in zone_flags if flags & bit]
            observation = ", ".join(zones) if zones else "no zone observed"
            lines.append(f"  ({row}, {column}): {observation}")

        lines.append(f"Cells visited: {visited_count}/100")
        return "\n".join(lines)