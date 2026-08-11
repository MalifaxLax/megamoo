"""
Canonical room coordinates, derived from the exit graph.

Rooms carry no authored position in the database.  Rather than make each
client guess a layout from the path its player happened to walk -- which
gives every player a differently-shaped map and falls apart the moment
the geography loops -- this module walks ``room.dexits`` once and assigns
every room a single ``(x, y, z)``.

The result is *canonical*: the same for every player, stable across
sessions, and the same layout a builder would see.  A client can then
place rooms exactly instead of dead-reckoning.

How the walk works
------------------

``dexits`` is a list parallel to ``#15.dnames``
(``['north', 'south', 'east', 'west', 'ne', 'nw', 'se', 'sw', 'u', 'd',
'o', 'in']``); entry *i* is ``[destination_objnum, ...messages]`` or
empty.  A breadth-first walk from a seed room steps one cell per
direction, so ``north`` from ``(4, 4, 0)`` lands at ``(4, 3, 0)`` and
``u`` lands at ``(4, 4, 1)``.

MUD geography is not euclidean: walking a four-room loop can return you
somewhere other than where the grid says you should be.  Two rules keep
that from destroying the map:

* A room already placed keeps its first position.  The loop simply
  closes with a longer connecting line, which reads as the world bending
  rather than as a room in the wrong place.
* A room whose computed cell is taken by a *different* room is placed at
  the nearest free cell on the same level.

``o`` (out) and ``in`` describe no spatial relationship, so they are
traversed for connectivity but contribute no offset -- their destination
is placed beside its source rather than pretending to be a compass move.

Disconnected regions (an arena, a private build) each get their own walk,
laid out side by side so their coordinates never collide.
"""

import logging
from collections import deque

logger = logging.getLogger('megamoo.roommap')

# Offsets by direction name, matching #15.dnames.  ``o``/``in`` are
# deliberately absent: see the module docstring.
DIRECTION_OFFSETS = {
    'north': (0, -1, 0),
    'south': (0, 1, 0),
    'east':  (1, 0, 0),
    'west':  (-1, 0, 0),
    'ne':    (1, -1, 0),
    'nw':    (-1, -1, 0),
    'se':    (1, 1, 0),
    'sw':    (-1, 1, 0),
    'u':     (0, 0, 1),
    'd':     (0, 0, -1),
}

#: Gap between disconnected regions, in cells.
REGION_GAP = 4

#: How far to search for a free cell before giving up and overlapping.
MAX_NUDGE_RADIUS = 8


def _direction_names(database):
    """The canonical direction list (``#15.dnames``), with a fallback."""
    try:
        names = getattr(database.get_object(15), 'dnames', None)
        if names:
            return list(names)
    except Exception:
        pass
    return ['north', 'south', 'east', 'west', 'ne', 'nw', 'se', 'sw',
            'u', 'd', 'o', 'in']


def _exits_of(room, dnames):
    """
    Yield ``(direction_name, destination_objnum)`` for a room.

    Reads ``dexits`` -- entry *i* is ``[dest, ...messages]`` or empty --
    and skips anything that is not a usable destination number.
    """
    dexits = room.dexits or []
    for index, entry in enumerate(dexits):
        if index >= len(dnames) or not entry:
            continue
        dest = entry[0] if isinstance(entry, (list, tuple)) else entry
        if isinstance(dest, int) and dest > 0:
            yield dnames[index], dest


def _is_room(obj):
    """Whether *obj* is a room, asked so that every object can answer.

    getattr with a default, not a bare read.  #1 declares ``is_room``
    false precisely so anything under Root can be asked -- but #0 is not
    under Root.  It is the system object, its parent is 0, and it inherits
    none of those declarations, so the bare read raised E_PROPNF on it.

    That mattered more than it looks.  The walk below runs over objects in
    numeric order, so it reached #0 first and died there every time;
    ``get_layout`` caught the exception, logged it, and cached an empty
    layout.  Every room then reported no coordinates, every mapping client
    fell back to dead-reckoning from whichever way the player happened to
    walk, and the canonical layout this module exists to provide had never
    once been computed.
    """
    return bool(getattr(obj, 'is_room', False))


def _free_cell(taken, x, y, z):
    """
    The given cell, or the nearest free one on the same level.

    Searched in rings so a displaced room lands as close as possible to
    where its exit actually pointed.
    """
    if (x, y, z) not in taken:
        return x, y, z
    for radius in range(1, MAX_NUDGE_RADIUS + 1):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                if (x + dx, y + dy, z) not in taken:
                    return x + dx, y + dy, z
    # Every nearby cell is taken; overlap rather than loop forever.
    return x, y, z


def build_layout(database):
    """
    Assign ``(x, y, z)`` to every room reachable through the exit graph.

    Args:
        database: The live ``Database``.

    Returns:
        dict: ``{objnum: (x, y, z)}``.  Rooms with no exits and no
        incoming exits still appear, each in its own region.
    """
    dnames = _direction_names(database)

    rooms = {}
    for obj in database.objects():
        if _is_room(obj):
            rooms[obj.objnum] = obj

    coords = {}
    taken = set()
    # Regions are laid out left to right; this is where the next one starts.
    region_x = 0

    # Seed with the login room when it is a room, so the part of the world
    # players actually start in anchors the origin.
    seeds = []
    try:
        from .globals import LOGIN_ROOM
        if LOGIN_ROOM in rooms:
            seeds.append(LOGIN_ROOM)
    except Exception:
        pass
    seeds.extend(sorted(rooms))

    for seed in seeds:
        if seed in coords:
            continue

        origin = (region_x, 0, 0)
        origin = _free_cell(taken, *origin)
        coords[seed] = origin
        taken.add(origin)
        region_cells = [origin]

        queue = deque([seed])
        while queue:
            objnum = queue.popleft()
            room = rooms.get(objnum)
            if room is None:
                continue
            x, y, z = coords[objnum]

            for direction, dest in _exits_of(room, dnames):
                if dest not in rooms:
                    continue            # exit into a non-room; not mappable
                if dest in coords:
                    continue            # first placement wins; loop just bends
                offset = DIRECTION_OFFSETS.get(direction)
                if offset is None:
                    # 'in'/'out': real connection, no spatial meaning.
                    target = _free_cell(taken, x, y + 1, z)
                else:
                    dx, dy, dz = offset
                    target = _free_cell(taken, x + dx, y + dy, z + dz)
                coords[dest] = target
                taken.add(target)
                region_cells.append(target)
                queue.append(dest)

        # Start the next region clear of this one's rightmost column.
        region_x = max(cell[0] for cell in region_cells) + REGION_GAP

    _relax(coords, taken, rooms, dnames)
    _align_components(coords, taken, rooms, dnames)
    _relax(coords, taken, rooms, dnames)

    logger.info("Room layout derived: %d rooms", len(coords))
    return coords


# ---------------------------------------------------------------------------
#   Whole-run alignment
# ---------------------------------------------------------------------------

def _satisfied_total(coords, constraints):
    """How many exit relationships hold across the whole layout."""
    total = 0
    for objnum, position in coords.items():
        total += _score(objnum, position, coords, constraints)
    return total


def _reachable_without(start, through, adjacency):
    """Every room reachable from *start* without passing through *through*."""
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in adjacency.get(node, ()):
            if neighbour == through or neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append(neighbour)
    return seen


def _align_components(coords, taken, rooms, dnames, max_passes=6):
    """
    Slide a whole run of rooms at once to close a misaligned join.

    :func:`_relax` moves one room at a time, which cannot fix a street
    that runs parallel to where it should be.  Shifting the first room of
    the street satisfies its link back to the junction but breaks its link
    to the next room along -- a tie, so nothing moves, and the whole run
    stays one row off with a diagonal jump into it.

    The move that actually helps is translating the entire run.  For each
    unsatisfied exit, work out the shift that would satisfy it, find every
    room reachable from the far side *without passing back through the
    near side*, and move that whole set together.  A rigid translation
    preserves every relationship inside the set, so only the links
    crossing the boundary can change.

    What keeps this honest is the acceptance test, not the choice of set:
    a shift is kept only when the number of satisfied exits across the
    whole layout strictly increases.  That makes the search monotonic, so
    it terminates, and it means a badly chosen set simply gets rejected --
    including the case where the two sides sit on a cycle and the "run"
    is most of the map.  (Sometimes moving that much is exactly right:
    when one outlying room is the correctly placed one, sliding the block
    to meet it is what closes the layout.)
    """
    constraints = _constraints(rooms, dnames)

    adjacency = {objnum: set() for objnum in rooms}
    for objnum, entries in constraints.items():
        for _delta, other in entries:
            adjacency[objnum].add(other)
            adjacency[other].add(objnum)

    for _ in range(max_passes):
        best_total = _satisfied_total(coords, constraints)
        applied = False

        for objnum in sorted(coords):
            here = coords[objnum]
            for (dx, dy, dz), other in constraints[objnum]:
                target = coords.get(other)
                if target is None:
                    continue
                want = (here[0] + dx, here[1] + dy, here[2] + dz)
                if target == want:
                    continue                     # already aligned

                shift = (want[0] - target[0], want[1] - target[1],
                         want[2] - target[2])

                run = _reachable_without(other, objnum, adjacency)
                moved = {r: (coords[r][0] + shift[0],
                             coords[r][1] + shift[1],
                             coords[r][2] + shift[2]) for r in run}

                # The run must land on empty space, not on the rooms it
                # is being aligned against.
                outside = {position for room, position in coords.items()
                           if room not in run}
                if outside & set(moved.values()):
                    continue

                original = {r: coords[r] for r in run}
                coords.update(moved)
                if _satisfied_total(coords, constraints) > best_total:
                    for position in original.values():
                        taken.discard(position)
                    taken.update(moved.values())
                    best_total = _satisfied_total(coords, constraints)
                    applied = True
                    break
                coords.update(original)          # no better; put it back

            if applied:
                break

        if not applied:
            break


# ---------------------------------------------------------------------------
#   Relaxation
# ---------------------------------------------------------------------------

def _constraints(rooms, dnames):
    """
    Per-room list of ``(delta, other)``: *other* should sit at this room's
    position plus *delta*.

    Both directions are recorded.  An exit ``north`` from A to B says B is
    one north of A, and equally that A is one south of B -- and a room is
    misplaced relative to its neighbours whichever way the exit points, so
    the walk that placed it must not be the only vote that counts.
    """
    constraints = {objnum: [] for objnum in rooms}
    for objnum, room in rooms.items():
        for direction, dest in _exits_of(room, dnames):
            offset = DIRECTION_OFFSETS.get(direction)
            if offset is None or dest not in rooms:
                continue
            constraints[objnum].append((offset, dest))
            constraints[dest].append(((-offset[0], -offset[1], -offset[2]),
                                      objnum))
    return constraints


def _score(objnum, position, coords, constraints):
    """How many of a room's exit relationships hold at *position*."""
    x, y, z = position
    score = 0
    for (dx, dy, dz), other in constraints[objnum]:
        target = coords.get(other)
        if target and target == (x + dx, y + dy, z + dz):
            score += 1
    return score


def _relax(coords, taken, rooms, dnames, max_passes=12):
    """
    Improve the breadth-first layout by local search.

    The walk places each room the first time it is reached, which means an
    arbitrary neighbour decides its cell.  When a room sits at the edge of
    two areas -- a market square also reachable from the street outside --
    whichever exit the walk happened to traverse first wins, and the room
    can end up outside the block it belongs to, dragging every one of its
    other exits out of alignment with it.

    So: repeatedly offer each room the cells its neighbours imply, and
    move it when one satisfies more of its exits than where it currently
    sits.  Ties keep the current position, which keeps the result stable
    and independent of iteration order.  Converges quickly; capped anyway
    so a pathological world cannot spin here.

    Swaps matter as much as moves.  A grid cannot embed a graph that is
    not planar, so two areas joined by a long path can end up overlapping,
    and a room from one area sits in the cell another area needs -- an
    unrelated room parked in the middle of a market square.  Neither can
    move while the other holds the cell, so the pair is exchanged whenever
    that leaves them collectively better placed.
    """
    constraints = _constraints(rooms, dnames)
    occupant = {position: objnum for objnum, position in coords.items()}

    def relocate(objnum, position):
        taken.discard(coords[objnum])
        occupant.pop(coords[objnum], None)
        coords[objnum] = position
        taken.add(position)
        occupant[position] = objnum

    for _ in range(max_passes):
        moved = False
        for objnum in sorted(coords):
            current = coords[objnum]
            best = _score(objnum, current, coords, constraints)
            best_position = current
            best_swap = None

            # Candidates: exactly the cells this room's neighbours want it in.
            for (dx, dy, dz), other in constraints[objnum]:
                target = coords.get(other)
                if not target:
                    continue
                candidate = (target[0] - dx, target[1] - dy, target[2] - dz)
                if candidate == current:
                    continue

                holder = occupant.get(candidate)
                if holder is None:
                    score = _score(objnum, candidate, coords, constraints)
                    if score > best:
                        best, best_position, best_swap = score, candidate, None
                    continue

                # Occupied: would exchanging the two place both better?
                # Scored with the swap actually applied, so a pair that
                # are each other's neighbours is measured honestly.
                before = (_score(objnum, current, coords, constraints)
                          + _score(holder, candidate, coords, constraints))
                coords[objnum], coords[holder] = candidate, current
                after = (_score(objnum, candidate, coords, constraints)
                         + _score(holder, current, coords, constraints))
                coords[objnum], coords[holder] = current, candidate

                if after > before:
                    score = _score(objnum, candidate, coords, constraints)
                    if score >= best:
                        best, best_position, best_swap = score, candidate, holder

            if best_position == current:
                continue

            if best_swap is not None:
                # Exchange directly: two relocate() calls would have the
                # second discard the cell the first just claimed. A swap
                # leaves the same set of cells occupied, so `taken` is
                # already correct.
                coords[objnum], coords[best_swap] = best_position, current
                occupant[best_position] = objnum
                occupant[current] = best_swap
            else:
                relocate(objnum, best_position)
            moved = True

        if not moved:
            break


# ---------------------------------------------------------------------------
#   Cached accessor
# ---------------------------------------------------------------------------

_cache = None


def get_layout(database):
    """
    The room layout, computed once and cached.

    Computed lazily: a server with no mapping clients never pays for it.
    """
    global _cache
    if _cache is None:
        try:
            _cache = build_layout(database)
        except Exception:
            logger.error("Room layout derivation failed", exc_info=True)
            _cache = {}
    return _cache


def coords_for(database, objnum):
    """``[x, y, z]`` for a room, or ``None`` if it has no derived position."""
    position = get_layout(database).get(objnum)
    return list(position) if position else None


def invalidate():
    """
    Drop the cached layout so the next lookup rebuilds it.

    Call after building or re-linking rooms; the layout is derived from
    the exit graph, so it goes stale when that graph changes.
    """
    global _cache
    _cache = None
