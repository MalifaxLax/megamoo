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
from moo.object_utils import make_room, ROOM_TYPES, ROOM_TYPE_NAMES

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
pobj.msg(f"\nYou create a new room %<245>#{new_room.objnum}:{new_room.name}%n of type {rtype.upper()}.")

# /tel switch: move the builder into the newly created room
if 'tel' in switches:
    move(pobj, new_room)
