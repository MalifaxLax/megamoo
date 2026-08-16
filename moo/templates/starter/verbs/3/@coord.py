"""
Usage: @coord [<room>]
       @coord [<room>] = <x>, <y>, <z>
       @coord/clear [<room>]
       @coord/fill [<room>]
       @coord/check [<room>]

Reads and writes a room's authored position -- `room.coordinates`, the
[x, y, z] the mapper draws from.

    +x is east, +y is NORTH, +z is up.

Graph-paper order, not screen order: going north raises y. The mapper
flips it once on the way to the canvas so nothing else has to.

A room with coordinates is ground truth. The layout never derives,
relaxes or moves it -- which is the whole point, and the only way the map
can be exactly right rather than merely plausible. Rooms without them are
still derived from the exit graph, so a half-coordinated world draws fine
and improves room by room.

Switches:
    /clear  - Remove the coordinates, returning the room to being derived.
    /fill   - Flood-fill outward from a room that already has coordinates,
              stamping every room reachable through an exit that states a
              bearing. This is how you coordinate a world: set one room,
              run it once. Rooms already coordinated are left alone and
              used as anchors, so it is safe to re-run after building.
    /check  - Audit. Walk every exit between two coordinated rooms and
              report the ones whose coordinates disagree with the exit's
              direction. Reports; changes nothing.

Bearings come from directional exits, and from go-exits that have had
`direction` set (see @gopen). A go-exit with no direction -- a front door,
an arch into a building -- states that it has no bearing, and is skipped
rather than guessed at.

Examples:
    @coord                        (show where you are)
    @coord #413 = 0, 0, 0
    @coord = 12, -4, 1
    @coord/fill #413
    @coord/check
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

from moo.roommap import AUTHORED_OFFSETS, canonical_direction, invalidate

DIM = '&<245>'
OFF = '&n'


def as_room(text):
    """The room a word names, or None (with the complaint already sent)."""
    text = (text or '').strip()
    if not text:
        room = pobj.location
        if not room or not getattr(room, 'is_room', False):
            pobj.msg("You are not in a room, so name one.")
            return None
        return room
    # Rooms are rarely in reach of the player naming them, so the
    # candidate list is the room they are in plus what they carry --
    # enough for "here" and a nearby exit, while `#N` (the way a room is
    # almost always named) is resolved by bmatch before candidates matter.
    nearby = list(pobj.contents or [])
    where = pobj.location
    if where:
        nearby += list(where.contents or [])
    found = bmatch(text, pobj, nearby, db)
    if not found:
        pobj.msg(f"I see no '{text}' here.")
        return None
    if not getattr(found, 'is_room', False):
        pobj.msg(f"{DIM}#{found.objnum}:{found.name}{OFF} is not a room.")
        return None
    return found


def coords_of(room):
    """A room's coordinates as a 3-tuple of ints, or None if unset/bad."""
    value = getattr(room, 'coordinates', None)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(int(n) for n in value)
    except (TypeError, ValueError):
        return None


def bearings_from(room):
    """
    (direction, destination_objnum) for every exit that states a bearing.

    Both kinds of exit, because both are real connections and the map has
    to agree with whichever one the builder used. Anything without a
    bearing -- in, out, an undirected door -- is left out: it is not that
    we failed to find its direction, it is that it does not have one.
    """
    found = []
    dnames = getattr(room, 'dnames', None) or []
    for index, entry in enumerate(getattr(room, 'dexits', None) or []):
        if index >= len(dnames) or not entry:
            continue
        dest = entry[0] if isinstance(entry, (list, tuple)) else entry
        direction = canonical_direction(dnames[index])
        if direction and isinstance(dest, int) and dest > 0:
            found.append((direction, dest))

    for item in room.contents:
        if isinstance(item, int):
            continue
        if not getattr(item, 'is_exit', False):
            continue
        dest = getattr(item, 'destination', None)
        if not isinstance(dest, int):
            dest = getattr(dest, 'objnum', None)
        if not isinstance(dest, int) or dest <= 0:
            continue
        stated = getattr(item, 'direction', '') or getattr(item, 'noun', '')
        direction = canonical_direction(str(stated or ''))
        if direction:
            found.append((direction, dest))
    return found


def show(room):
    position = coords_of(room)
    where = f"{DIM}#{room.objnum}:{room.name}{OFF}"
    if position is None:
        pobj.msg(f"{where} has no coordinates; it is derived from its exits.")
    else:
        pobj.msg(f"{where} is at {DIM}{position[0]}, {position[1]}, "
                 f"{position[2]}{OFF}  (x east, y north, z up)")


# ---------------------------------------------------------------------------
#   /check -- audit, change nothing
# ---------------------------------------------------------------------------
if 'check' in switches:
    rooms = {o.objnum: o for o in db.objects() if getattr(o, 'is_room', False)}
    known = {n: coords_of(r) for n, r in rooms.items()}
    known = {n: p for n, p in known.items() if p is not None}

    if not known:
        pobj.msg("No room has coordinates yet. Set one, then @coord/fill.")
        return

    seen = set()
    bad = []
    for objnum in sorted(known):
        here = known[objnum]
        for direction, dest in bearings_from(rooms[objnum]):
            if dest not in known:
                continue
            key = (min(objnum, dest), max(objnum, dest), direction)
            if key in seen:
                continue
            seen.add(key)
            dx, dy, dz = AUTHORED_OFFSETS[direction]
            want = (here[0] + dx, here[1] + dy, here[2] + dz)
            if known[dest] != want:
                bad.append((objnum, direction, dest, want, known[dest]))

    pobj.msg(f"{len(known)} of {len(rooms)} rooms coordinated.")
    if not bad:
        pobj.msg("Every exit between two coordinated rooms agrees with them.")
        return
    pobj.msg(f"{len(bad)} exit(s) disagree with the coordinates:")
    for objnum, direction, dest, want, got in bad:
        pobj.msg(f"  {DIM}#{objnum}{OFF} {direction} -> {DIM}#{dest}{OFF}"
                 f"  expects {want[0]}, {want[1]}, {want[2]}"
                 f"  but it is at {got[0]}, {got[1]}, {got[2]}")
    pobj.msg("Some of these may be deliberate -- a world is allowed to "
             "fold. Nothing has been changed.")
    return


# ---------------------------------------------------------------------------
#   /fill -- flood outward from a coordinated room
# ---------------------------------------------------------------------------
if 'fill' in switches:
    start = as_room(args)
    if not start:
        return
    origin = coords_of(start)
    if origin is None:
        pobj.msg(f"{DIM}#{start.objnum}:{start.name}{OFF} has no coordinates "
                 f"to fill from. Set it first: @coord #{start.objnum} = 0, 0, 0")
        return

    rooms = {o.objnum: o for o in db.objects() if getattr(o, 'is_room', False)}
    # Every already-coordinated room anchors the fill, not just the seed:
    # re-running after building must not fight the coordinates already set.
    taken = {}
    for objnum, room in rooms.items():
        position = coords_of(room)
        if position is not None:
            taken[position] = objnum

    placed = {}
    clashes = []
    queue = [start.objnum]
    seen = {start.objnum}
    while queue:
        objnum = queue.pop(0)
        here = coords_of(rooms[objnum])
        if here is None:
            continue
        for direction, dest in bearings_from(rooms[objnum]):
            if dest not in rooms or dest in seen:
                continue
            dx, dy, dz = AUTHORED_OFFSETS[direction]
            want = (here[0] + dx, here[1] + dy, here[2] + dz)
            existing = coords_of(rooms[dest])
            if existing is not None:
                # Already stated. Honour it, walk on through it, and say
                # so only when it disagrees -- that is a fold in the world
                # or a mistake, and either way it is the builder's call.
                seen.add(dest)
                queue.append(dest)
                if existing != want:
                    clashes.append((objnum, direction, dest, want, existing))
                continue
            holder = taken.get(want)
            if holder is not None:
                clashes.append((objnum, direction, dest, want, None))
                continue
            rooms[dest].coordinates = [want[0], want[1], want[2]]
            rooms[dest]._mark_modified()
            taken[want] = dest
            placed[dest] = want
            seen.add(dest)
            queue.append(dest)

    invalidate()
    pobj.msg(f"Coordinated {len(placed)} room(s) from "
             f"{DIM}#{start.objnum}:{start.name}{OFF}.")
    if clashes:
        pobj.msg(f"{len(clashes)} conflict(s), left for you:")
        for objnum, direction, dest, want, existing in clashes:
            if existing is None:
                pobj.msg(f"  {DIM}#{objnum}{OFF} {direction} -> "
                         f"{DIM}#{dest}{OFF} wants {want[0]}, {want[1]}, "
                         f"{want[2]} -- cell held by "
                         f"{DIM}#{taken[want]}{OFF}")
            else:
                pobj.msg(f"  {DIM}#{objnum}{OFF} {direction} -> "
                         f"{DIM}#{dest}{OFF} wants {want[0]}, {want[1]}, "
                         f"{want[2]} -- it says {existing[0]}, {existing[1]}, "
                         f"{existing[2]}")
    unset = [n for n in rooms if coords_of(rooms[n]) is None]
    if unset:
        pobj.msg(f"{len(unset)} room(s) still uncoordinated -- reachable only "
                 f"through exits with no bearing, or not connected at all: "
                 + ', '.join(f"#{n}" for n in sorted(unset)[:12])
                 + (' ...' if len(unset) > 12 else ''))
    return


# ---------------------------------------------------------------------------
#   /clear
# ---------------------------------------------------------------------------
if 'clear' in switches:
    room = as_room(args)
    if not room:
        return
    room.coordinates = []
    room._mark_modified()
    invalidate()
    pobj.msg(f"{DIM}#{room.objnum}:{room.name}{OFF} is derived again.")
    return


# ---------------------------------------------------------------------------
#   show, or set
# ---------------------------------------------------------------------------
text = (args or '').strip()
if '=' not in text:
    room = as_room(text)
    if room:
        show(room)
    return

target, _, values = text.partition('=')
room = as_room(target)
if not room:
    return

parts = [p for p in values.replace(',', ' ').split() if p]
if len(parts) != 3:
    pobj.msg("Give three whole numbers: @coord <room> = <x>, <y>, <z>")
    return
try:
    x, y, z = (int(p) for p in parts)
except ValueError:
    pobj.msg("Coordinates must be whole numbers.")
    return

rooms = {o.objnum: o for o in db.objects() if getattr(o, 'is_room', False)}
for objnum, other in rooms.items():
    if objnum == room.objnum:
        continue
    if coords_of(other) == (x, y, z):
        pobj.msg(f"{DIM}#{objnum}:{other.name}{OFF} is already at "
                 f"{x}, {y}, {z}. Nothing changed.")
        return

room.coordinates = [x, y, z]
room._mark_modified()
invalidate()
pobj.msg(f"{DIM}#{room.objnum}:{room.name}{OFF} is now at "
         f"{DIM}{x}, {y}, {z}{OFF}.")
