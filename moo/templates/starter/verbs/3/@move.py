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

# Parse argstr, the full unsplit argument string, rather than the
# parser's dobj/iobj.
#
# 'with' is a preposition.  The parser splits on it before this verb
# runs, so the message never arrived: iobj held only the destination and
# `if ' with ' in iobj_str` was never true.  The documented
# `@move ball to #13 with A ball comes flying in!` moved the ball in
# silence, and had done since it was written.  Same trap as @adverb's
# options; same answer.
raw = (argstr or '').strip()
head, _sep, _tail = raw.partition(' with ')
arrival_msg = _tail.strip() if _sep else ''
obj_part, _sep2, dest_part = head.partition(' to ')
obj_part = obj_part.strip()
dest_part = dest_part.strip()

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
