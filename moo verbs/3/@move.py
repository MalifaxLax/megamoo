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

# Match the object in room contents + inventory
candidates = list(pobj.location.contents) + list(pobj.contents)
obj = bmatch(dobj, pobj, candidates, db)
if not obj:
    pobj.msg("Invalid object.")
    return

# Parse destination and optional message from iobj
# iobj could be "#13 with A ball flies in!" or just "#13"
iobj_str = iobj.strip() if iobj else ''
if not iobj_str:
    pobj.msg("Move it where? Use: @move <object> to <destination>")
    return

# Split on ' with ' to separate destination from message
arrival_msg = ''
if ' with ' in iobj_str:
    dest_part, arrival_msg = iobj_str.split(' with ', 1)
    dest_part = dest_part.strip()
    arrival_msg = arrival_msg.strip()
else:
    dest_part = iobj_str

# Resolve destination
dest = bmatch(dest_part, pobj, candidates, db)
if not dest:
    pobj.msg("Invalid destination.")
    return

# Move the object
old_loc = obj.location
move(obj, dest)
pobj.msg(f"Moved &<245>#{obj.objnum}:{obj.name}&n to &<245>#{dest.objnum}:{dest.name}&n.")

# Send arrival message to destination room
if arrival_msg:
    dest.msg_room(arrival_msg)
