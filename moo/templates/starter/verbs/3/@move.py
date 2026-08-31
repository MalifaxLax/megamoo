"""
Usage: @move <object> to <destination> [with <message>]

Moves an object to a destination room or container. If a
message is provided after 'with', it is displayed to everyone
in the destination.

OBJECT is matched against room contents and your inventory.
DESTINATION must be a room or container ID in form #N.
MESSAGE is optional arrival text shown to the destination.

Examples:
    @move ball to #41
    @move ball to #201 with A ball comes flying into the room!
    @move #50 to #42
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg('Usage: @move <object> to <destination> [with <message>]')
    return

if not dobj:
    pobj.msg("Move what?")
    return

obj_part = (dobj or '').strip()
dest_part = (iobj or '').strip()
arrival_msg = (dobj2 or '').strip() if prep2 == 'with' else ''

candidates = list(pobj.location.contents) + list(pobj.contents)
obj = bmatch(obj_part, pobj, candidates, db)
if not obj:
    pobj.msg("Invalid object.")
    return

if not dest_part:
    pobj.msg("Move it where? Use: @move <object> to <destination>")
    return

dest = bmatch(dest_part, pobj, candidates, db)
if not dest:
    pobj.msg("Invalid destination.")
    return

def _room_of(o):
    """The room enclosing o, or None if it is not inside one."""
    for _ in range(16):
        if o is None:
            return None
        if getattr(o, 'is_room', False):
            return o
        o = getattr(o, 'location', None)
    return None

src_room = _room_of(obj.location)
dst_room = _room_of(dest)
if src_room is not None and dst_room is not None:
    if ((src_room.is_icroom and dst_room.is_ocroom)
            or (src_room.is_ocroom and dst_room.is_icroom)):
        kind = "an OOC" if dst_room.is_ocroom else "an IC"
        pobj.msg(f"You can't move &<245>#{obj.objnum}:{obj.name}&n into "
                 f"{kind} area from where it is.")
        return

old_loc = obj.location
move(obj, dest)
pobj.msg(f"Moved &<245>#{obj.objnum}:{obj.name}&n to &<245>#{dest.objnum}:{dest.name}&n.")

if arrival_msg:
    dest.msg_room(arrival_msg, exclude=[obj], sub=pobj, dob=obj)
