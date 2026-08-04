"""
Usage: @vopen <direction> to <destination>

Creates a new virtual directional exit at your current location.
Virtual exits are stored in the room's dexits property instead
of being created as separate exit objects — they are lightweight
and ideal for standard directional connections between rooms.

DIRECTION must be a valid direction name: north, south, east,
west, ne, nw, se, sw, u, d, o, in (or full names).
DESTINATION must be a room ID in form #N.

If the direction already has a virtual exit to the same room,
the verb reports it already exists. If it points to a different
room, you are asked whether to overwrite it.

Examples:
    @vopen north to #42
    @vopen se to #100
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
from moo.globals import DNAMES, FDNAMES, RFDNAMES, ESUCC, EOSUCC, EODROP

# No arguments: show usage
if not args:
    pobj.msg('Usage: @vopen <direction> to <destination>')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room to create a virtual exit.")
    return

# Parse direction from dobj
direction = dobj.strip().lower() if dobj else args.strip().split()[0].lower()
try:
    enum = DNAMES.index(direction)
except ValueError:
    pobj.msg(f"'{direction}' is not a valid direction name.")
    return

name = DNAMES[enum]

# Parse destination from iobj (expects "to #N")
dest_str = iobj.strip() if iobj else ''
if not dest_str or not dest_str.startswith('#') or not dest_str[1:].isdigit():
    pobj.msg("You need to include a destination room (#N).")
    return

try:
    dest = db.get_object(int(dest_str[1:]))
except:
    pobj.msg("Invalid destination object.")
    return

if not dest.is_room:
    pobj.msg("Destination must be a room.")
    return

# Deep copy dexits to avoid mutating inherited parent list
inherited = room.dexits or []
dexits = [list(e) if isinstance(e, list) else e for e in inherited]
while len(dexits) < 12:
    dexits.append(None)

# Check for existing virtual exit in this direction
existing = dexits[enum]
if existing and existing[0]:
    if existing[0] == dest.objnum:
        # Same destination — already exists
        pobj.msg(f"{name} to %<245>#{dest.objnum}:{dest.name}%n already exists.")
        return
    else:
        # Different destination — overwrite it
        old_dest = existing[0]
        dexits[enum] = [dest.objnum] + existing[1:]
        dexits[enum][0] = dest.objnum
        room.dexits = dexits
        room._mark_modified()
        try:
            old_obj = db.get_object(old_dest)
            old_str = f"#{old_dest}:{old_obj.name}"
        except:
            old_str = f"#{old_dest}"
        pobj.msg(f"%<245>{name}%n destination changed from %<245>{old_str}%n to %<245>#{dest.objnum}:{dest.name}%n.")
        return

# Build default exit messages with direction names substituted
fname = FDNAMES[enum]
rfname = RFDNAMES[enum]
succ = ESUCC.replace('%1', fname)
osucc = EOSUCC.replace('%1', fname)
odrop = EODROP.replace('%1', rfname)

# Store virtual exit data: [dest, succ, osucc, drop, odrop, rtval]
dexits[enum] = [dest.objnum, succ, osucc, '', odrop, 0]
room.dexits = dexits

# Deep copy obvexits too
obvexits = list(room.obvexits or [])
if enum not in obvexits:
    obvexits.append(enum)
    # Sort by direction index so exits display in canonical order
    obvexits = sorted([e for e in obvexits if type(e) == int],
                      key=lambda x: x if x < 12 else x - 12)
    room.obvexits = obvexits

room._mark_modified()
pobj.msg(f"\nYou created a new virtual %<245>{name}%n exit to %<245>#{dest.objnum}:{dest.name}%n.")
