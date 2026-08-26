"""
Converts an object-based directional exit into a lightweight virtual exit.
The exit's data (destination, success, osuccess, odrop) is stored in the
room's dexits property, and the exit object is recycled.

Usage: @virtualize <exit>

Arguments:
    exit  - The directional exit to virtualize (matched in room contents).

Abbrev:  @virtualize=5
Auth: gm2+ (auth_level 2)

Note: The exit must be a directional exit (descended from #21) located in
the current room. After conversion, the exit data lives in the room's
dexits list and the direction is added to obvexits. The original exit
object is permanently recycled.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
from moo.globals import DNAMES

spec = args.strip() if args else ''
if not spec:
    pobj.msg('Usage: @virtualize <exit>')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room.")
    return

# Match the exit in the room
candidates = list(room.contents)
target = bmatch(spec, pobj, candidates, db)
if not target:
    pobj.msg(f"Exit '{dobj}' not found in this room.")
    return

# Verify it's a directional exit (child of #21).
# The inheritance link is `parent` (an objnum); there is no `_parent_id`
# attribute, so reading that one ended the walk on the first step and no
# exit ever qualified.  #0 is its own parent, hence the seen-set.
obj = target
is_direxit = False
seen = set()
while obj is not None and obj.objnum not in seen:
    seen.add(obj.objnum)
    if obj.objnum == 15:
        is_direxit = True
        break
    parent = obj.parent
    if hasattr(parent, 'objnum'):
        obj = parent
    elif isinstance(parent, int) and parent >= 0:
        obj = db.get_object(parent)
    else:
        obj = None

if not is_direxit:
    pobj.msg(f"&<245>#{target.objnum}:{target.name}&n is not a directional exit.")
    return

# Find the direction index by matching the exit's noun against DNAMES
noun = target.noun or ''
try:
    enum = DNAMES.index(noun.lower())
except ValueError:
    pobj.msg(f"Could not determine direction for '{noun}'. Not a standard direction name.")
    return

# Gather exit properties
dest = target.destination
if not dest:
    pobj.msg(f"&<245>#{target.objnum}:{target.name}&n has no destination set.")
    return

dest_num = dest if type(dest) == int else dest.objnum if hasattr(dest, 'objnum') else dest
succ = target.success or ''
osucc = target.osuccess or ''
odrop = target.odrop or ''

# Get or initialize the room's dexits list (12 direction slots)
dexits = room.dexits or []
while len(dexits) < 12:
    dexits.append(None)

# Store the virtual exit data: [dest, succ, osucc, drop, odrop, rtval]
dexits[enum] = [dest_num, succ, osucc, '', odrop, 0]
room.dexits = dexits

# Add direction index to obvexits if not already present, sorted by direction order
obvexits = room.obvexits or []
if enum not in obvexits:
    obvexits.append(enum)
    obvexits = sorted([e for e in obvexits if type(e) == int],
                      key=lambda x: x if x < 12 else x - 12)
    room.obvexits = obvexits

# Remove the exit object from the room's exits list
exits = room.exits or []
if target.objnum in exits:
    exits.remove(target.objnum)
    room.exits = exits

# Also remove from obvexits if the objnum was listed there (object-based exit)
if target.objnum in obvexits:
    obvexits.remove(target.objnum)
    room.obvexits = obvexits

room._mark_modified()

# Recycle the exit object
exit_name = target.name
exit_num = target.objnum
recycle(target)

try:
    dest_obj = db.get_object(dest_num)
    dest_str = f"#{dest_num}:{dest_obj.name}"
except:
    dest_str = f"#{dest_num}"

pobj.msg(f"Converted &<245>#{exit_num}:{exit_name}&n ({DNAMES[enum]}) to virtual exit -> &<245>{dest_str}&n.")
pobj.msg(f"Exit object #{exit_num} recycled.")
