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

_g = system_ref(db, 'globals')
ROOM_TYPES = dict(getattr(_g, 'room_types', None) or {}) if _g is not None else {}
ROOM_TYPE_NAMES = [tuple(e) for e in (getattr(_g, 'room_type_names', None) or [])] if _g is not None else []
if not ROOM_TYPES:
    pobj.msg('$globals.room_types is not set; @dig cannot resolve a room type.')
    return

if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
if 'types' in switches:
    maxlen = 24
    if (pobj.settings or {}).get('screenreader', False):
        pobj.msg("\nRoom types:")
        for short, desc in ROOM_TYPE_NAMES:
            pobj.msg(f"  {short}: {desc}")
        return
    header = '__ROOM TYPES__'.center(maxlen)
    pobj.msg(f"\n{header}")
    for short, desc in ROOM_TYPE_NAMES:
        pobj.msg(f"{short}{desc.rjust(maxlen - len(short))}")
    return

if not args:
    pobj.msg('Usage: @dig[/types][/tel] <roomtype> [= <roomname>]')
    return

rtype = dobj.strip().lower() if dobj else args.strip().lower()
rname = iobj.strip() if (prep == '=' and iobj) else None

parent_num = ROOM_TYPES.get(rtype)
if not parent_num:
    pobj.msg(f"'{rtype}' is not a valid room type. Use '@dig/types' to see options.")
    return

parent = db.get_object(parent_num)
if not parent.is_room:
    pobj.msg(f"#{parent_num} is not a room type.")
    return

new_room = make_room(parent, db, pobj, name=rname)
pobj.msg(f"You create a new room &<245>#{new_room.objnum}:{new_room.name}&n of type {rtype.upper()}.")

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
