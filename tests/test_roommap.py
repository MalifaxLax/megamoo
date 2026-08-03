"""tests/test_roommap.py — canonical room coordinates from the exit graph.

The layout has to be the *same* for every player and stable across runs;
that is the whole reason it is derived server-side rather than inferred
per-client from whatever route someone walked. These pin the properties
that make that true.
"""
import types

import pytest

from moo import roommap
from moo.roommap import build_layout, DIRECTION_OFFSETS


DNAMES = ['north', 'south', 'east', 'west', 'ne', 'nw', 'se', 'sw',
          'u', 'd', 'o', 'in']


class FakeRoom:
    """A room with just the attributes the deriver reads."""

    is_room = True

    def __init__(self, objnum, exits=None):
        self.objnum = objnum
        self.name = f'Room {objnum}'
        # dexits is parallel to dnames; each entry is [dest, ...messages].
        self.dexits = [[] for _ in DNAMES]
        for direction, dest in (exits or {}).items():
            self.dexits[DNAMES.index(direction)] = [dest, 'msg', 'msg']


class FakeDatabase:
    def __init__(self, rooms):
        self._rooms = {r.objnum: r for r in rooms}
        # #15 carries dnames.
        self._dnames_holder = types.SimpleNamespace(dnames=DNAMES)

    def get_object(self, objnum):
        if objnum == 15:
            return self._dnames_holder
        return self._rooms[objnum]

    def objects(self):
        return iter(self._rooms.values())


@pytest.fixture(autouse=True)
def _clear_cache():
    roommap.invalidate()
    yield
    roommap.invalidate()


# ---------------------------------------------------------------------------
#   Basic walking
# ---------------------------------------------------------------------------

def test_compass_directions_step_one_cell():
    db = FakeDatabase([
        FakeRoom(1, {'north': 2, 'east': 3}),
        FakeRoom(2), FakeRoom(3),
    ])
    layout = build_layout(db)
    x, y, z = layout[1]
    assert layout[2] == (x, y - 1, z), 'north must decrease y'
    assert layout[3] == (x + 1, y, z), 'east must increase x'


def test_up_and_down_change_level_not_position():
    db = FakeDatabase([FakeRoom(1, {'u': 2, 'd': 3}), FakeRoom(2), FakeRoom(3)])
    layout = build_layout(db)
    x, y, z = layout[1]
    assert layout[2] == (x, y, z + 1)
    assert layout[3] == (x, y, z - 1)


def test_every_room_is_placed():
    db = FakeDatabase([FakeRoom(1, {'north': 2}), FakeRoom(2), FakeRoom(3)])
    layout = build_layout(db)
    assert set(layout) == {1, 2, 3}


def test_no_two_rooms_share_a_cell():
    # A 2x2 block of rooms fully cross-linked: plenty of chances to collide.
    db = FakeDatabase([
        FakeRoom(1, {'east': 2, 'south': 3}),
        FakeRoom(2, {'west': 1, 'south': 4}),
        FakeRoom(3, {'north': 1, 'east': 4}),
        FakeRoom(4, {'north': 2, 'west': 3}),
    ])
    layout = build_layout(db)
    assert len(set(layout.values())) == len(layout)


# ---------------------------------------------------------------------------
#   Non-euclidean geography
# ---------------------------------------------------------------------------

def test_first_placement_wins_when_a_loop_does_not_close():
    """Three norths returning to the start must not move the start room.

    MUD geography loops in ways a grid cannot express. The rule is that a
    room already placed keeps its position and the connection simply
    stretches -- moving it would drag the whole map around behind it.
    """
    db = FakeDatabase([
        FakeRoom(1, {'north': 2}),
        FakeRoom(2, {'north': 3}),
        FakeRoom(3, {'north': 1}),   # back to the start, geometrically wrong
    ])
    layout = build_layout(db)
    assert layout[1] == (0, 0, 0)
    assert layout[2] == (0, -1, 0)
    assert layout[3] == (0, -2, 0)


def test_conflicting_target_cell_is_nudged_not_overlapped():
    # Both 2 and 3 want the cell north of 1.
    db = FakeDatabase([
        FakeRoom(1, {'north': 2, 'ne': 3}),
        FakeRoom(2, {'east': 3}),
        FakeRoom(3),
    ])
    layout = build_layout(db)
    assert len(set(layout.values())) == 3


# ---------------------------------------------------------------------------
#   Non-spatial exits and regions
# ---------------------------------------------------------------------------

def test_in_and_out_are_traversed_but_claim_no_direction():
    # 'in' still has to reach the room, or it would never be mapped.
    db = FakeDatabase([FakeRoom(1, {'in': 2}), FakeRoom(2)])
    layout = build_layout(db)
    assert 2 in layout
    assert layout[2] != layout[1]
    assert 'in' not in DIRECTION_OFFSETS and 'o' not in DIRECTION_OFFSETS


def test_disconnected_regions_do_not_overlap():
    db = FakeDatabase([
        FakeRoom(1, {'east': 2}), FakeRoom(2),
        FakeRoom(10, {'east': 11}), FakeRoom(11),   # separate island
    ])
    layout = build_layout(db)
    assert len(set(layout.values())) == 4
    connected = {layout[1][0], layout[2][0]}
    island = {layout[10][0], layout[11][0]}
    assert max(connected) < min(island), 'regions must be laid out apart'


def test_exit_to_a_nonexistent_room_is_ignored():
    db = FakeDatabase([FakeRoom(1, {'north': 999})])
    assert build_layout(db) == {1: (0, 0, 0)}


# ---------------------------------------------------------------------------
#   Relaxation
# ---------------------------------------------------------------------------

def _grid_world(extra=None):
    """A 3x3 block of rooms, fully linked, numbered left-to-right.

        1 2 3
        4 5 6
        7 8 9
    """
    links = {
        1: {'east': 2, 'south': 4},
        2: {'west': 1, 'east': 3, 'south': 5},
        3: {'west': 2, 'south': 6},
        4: {'north': 1, 'east': 5, 'south': 7},
        5: {'north': 2, 'west': 4, 'east': 6, 'south': 8},
        6: {'north': 3, 'west': 5, 'south': 9},
        7: {'north': 4, 'east': 8},
        8: {'north': 5, 'west': 7, 'east': 9},
        9: {'north': 6, 'west': 8},
    }
    if extra:
        for objnum, exits in extra.items():
            links.setdefault(objnum, {}).update(exits)
    return FakeDatabase([FakeRoom(n, e) for n, e in links.items()])


def _relative(layout, anchor=1):
    """Layout re-expressed relative to a room, so absolute origin is irrelevant."""
    ax, ay, az = layout[anchor]
    return {n: (x - ax, y - ay, z - az) for n, (x, y, z) in layout.items()}


def test_a_clean_grid_is_laid_out_exactly():
    layout = _relative(build_layout(_grid_world()))
    assert layout[5] == (1, 1, 0)
    assert layout[9] == (2, 2, 0)
    assert layout[3] == (2, 0, 0)
    assert layout[7] == (0, 2, 0)


def test_a_room_from_elsewhere_is_displaced_out_of_the_block():
    """The Haven bazaar bug, in miniature.

    Room 1 has a diagonal exit to an unrelated room, and the walk
    traverses it before reaching the middle of the block -- so the
    outsider claims the centre cell and every one of room 5's four exits
    ends up misaligned. Relaxation has to exchange them, since neither
    can move while the other holds the cell.
    """
    db = _grid_world(extra={1: {'se': 20}, 20: {}})
    layout = _relative(build_layout(db))
    assert layout[5] == (1, 1, 0), 'the block centre must belong to the block'
    assert layout[20] != (1, 1, 0)


def test_relaxation_leaves_no_improving_move_or_swap():
    """The result is a local optimum: nothing gains by moving or swapping."""
    from moo.roommap import _constraints, _score, _direction_names

    db = _grid_world(extra={1: {'se': 20}, 20: {}})
    layout = build_layout(db)
    rooms = {o.objnum: o for o in db.objects()}
    constraints = _constraints(rooms, _direction_names(db))
    occupant = {pos: num for num, pos in layout.items()}

    for objnum, position in layout.items():
        current = _score(objnum, position, layout, constraints)
        for (dx, dy, dz), other in constraints[objnum]:
            target = layout[other]
            candidate = (target[0] - dx, target[1] - dy, target[2] - dz)
            if candidate == position:
                continue
            holder = occupant.get(candidate)
            if holder is None:
                assert _score(objnum, candidate, layout, constraints) <= current, \
                    f'room {objnum} could improve by moving to {candidate}'
            else:
                before = current + _score(holder, candidate, layout, constraints)
                layout[objnum], layout[holder] = candidate, position
                after = (_score(objnum, candidate, layout, constraints)
                         + _score(holder, position, layout, constraints))
                layout[objnum], layout[holder] = position, candidate
                assert after <= before, \
                    f'rooms {objnum} and {holder} could improve by swapping'


def test_relaxation_never_stacks_two_rooms():
    db = _grid_world(extra={1: {'se': 20}, 20: {'nw': 5}})
    layout = build_layout(db)
    assert len(set(layout.values())) == len(layout)


# ---------------------------------------------------------------------------
#   Whole-run alignment
# ---------------------------------------------------------------------------

def test_a_misaligned_run_is_slid_into_place():
    """A street parallel to where it belongs must move as one piece.

    Single-room relaxation cannot fix this: shifting the head of the run
    satisfies its link back to the junction but breaks its link to the
    next room along, so it scores a tie and nothing moves. The run has to
    translate together.
    """
    from moo.roommap import _align_components

    db = FakeDatabase([
        FakeRoom(1, {'east': 2}),
        FakeRoom(2, {'east': 3}),
        FakeRoom(3, {'east': 4}),
        FakeRoom(4),
    ])
    rooms = {o.objnum: o for o in db.objects()}
    # 3 and 4 sit a row down and a cell out -- the East Main Street shape.
    coords = {1: (0, 0, 0), 2: (1, 0, 0), 3: (3, 1, 0), 4: (4, 1, 0)}
    taken = set(coords.values())

    _align_components(coords, taken, rooms, DNAMES)

    assert coords[3] == (2, 0, 0)
    assert coords[4] == (3, 0, 0)


def test_a_cycle_closes_onto_its_outlier():
    """A loop with one room out of place must end up consistent.

    Which side moves does not matter -- absolute position is meaningless,
    only the relationships are real. Sliding the block to meet the stray
    room is a perfectly good answer, and is what the acceptance test
    (strictly more satisfied exits) selects.
    """
    from moo.roommap import _align_components

    db = FakeDatabase([
        FakeRoom(1, {'east': 2, 'south': 3}),
        FakeRoom(2, {'south': 4}),
        FakeRoom(3, {'east': 4}),
        FakeRoom(4, {}),
    ])
    rooms = {o.objnum: o for o in db.objects()}
    coords = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0), 4: (5, 5, 0)}
    taken = set(coords.values())

    _align_components(coords, taken, rooms, DNAMES)

    ox, oy, oz = coords[1]
    assert coords[2] == (ox + 1, oy, oz)
    assert coords[3] == (ox, oy + 1, oz)
    assert coords[4] == (ox + 1, oy + 1, oz)


def test_alignment_never_stacks_rooms():
    from moo.roommap import _align_components

    db = FakeDatabase([
        FakeRoom(1, {'east': 2}),
        FakeRoom(2, {'east': 3}),
        FakeRoom(3, {'east': 4}),
        FakeRoom(4),
    ])
    rooms = {o.objnum: o for o in db.objects()}
    coords = {1: (0, 0, 0), 2: (1, 0, 0), 3: (3, 1, 0), 4: (4, 1, 0)}
    taken = set(coords.values())

    _align_components(coords, taken, rooms, DNAMES)

    assert len(set(coords.values())) == len(coords)
    assert taken == set(coords.values())


def test_a_fully_griddable_world_ends_up_perfect():
    """Nothing should be left misaligned when the world *can* be a grid."""
    from moo.roommap import DIRECTION_OFFSETS, _exits_of

    db = _grid_world(extra={3: {'east': 20}, 20: {'west': 3, 'east': 21},
                            21: {'west': 20}})
    layout = build_layout(db)
    rooms = {o.objnum: o for o in db.objects()}

    violations = []
    for objnum, room in rooms.items():
        x, y, z = layout[objnum]
        for direction, dest in _exits_of(room, DNAMES):
            offset = DIRECTION_OFFSETS.get(direction)
            if offset is None:
                continue
            want = (x + offset[0], y + offset[1], z + offset[2])
            if layout[dest] != want:
                violations.append((objnum, direction, dest))
    assert violations == []


# ---------------------------------------------------------------------------
#   Determinism and caching
# ---------------------------------------------------------------------------

def test_layout_is_deterministic():
    def make():
        return FakeDatabase([
            FakeRoom(1, {'north': 2, 'east': 3}),
            FakeRoom(2, {'east': 4}),
            FakeRoom(3, {'north': 4}),
            FakeRoom(4),
        ])
    assert build_layout(make()) == build_layout(make())


def test_layout_is_cached_until_invalidated():
    db = FakeDatabase([FakeRoom(1)])
    first = roommap.get_layout(db)
    assert roommap.get_layout(db) is first
    roommap.invalidate()
    assert roommap.get_layout(db) is not first


def test_coords_for_returns_a_list_or_none():
    db = FakeDatabase([FakeRoom(1)])
    assert roommap.coords_for(db, 1) == [0, 0, 0]
    assert roommap.coords_for(db, 999) is None
