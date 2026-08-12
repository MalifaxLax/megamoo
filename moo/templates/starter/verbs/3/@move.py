"""
Usage: @move <object> to <destination> [with <message>]

Moves an object to a destination room or container. If a
message is provided after 'with', it is displayed to everyone
in the destination.

OBJECT is matched against room contents and your inventory.
DESTINATION must be a room or container ID in form #N.
MESSAGE is optional arrival text shown to the destination.

Examples:
    @move ball to #13
    @move ball to #13 with A ball comes flying into the room!
    @move #50 to #14
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

# No arguments: show usage
if not args:
    pobj.msg('Usage: @move <object> to <destination> [with <message>]')
    return

# Parse: dobj = object, prep = to, iobj = destination [with message]
if not dobj:
    pobj.msg("Move what?")
    return

# The parser splits on both prepositions, so take the second slot.
#
# `@move ball to #13 with A ball comes flying in!` arrives as
# dobj='ball', prep='to', iobj='#13', prep2='with', dobj2='A ball comes
# flying in!'.  This verb looked for ' with ' inside iobj, which holds
# only the destination, so the condition was never true and the
# documented message was silently dropped -- since the verb was written.
obj_part = (dobj or '').strip()
dest_part = (iobj or '').strip()
arrival_msg = (dobj2 or '').strip() if prep2 == 'with' else ''

# Match the object in room contents + inventory
candidates = list(pobj.location.contents) + list(pobj.contents)
obj = bmatch(obj_part, pobj, candidates, db)
if not obj:
    pobj.msg("Invalid object.")
    return

if not dest_part:
    pobj.msg("Move it where? Use: @move <object> to <destination>")
    return

# Resolve destination
dest = bmatch(dest_part, pobj, candidates, db)
if not dest:
    pobj.msg("Invalid destination.")
    return

# --- IC/OOC boundary ---
#
# The same rule @tel keeps for people, kept here for things. Neither a
# character nor a bucket should cross by being carried across: an account
# body (#4) in an IC room has no hands, because move_to_hand lives on #5,
# and an IC object in the lobby is reachable by verbs that assume it is
# not.
#
# Compared room to room, not location to location, because either end may
# be a container or a character -- @move takes both -- and a sack changing
# hands inside one room crosses nothing.
def _room_of(o):
    """The room enclosing o, or None if it is not inside one."""
    for _ in range(16):          # a bounded walk: containers nest
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

# Move the object
old_loc = obj.location
move(obj, dest)
pobj.msg(f"Moved &<245>#{obj.objnum}:{obj.name}&n to &<245>#{dest.objnum}:{dest.name}&n.")

# Send arrival message to destination room.
#
# sub and dob so a builder's message can use the tokens the rest of the
# game uses -- "&D lands with a thud." -- rather than only literal text,
# and exclude so an object being moved is not told about its own arrival
# when that object is a player.
if arrival_msg:
    dest.msg_room(arrival_msg, exclude=[obj], sub=pobj, dob=obj)
