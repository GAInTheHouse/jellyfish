import math
import struct

from core.action import Action
from core.depth import Depth
from core.player import Player
from core.snapshot import JellyfishSnapshot


## Helper methods
def val_to_bitarray(b: int, size=8):
    return [b >> i & 1 for i in range(size)]


def bitarray_to_val(bitarray: list[int]):
    return sum([b << i for i, b in enumerate(bitarray)])


def discretize(val: float, max_val: float, num_bits: int = 8) -> int:
    num_vals = 1 << num_bits
    return min(int(val / max_val * num_vals), num_vals - 1)


def undiscretize(val: int, max_val: float, num_bits: int = 8) -> float:
    num_vals = 1 << num_bits
    return (val + 0.5) / num_vals * max_val


def pack_float(bytes: bytearray, offset: int, val: float, double=True):
    struct.pack_into(f"<{'d' if double else 'f'}", bytes, offset, val)


def unpack_float(bytes: bytearray, offset: int, double=True) -> float:
    return struct.unpack_from(f"<{'d' if double else 'f'}", bytes, offset)[0]


def read_float(
    bytes: bytearray, offset: int, num_bytes: int, max_val: float = 360
) -> float:
    if num_bytes == 8:
        return unpack_float(bytes, offset)
    elif num_bytes == 4:
        return unpack_float(bytes, offset, double=False)
    else:
        vals = bytes[offset : offset + num_bytes]
        int_val = int.from_bytes(vals, byteorder="little")
        return undiscretize(int_val, max_val, num_bits=num_bytes * 8)


def write_float(
    val: float, bytes: bytearray, offset: int, num_bytes: int, max_val: float = 360
):
    if num_bytes == 8:
        pack_float(bytes, offset, val)
    elif num_bytes == 4:
        pack_float(bytes, offset, val, double=False)
    else:
        int_val = discretize(val, max_val, num_bits=num_bytes * 8)
        bytes[offset : offset + num_bytes] = int_val.to_bytes(
            length=num_bytes, byteorder="little"
        )


### Constants

DEPTHS = [Depth.SURFACE, Depth.SHALLOW, Depth.MEDIUM, Depth.DEEP]

SEARCH_ANGLES = [(1, 3), (3, 1), (3, -1), (1, -3), (-1, -3), (-3, -1), (-3, 1), (-1, 3)]

# Keys for the memory offsets
METADATA = "metadata"
POS_X = "pos_x"
POS_Y = "pos_y"
CURR_SURFACE = "curr_surface"
CURR_SHALLOW = "curr_shallow"
CURR_MEDIUM = "curr_medium"
CURR_DEEP = "curr_deep"
METADATA_ZONES = "metadata_zones"
CENTER_BREED_X = "center_breed_x"
CENTER_BREED_Y = "center_breed_x"
CENTER_FEED_X = "center_feed_x"
CENTER_FEED_Y = "center_feed_y"
CENTER_PRED_X = "center_pred_x"
CENTER_PRED_Y = "center_pred_y"
BREED_1_X = "breed_1_x"
BREED_1_Y = "breed_1_y"
BREED_2_X = "breed_2_x"
BREED_2_Y = "breed_2_y"
FEED_1_X = "feed_1_x"
FEED_1_Y = "feed_1_y"
FEED_2_X = "feed_2_x"
FEED_2_Y = "feed_2_y"
PRED_1_X = "pred_1_x"
PRED_1_Y = "pred_1_y"
PRED_2_X = "pred_2_x"
PRED_2_Y = "pred_2_y"

HISTORY = "history"


def memory_offsets(memory: bytearray):
    """Get the memory offsets and byte sizes for each component as a dict"""
    size = len(memory)

    if size >= 200:
        sizes = {
            METADATA: 1,
            POS_X: 8,
            POS_Y: 8,
            CURR_SURFACE: 8,
            CURR_SHALLOW: 8,
            CURR_MEDIUM: 8,
            CURR_DEEP: 8,
            METADATA_ZONES: 1,
            CENTER_BREED_X: 8,
            CENTER_BREED_Y: 8,
            CENTER_FEED_X: 8,
            CENTER_FEED_Y: 8,
            CENTER_PRED_X: 8,
            CENTER_PRED_Y: 8,
            BREED_1_X: 8,
            BREED_1_Y: 8,
            BREED_2_X: 8,
            BREED_2_Y: 8,
            FEED_1_X: 8,
            FEED_1_Y: 8,
            FEED_2_X: 8,
            FEED_2_Y: 8,
            PRED_1_X: 8,
            PRED_1_Y: 8,
            PRED_2_X: 8,
            PRED_2_Y: 8,  # Up to here is 194 bytes
            HISTORY: -1,  # Use the rest
        }
    else:
        return {}

    counter = 0
    full_dict = {}
    for key, s in sizes.items():
        full_dict[key] = (counter, s)
        counter += s

    return full_dict


def angle_distance(a, b):
    return abs((a - b + 180) % 360 - 180)


def unknown_currents(snapshot: JellyfishSnapshot) -> list[Depth]:
    # Update memory with current depth
    offsets = memory_offsets(snapshot.memory)
    metadata_off, _ = offsets[METADATA]

    metadata = val_to_bitarray(snapshot.memory[metadata_off])
    curr_depth = DEPTHS.index(snapshot.depth) + 1
    # If we haven't seen this current before, save it
    if metadata[curr_depth] == 0:
        metadata[curr_depth] = 1

        new_metadata = bitarray_to_val(metadata)
        snapshot.memory[metadata_off] = new_metadata

        static_names = [CURR_SURFACE, CURR_SHALLOW, CURR_MEDIUM, CURR_DEEP]
        offset, size = offsets[static_names[curr_depth - 1]]
        write_float(snapshot.heading, snapshot.memory, offset, size)

    metadata_depths = metadata[1:5]
    return [depth for depth, visited in zip(DEPTHS, metadata_depths) if visited == 0]


def torus_distance(p1, p2, width=1000, height=1000):
    # Generated from prompt: how do you find the distance over a torus?
    dx = abs(p1[0] - p2[0])
    dy = abs(p1[1] - p2[1])

    dx = min(dx, width - dx)
    dy = min(dy, height - dy)

    return math.hypot(dx, dy)


def navigation(snapshot: JellyfishSnapshot, curr_pos: tuple[float, float]) -> Action:
    offsets = memory_offsets(snapshot.memory)
    curr_x, curr_y = curr_pos

    if snapshot.reproduction_capacity == 0:
        # Go to feeding zone
        destination_x = read_float(snapshot.memory, *offsets[CENTER_FEED_X])
        destination_y = read_float(snapshot.memory, *offsets[CENTER_FEED_Y])
        in_zone = snapshot.in_feeding_zone
    else:
        # Go to breeding zone
        destination_x = read_float(snapshot.memory, *offsets[CENTER_BREED_X])
        destination_y = read_float(snapshot.memory, *offsets[CENTER_BREED_Y])
        in_zone = snapshot.in_breeding_zone

    curr_distance = torus_distance((destination_x, destination_y), curr_pos)
    if curr_distance <= 200 and not in_zone:
        # @TODO: Maybe adjust our notion of the center
        pass

    curr_arr = [CURR_SURFACE, CURR_SHALLOW, CURR_MEDIUM, CURR_DEEP]
    curr_dir = [
        read_float(snapshot.memory, *offsets[c]) * math.pi / 180 for c in curr_arr
    ]

    # Take the current that will bring us closest
    best_dir = Depth.SURFACE
    best_dist = math.inf
    for depth, head in zip(DEPTHS, curr_dir):
        # Since counter-clockwise from true, sin=x, cos=y
        x = depth.speed * math.sin(head)
        y = depth.speed * math.cos(head)
        new_x = curr_x + x
        new_y = curr_y + y
        distance = torus_distance((destination_x, destination_y), (new_x, new_y))
        if distance < best_dist:
            best_dir = depth
            best_dist = distance

    return Action(depth=best_dir)


def fit_circle(points):
    # Give us numpy please b/c this is soooo slow. Could do coarse to fine, but if we are given numpy anyway then no point

    best_center = (0, 0)
    best_residual = math.inf
    for x in range(1000):
        for y in range(1000):
            center = (x, y)
            residual = 0
            for p in points:
                residual += abs(torus_distance(center, p) - 200)

            if residual < best_residual:
                best_center = center
                best_residual = residual

    return best_center


def exploration(snapshot: JellyfishSnapshot, curr_pos: tuple[float, float]) -> Action:
    # First get understanding of all currents
    unknown = unknown_currents(snapshot)
    if len(unknown) > 0:
        return Action(depth=unknown[0])

    offsets = memory_offsets(snapshot.memory)
    # Checks for boundaries. Want to see if we entered/exited a zone to estimate radius
    metadata_off, _ = offsets[METADATA_ZONES]
    zone_bitarray = val_to_bitarray(snapshot.memory[metadata_off])
    # Zone Metadata Bits: 0-2: Was in breed/feed/pred. 3-5: breed/feed/pred center estimate
    was_breed = bool(zone_bitarray[0])
    was_feed = bool(zone_bitarray[1])
    was_pred = bool(zone_bitarray[2])

    curr_x, curr_y = curr_pos
    if was_breed != snapshot.in_breeding_zone and zone_bitarray[3] == 0:
        # Record value
        breed1x = read_float(snapshot.memory, *offsets[BREED_1_X])
        breed1y = read_float(snapshot.memory, *offsets[BREED_1_Y])
        breed2x = read_float(snapshot.memory, *offsets[BREED_2_X])
        breed2y = read_float(snapshot.memory, *offsets[BREED_2_Y])
        if breed1x == 0 and breed1y == 0:
            write_float(curr_x, snapshot.memory, *offsets[BREED_1_X])
            write_float(curr_y, snapshot.memory, *offsets[BREED_1_Y])
        elif breed2x == 0 and breed2y == 0:
            write_float(curr_x, snapshot.memory, *offsets[BREED_2_X])
            write_float(curr_y, snapshot.memory, *offsets[BREED_2_Y])
        else:
            (
                center_x,
                center_y,
            ) = fit_circle([(breed1x, breed1y), (breed2x, breed2y), (curr_x, curr_y)])
            write_float(center_x, snapshot.memory, *offsets[CENTER_BREED_X])
            write_float(center_y, snapshot.memory, *offsets[CENTER_BREED_Y])
            zone_bitarray[3] = 1

    if was_feed != snapshot.in_feeding_zone and zone_bitarray[4] == 0:
        # Record value
        feed1x = read_float(snapshot.memory, *offsets[FEED_1_X])
        feed1y = read_float(snapshot.memory, *offsets[FEED_1_Y])
        feed2x = read_float(snapshot.memory, *offsets[FEED_2_X])
        feed2y = read_float(snapshot.memory, *offsets[FEED_2_Y])
        if feed1x == 0 and feed1y == 0:
            write_float(curr_x, snapshot.memory, *offsets[FEED_1_X])
            write_float(curr_y, snapshot.memory, *offsets[FEED_1_Y])
        elif feed2x == 0 and feed2y == 0:
            write_float(curr_x, snapshot.memory, *offsets[FEED_2_X])
            write_float(curr_y, snapshot.memory, *offsets[FEED_2_Y])
        else:
            center_x, center_y = fit_circle(
                [(feed1x, feed1y), (feed2x, feed2y), (curr_x, curr_y)]
            )
            write_float(center_x % 1000, snapshot.memory, *offsets[CENTER_FEED_X])
            write_float(center_y % 1000, snapshot.memory, *offsets[CENTER_FEED_Y])
            zone_bitarray[4] = 1

    if was_pred != snapshot.in_predator_zone and zone_bitarray[5] == 0:
        # @TODO: Too lazy to fill in. Also, do we need to also do this check in navigation, b/c might find other two before this.
        pass

    if zone_bitarray[3] == 1 and zone_bitarray[4] == 1:
        # Switch to navigation mode
        o, _ = offsets[METADATA]
        metadata = val_to_bitarray(snapshot.memory[o])
        metadata[0] = 1
        snapshot.memory[o] = bitarray_to_val(metadata)
        return navigation(snapshot, curr_pos)

    zone_bitarray[0] = 1 if snapshot.in_breeding_zone else 0
    zone_bitarray[1] = 1 if snapshot.in_feeding_zone else 0
    zone_bitarray[2] = 1 if snapshot.in_predator_zone else 0

    # Update memory for next time
    snapshot.memory[metadata_off] = bitarray_to_val(zone_bitarray)

    # Find optimal direction to traverse the field, given our directions.
    # Just try to maintain a 1:3 ratio. Possibilities are (1,3), (3,1), (3, -1), (1, -3), (-1, -3), (-3, -1), (-3, 1), (-1, 3)
    surface_off, surface_size = offsets[CURR_SURFACE]
    surface = read_float(snapshot.memory, surface_off, surface_size)
    angles = [math.atan2(x, y) * 180 / math.pi for x, y in SEARCH_ANGLES]
    angles = [a if a > 0 else a + 360 for a in angles]

    i = min(range(len(angles)), key=lambda i: angle_distance(angles[i], surface))

    # SEARCH_ANGLES[i] is the closest angle to surface current. Try to go in that direction.
    # @TODO This is not the right way to do this.
    search_x, search_y = SEARCH_ANGLES[i]
    if abs(search_x) == 1:
        section = curr_x // 100 * 100
        destination_y = (1000 * search_y / 3 + 1000) / 2  # 0 or 1000 based on the sign
        destination_x = section + 100 if search_x > 0 else section
    else:
        section = curr_y // 100 * 100
        destination_x = (1000 * search_x / 3 + 1000) / 2  # 0 or 1000 based on the sign
        destination_y = section + 100 if search_y > 0 else section

    x, y = destination_x - curr_x, destination_y - curr_y
    angle = math.atan2(x, y) * 180 / math.pi

    off, size = offsets[CURR_SHALLOW]
    shallow = read_float(snapshot.memory, off, size)
    off, size = offsets[CURR_MEDIUM]
    medium = read_float(snapshot.memory, off, size)
    off, size = offsets[CURR_DEEP]
    deep = read_float(snapshot.memory, off, size)

    currents = [surface, shallow, medium, deep]

    d = min(range(4), key=lambda i: angle_distance(currents[i], angle))
    return Action(depth=DEPTHS[d])


class Player9(Player):
    """Group 9's jellyfish.

    Metadata bits: 0: Mode, 1-4: Seen Currents, 5-6: Seen Feeding/Predator Zones

    Called once per living jellyfish per day. Read what the jellyfish senses
    from `snapshot`, update `snapshot.memory` in place if you want to
    remember something, and return an Action choosing today's depth.

    Do not keep per-jellyfish state on `self`: memory is the only memory.
    """

    def act(self, snapshot: JellyfishSnapshot) -> Action:
        offsets = memory_offsets(snapshot.memory)
        # If we don't have a good memory configuration, then just default to surface
        if len(offsets) == 0:
            return Action(depth=Depth.SURFACE)

        x_offset, x_size = offsets[POS_X]
        y_offset, y_size = offsets[POS_Y]

        # Previous position
        pos_x = read_float(snapshot.memory, x_offset, x_size, max_val=1000)
        pos_y = read_float(snapshot.memory, y_offset, y_size, max_val=1000)
        curr_pos = (pos_x, pos_y)
        if snapshot.age_days > 0:
            # Mod our new position to 0,1000 where 0,0 is our starting point
            new_x = (pos_x + snapshot.velocity[0]) % 1000
            new_y = (pos_y - snapshot.velocity[1]) % 1000

            write_float(new_x, snapshot.memory, x_offset, x_size, max_val=1000)
            write_float(new_y, snapshot.memory, y_offset, y_size, max_val=1000)
            curr_pos = (new_x, new_y)

        metadata = val_to_bitarray(snapshot.memory[0])
        # Mode: Exploration or Navigation
        if metadata[0]:
            # Navigation
            action = navigation(snapshot, curr_pos)
        else:
            action = exploration(snapshot, curr_pos)

        # mem_size = len(snapshot.memory)
        # history_offset = mem_size // 2 if mem_size > 256 else 0
        # if history_offset > 0:
        #     history = snapshot.memory[history_offset:]
        #     curr_offset = snapshot.age_days // 4
        #     if curr_offset >= mem_size - history_offset:
        #         return action
        #     bit_offset = (snapshot.age_days % 4) * 2
        #     snapshot_arr = val_to_bitarray(history[curr_offset])
        #     chosen = DEPTHS.index(action.depth)
        #     arr = val_to_bitarray(chosen, 2)
        #     snapshot_arr[bit_offset:bit_offset + 2] = arr
        #     history[curr_offset] = bitarray_to_val(snapshot_arr)
        #     snapshot.memory[history_offset:] = history

        return action
