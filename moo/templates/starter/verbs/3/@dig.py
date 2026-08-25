"""
Usage: @dig[/switches] <roomtype> [= <roomname>]

Creates a new room of the given type with an optional name.
ROOMTYPE is required and must be one of the built-in room types.
ROOMNAME defaults to the parent type's noun if not provided.

Switches:
    /types  - Display a list of available room types.
    /tel    - Teleport to the newly created room.

Examples:
    @dig ic = Town Square
    @dig/tel ooc = OOC Lounge
    @dig/types

Note: Use @open, @vopen, @gopen, @copen, @jopen to create exits.
"""
from moo.object_utils import make_room, system_ref

# The room types are the world's, not the engine's: they name object numbers,
# and a Python constant naming an object number is one @renumber cannot
# maintain.  They live on $globals now.
_g = system_ref(db, 'globals')
ROOM_TYPES = dict(getattr(_g, 'room_types', None) or {}) if _g is not None else {}
ROOM_TYPE_NAMES = [tuple(e) for e in (getattr(_g, 'room_type_names', None) or [])] if _g is not None else []
if not ROOM_TYPES:
    pobj.msg('$globals.room_types is not set; @dig cannot resolve a room type.')
    return

# Security: only execute for the player this verb is defined on
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
# /types switch: display available room types and return
if 'types' in switches:
    maxlen = 24
    header = '__ROOM TYPES__'.center(maxlen)
    pobj.msg(f"\n{header}")
    for short, desc in ROOM_TYPE_NAMES:
        pobj.msg(f"{short}{desc.rjust(maxlen - len(short))}")
    return

# No arguments: show usage via docstring
if not args:
    pobj.msg('Usage: @dig[/types][/tel] <roomtype> [= <roomname>]')
    return

# Parse arguments: dobj = room type, iobj = room name (split on '=')
rtype = dobj.strip().lower() if dobj else args.strip().lower()
rname = iobj.strip() if (prep == '=' and iobj) else None

# Validate room type against known types
parent_num = ROOM_TYPES.get(rtype)
if not parent_num:
    pobj.msg(f"'{rtype}' is not a valid room type. Use '@dig/types' to see options.")
    return

# Fetch the parent room object and verify it's actually a room
parent = db.get_object(parent_num)
if not parent.is_room:
    pobj.msg(f"#{parent_num} is not a room type.")
    return

# Create the new room via object_utils
new_room = make_room(parent, db, pobj, name=rname)
pobj.msg(f"You create a new room &<245>#{new_room.objnum}:{new_room.name}&n of type {rtype.upper()}.")

# /tel switch: move the builder into the newly created room.
#
# Subject to the same IC/OOC boundary @tel enforces, which this used to
# walk straight through -- and it is the easiest way to cross it, because
# the room on the far side is one you just made. An account body (#4) in
# an IC room has no hands: `get` answers "Verb 'move_to_hand' not found",
# because move_to_hand lives on #5 and never will live anywhere else.
#
# The room is still created. Only the trip is refused, so the switch
# turns into a no-op rather than losing the work.
if 'tel' in switches:
    here = pobj.location
    src_ic = getattr(here, 'is_icroom', False)
    src_oc = getattr(here, 'is_ocroom', False)
    if (src_ic and new_room.is_ocroom) or (src_oc and new_room.is_icroom):
        kind = "an OOC" if new_room.is_ocroom else "an IC"
        pobj.msg(f"Not moved: {kind} room is across the boundary from here. "
                 f"Use &<245>@tel #{new_room.objnum}&n from the other side.")
    else:
        move(pobj, new_room)
