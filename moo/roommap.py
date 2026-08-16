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

Exit *objects* -- a door, an archway, a flight of stairs -- are walked on
the same terms.  They are not entries in ``dexits`` at all; they are
objects lying in the room that carry a ``destination``, and in a
hand-built world they are most of the joins.  See :func:`_exit_objects_of`
for why they contribute connectivity but never a bearing.

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


#: The authored coordinate convention, as a builder types it.
#:
#: ``room.coordinates`` is ``[x, y, z]`` with +x east, +y **north** and
#: +z up -- graph-paper order, which is what someone setting one by hand
#: expects.  Everything below works in screen order, where y grows
#: downward, so north is negated in exactly one place: :func:`_authored`.
#: Nowhere else in this module, or in the client, may flip it again.
AUTHORED_Y_IS_NORTH = True


def _authored(rooms):
    """
    ``{objnum: (x, y, z)}`` in screen order for rooms that state a position.

    A room with authored coordinates is ground truth. It is not derived,
    not relaxed, and not translated into a region lane -- the whole point
    of authoring them is that the builder, not this module, decides where
    the room is.

    Anything malformed is ignored rather than raising: coordinates are
    set by hand and by verbs, and one bad triple must not cost the world
    its layout.

    Two rooms claiming one cell is a real conflict and only the builder
    can resolve it, so the lower objnum keeps the cell, the loser falls
    back to being derived, and the clash is logged. Silently stacking
    them would draw one room on top of another; silently moving one would
    contradict what the builder wrote.
    """
    claimed = {}
    for objnum in sorted(rooms):
        value = getattr(rooms[objnum], 'coordinates', None)
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            continue
        try:
            x, y, z = (int(n) for n in value)
        except (TypeError, ValueError):
            continue
        position = (x, -y, z)          # authored north -> screen south
        holder = claimed.get(position)
        if holder is not None:
            logger.warning(
                "Room #%s claims coordinates already held by #%s: %s",
                objnum, holder[0], list(value))
            continue
        claimed[position] = (objnum, value)

    return {objnum: position for position, (objnum, _v) in claimed.items()}


def _exit_objects_of(room, database):
    """
    Yield ``(direction, destination)`` for the exit *objects* in a room.

    Go-exits (#22 and its children) are ordinary objects in the room's
    contents that carry their destination in ``destination``.  Nothing
    about them appears in ``dexits``, so a walk that reads only ``dexits``
    cannot see them -- and in a hand-built world they are most of the
    joins there are.

    Missing them does not merely lose a line on the map.  A room whose
    only way out is a door has *no* exits as far as the walk is concerned,
    so it becomes a disconnected region of one, gets its own origin
    ``REGION_GAP`` cells along, and is reported to every client as being
    nowhere near the room on the other side of the door the player just
    walked through.  In the reference world that was 13 of 18 go-exit
    joins, and it put four rooms of the same inn in a row four cells
    apart with nothing drawn between them.

    The direction comes from one of two places, and prose is not one of
    them.  A #21 DirectionalExit states its direction as its ``noun``.  A
    go-exit states it in ``direction``, which the builder sets -- and
    which exists because nothing else in a go-exit is a bearing.  The
    wording of ``success`` was tried and is not usable: only 5 of 18
    mention a compass point at all, and the reverse pair joining #406 and
    #408 claims ``east`` in *both* directions.

    A go-exit with no direction yields ``None``, and that is a real
    answer rather than a gap.  A front door is an ``in``/``out``
    relationship; it has no compass bearing to state, and one must not be
    invented for it.

    getattr with defaults throughout, and ints resolved: a room's contents
    can hold anything, including the objects under #1 but outside #10 that
    never declare ``is_exit`` and raise E_PROPNF when asked.
    """
    for item in room.contents:
        if isinstance(item, int):
            try:
                item = database.get_object(item)
            except Exception:
                continue
        if not getattr(item, 'is_exit', False):
            continue
        dest = getattr(item, 'destination', None)
        if not isinstance(dest, int):
            dest = getattr(dest, 'objnum', None)
        if not isinstance(dest, int) or dest <= 0:
            continue

        stated = (getattr(item, 'direction', '')
                  or getattr(item, 'noun', '') or '')
        yield canonical_direction(str(stated)), dest


def canonical_direction(word):
    """
    The canonical name for a direction word, or ``None``.

    Public because the builder verbs need exactly this reading of a typed
    direction -- ``@coord``, ``@vopen`` and ``@gopen`` must agree with the
    layout about what ``nw`` means, and a second copy of the table would
    be a second thing to keep in step.
    """
    word = word.strip().lower()
    if word in DIRECTION_OFFSETS:
        return word
    return _DIRECTION_ALIASES.get(word)


#: Offsets in **authored** order: +x east, +y north, +z up.
#:
#: ``DIRECTION_OFFSETS`` is screen order, where y grows downward, and is
#: right for laying out a canvas.  Anything reading or writing
#: ``room.coordinates`` wants this one instead, so that a verb stepping
#: ``north`` adds to y the way the builder who typed the coordinates
#: expects.  Derived from the other so the two cannot drift.
AUTHORED_OFFSETS = {name: (dx, -dy, dz)
                    for name, (dx, dy, dz) in DIRECTION_OFFSETS.items()}


def _canonical_direction(word):
    """Deprecated spelling of :func:`canonical_direction`."""
    return canonical_direction(word)


def read_coordinates(room):
    """A room's authored ``(x, y, z)`` in authored order, or ``None``."""
    value = getattr(room, 'coordinates', None)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(int(n) for n in value)
    except (TypeError, ValueError):
        return None


def place_relative(source, direction, dest, database):
    """
    Give *dest* the coordinates one step *direction* from *source*.

    Shared by every verb that links two rooms, so that building a world
    coordinates it as a side effect and nobody has to remember to run
    ``@coord`` afterwards.  Reports rather than acts whenever the answer
    is not obvious, because a wrong coordinate is worse than a missing
    one: a missing one is derived, and a wrong one is drawn as fact.

    Returns:
        (changed, message): *changed* says whether anything was written.
        *message* is None when there is nothing worth telling the builder.
    """
    step = AUTHORED_OFFSETS.get(canonical_direction(direction) or '')
    if step is None:
        return False, None          # in/out and friends state no bearing

    here = read_coordinates(source)
    if here is None:
        return False, ("This room has no coordinates, so none were set for "
                       "#%s. Set this one and @coord/fill." % dest.objnum)

    want = (here[0] + step[0], here[1] + step[1], here[2] + step[2])

    existing = read_coordinates(dest)
    if existing is not None:
        if existing == want:
            return False, None      # already right; nothing to say
        return False, ("#%s is at %d, %d, %d, not the %d, %d, %d this exit "
                       "implies. Left alone." % ((dest.objnum,) + existing
                                                 + want))

    for other in database.objects():
        if not getattr(other, 'is_room', False):
            continue
        if other.objnum != dest.objnum and read_coordinates(other) == want:
            return False, ("#%s would sit at %d, %d, %d, where #%s already "
                           "is. Left alone." % (dest.objnum, want[0], want[1],
                                                want[2], other.objnum))

    dest.coordinates = [want[0], want[1], want[2]]
    dest._mark_modified()
    invalidate()
    return True, ("#%s is now at %d, %d, %d."
                  % (dest.objnum, want[0], want[1], want[2]))


#: Spellings a builder may type, mapped to the names in DIRECTION_OFFSETS.
#: ``in``/``out`` are deliberately absent -- they are not bearings, and a
#: go-exit that states one is stating that it has none.
_DIRECTION_ALIASES = {
    'n': 'north', 's': 'south', 'e': 'east', 'w': 'west',
    'northeast': 'ne', 'northwest': 'nw',
    'southeast': 'se', 'southwest': 'sw',
    'up': 'u', 'down': 'd',
}


def _object_joins(rooms, database):
    """
    ``{objnum: {objnum: direction_or_None}}`` for exit-object connections.

    Symmetric even for a one-way door.  Which way you can walk is a
    question about the exit; how far apart the two rooms are is a question
    about the world, and a door on one side of a wall puts the rooms it
    joins beside each other whichever way it opens.  The reverse entry
    carries the opposite bearing when there is one, so a door stated as
    ``north`` on one side places its neighbour correctly from either end
    even if only one side was ever given a direction.

    Built once and passed around, because it costs a walk of every room's
    contents and both the layout walk and :func:`_align_components` need it.
    """
    joins = {objnum: {} for objnum in rooms}
    for objnum, room in rooms.items():
        try:
            links = list(_exit_objects_of(room, database))
        except Exception:
            continue            # a room whose contents will not enumerate
        for direction, dest in links:
            if dest not in rooms:
                continue
            # A stated bearing wins over one already recorded as unknown.
            if joins[objnum].get(dest) is None:
                joins[objnum][dest] = direction
            reverse = _opposite(direction)
            if joins[dest].get(objnum) is None:
                joins[dest][objnum] = reverse
    return joins


def _opposite(direction):
    """The reverse of a canonical direction, or ``None`` if there isn't one."""
    if direction is None:
        return None
    offset = DIRECTION_OFFSETS.get(direction)
    if offset is None:
        return None
    mirrored = (-offset[0], -offset[1], -offset[2])
    for name, candidate in DIRECTION_OFFSETS.items():
        if candidate == mirrored:
            return name
    return None


def _components(rooms, dnames, joins):
    """
    Rooms grouped into connected areas, largest first.

    Regions are laid out one after another along x, so the order they are
    walked decides who gets contiguous space.  Objnum order hands it out
    arbitrarily, and that is worse than it sounds: #18 BlankRoom -- a
    utility room with no exits in or out -- sorts before every street in
    Haven, takes a region of its own early, and lands in a cell East Main
    Street later needs.  The street cannot have it, so one of its rooms is
    nudged off the row and the map shows a diagonal jog in a straight
    road.

    Largest first gives the areas players actually walk the room they
    need, and leaves the singletons at the far end where nothing has to
    route around them.  Ties break on the lowest objnum so the result
    stays canonical -- every client must derive the same layout.
    """
    adjacency = {objnum: set() for objnum in rooms}
    for objnum, room in rooms.items():
        for _direction, dest in _exits_of(room, dnames):
            if dest in rooms:
                adjacency[objnum].add(dest)
                adjacency[dest].add(objnum)
        for dest in joins.get(objnum, ()):
            adjacency[objnum].add(dest)
            adjacency[dest].add(objnum)

    seen = set()
    components = []
    for start in sorted(rooms):
        if start in seen:
            continue
        group = {start}
        seen.add(start)
        queue = deque([start])
        while queue:
            for neighbour in adjacency[queue.popleft()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    group.add(neighbour)
                    queue.append(neighbour)
        components.append(group)

    components.sort(key=lambda group: (-len(group), min(group)))
    return components


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


def _walk_region(group, rooms, dnames, joins, seed, fixed):
    """
    Breadth-first placement of one connected area.

    *fixed* is the authored positions in this area.  A room named there is
    placed exactly where the builder said and never derived, so a walk
    through a world that has been fully coordinated simply reads the
    coordinates back out and the derivation below never fires at all.

    Everything not authored is derived around what is, which is what lets
    a half-coordinated world still draw: the authored rooms anchor, and
    the rest fall in from their exits.

    Local coordinates when nothing here is authored -- the area is walked
    as though it were the only thing in the world and
    :func:`build_layout` translates it into a lane.  When something *is*
    authored the area is already in absolute space and must not be moved.
    """
    origin = fixed.get(seed, (0, 0, 0))
    coords = {seed: origin}
    taken = {origin}

    queue = deque([seed])
    while queue:
        objnum = queue.popleft()
        room = rooms.get(objnum)
        if room is None:
            continue
        x, y, z = coords[objnum]

        def place(dest, target):
            # Authored wins outright: it is not a hint to be nudged off.
            if dest in fixed:
                target = fixed[dest]
            else:
                target = _free_cell(taken, *target)
            coords[dest] = target
            taken.add(target)
            queue.append(dest)

        for direction, dest in _exits_of(room, dnames):
            if dest not in group:
                continue            # exit into a non-room; not mappable
            if dest in coords:
                continue            # first placement wins; loop just bends
            offset = DIRECTION_OFFSETS.get(direction)
            if offset is None:
                # 'in'/'out': real connection, no spatial meaning.
                place(dest, (x, y + 1, z))
            else:
                dx, dy, dz = offset
                place(dest, (x + dx, y + dy, z + dz))

        # Doors, arches, stairs.  Traversed after the directional exits
        # above, and sorted, so a room reachable both ways takes its
        # compass placement and the result does not depend on the order
        # the contents happen to come back in.
        for dest in sorted(joins.get(objnum, {})):
            if dest not in group or dest in coords:
                continue
            offset = DIRECTION_OFFSETS.get(joins[objnum].get(dest))
            if offset is None:
                # A door with no stated bearing -- a front door, an arch
                # into a building.  Beside its source, never in an
                # invented compass direction.
                place(dest, (x, y + 1, z))
            else:
                dx, dy, dz = offset
                place(dest, (x + dx, y + dy, z + dz))

    return coords, taken


def build_layout(database):
    """
    Assign ``(x, y, z)`` to every room reachable through the exit graph.

    Each connected area is walked, relaxed and aligned *on its own*, in
    local coordinates, and only then translated into a lane of its own
    clear of everything already placed.

    Laying them all out in one shared coordinate space -- which is what
    this did -- meant the relaxation passes ran with the other regions
    sitting in the way.  The chargen block is a region of four rooms and,
    as the login area, it anchors the origin; Haven is a region of
    twenty-odd that has to be laid out beside it.  When alignment then
    tried to slide East Main Street west to meet the bazaar, chargen was
    standing in the cell it needed, so one room of a dead straight road
    was nudged off the row and the street drew with a diagonal jog in it.

    Widening ``REGION_GAP`` looked like the fix and is not: the outcome is
    not even monotonic in it (a gap of 6 scored *worse* than 4 or 8 on the
    reference world), because all it does is change which collision
    happens. Isolating the regions removes the collisions instead, and
    leaves the gap meaning the one thing it should -- how far apart two
    unconnected areas are drawn.

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

    joins = _object_joins(rooms, database)

    # Seed with the login room when it is a room, so the part of the world
    # players actually start in anchors the origin -- and walk its whole
    # area first, then the next largest, so the big connected places get
    # contiguous space before the strays do.
    login = None
    try:
        from .globals import LOGIN_ROOM
        if LOGIN_ROOM in rooms:
            login = LOGIN_ROOM
    except Exception:
        pass

    ordered = _components(rooms, dnames, joins)
    if login is not None:
        # Stable, so this only lifts the login room's area to the front and
        # leaves the size ordering of everything else alone.
        ordered.sort(key=lambda group: login not in group)

    authored = _authored(rooms)

    coords = {}
    region_x = 0
    if authored:
        # Derived areas are laid out to the right of everything stated, so
        # a half-coordinated world never drops a derived room on top of an
        # authored one.
        region_x = max(position[0] for position in authored.values()) \
            + REGION_GAP

    for group in ordered:
        fixed = {objnum: authored[objnum]
                 for objnum in group if objnum in authored}
        # An authored room anchors its area, so seed from one -- the walk
        # then spreads outward from a cell that is already correct.
        seed = (min(fixed) if fixed else
                (login if (login is not None and login in group)
                 else min(group)))
        subrooms = {objnum: rooms[objnum] for objnum in group}
        subjoins = {objnum: joins.get(objnum, {}) for objnum in group}

        local, taken = _walk_region(group, subrooms, dnames, subjoins,
                                    seed, fixed)
        # Authored rooms are ground truth and are frozen against every
        # pass below: relaxation exists to guess better, and there is
        # nothing left to guess about a room whose position was stated.
        frozen = set(fixed)
        _relax(local, taken, subrooms, dnames, frozen)
        _align_components(local, taken, subrooms, dnames, subjoins, frozen)
        _relax(local, taken, subrooms, dnames, frozen)

        if fixed:
            # Already in absolute space, and moving it would contradict
            # the coordinates it was anchored to.
            coords.update(local)
            continue

        # Slide the finished region so its left edge starts the next lane.
        shift = region_x - min(position[0] for position in local.values())
        for objnum, (x, y, z) in local.items():
            coords[objnum] = (x + shift, y, z)
        region_x = max(position[0] for position in local.values()) + shift \
            + REGION_GAP

    logger.info("Room layout derived: %d rooms in %d region(s), "
                "%d authored", len(coords), len(ordered), len(authored))
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


def _align_components(coords, taken, rooms, dnames, joins=None, frozen=None,
                      max_passes=6):
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

    *joins* is the extra connectivity from exit objects, and is optional
    because compass exits alone are a complete input -- that is the shape
    this had before doors were part of the graph at all.
    """
    constraints = _constraints(rooms, dnames)

    adjacency = {objnum: set() for objnum in rooms}
    for objnum, entries in constraints.items():
        for _delta, other in entries:
            adjacency[objnum].add(other)
            adjacency[other].add(objnum)

    # Exit objects join rooms too, and a run that slides has to take the
    # rooms behind its doors with it.  They are absent from `constraints`
    # on purpose -- a door has no bearing to satisfy -- but absent from
    # `adjacency` as well they would be torn off: aligning a street to its
    # junction would translate the street and leave the inn's bedrooms
    # standing where the street used to be.
    for objnum, others in (joins or {}).items():
        if objnum not in adjacency:
            continue
        for other in others:
            if other in adjacency:
                adjacency[objnum].add(other)
                adjacency[other].add(objnum)

    frozen = frozen or set()

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
                # A run containing a stated room cannot slide: the whole
                # translation would carry that room off the coordinates
                # the builder gave it.
                if run & frozen:
                    continue
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


def _relax(coords, taken, rooms, dnames, frozen=None, max_passes=12):
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
    # Rooms whose position was stated rather than guessed. They neither
    # move nor get swapped out from under a neighbour: an authored cell
    # is the answer, not a candidate.
    frozen = frozen or set()

    def relocate(objnum, position):
        taken.discard(coords[objnum])
        occupant.pop(coords[objnum], None)
        coords[objnum] = position
        taken.add(position)
        occupant[position] = objnum

    for _ in range(max_passes):
        moved = False
        for objnum in sorted(coords):
            if objnum in frozen:
                continue
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
                if holder in frozen:
                    continue        # its cell is stated; nothing to trade

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
