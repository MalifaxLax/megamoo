"""
Usage: @gopen[/noret] <exit_name> [<direction>] [to <destination>]

Creates a new go-type exit at your current location. Go exits
are named passage objects (trails, arches, paths, openings,
cracks, portals, etc.) — as opposed to directional exits which
use compass directions.

A trailing DIRECTION states which way the exit actually goes, and
is what lets the mapper draw it. It is stored as `direction` on the
exit, the return exit gets the reverse automatically, and the
destination room is coordinated from it (see @coord). Without one
the exit still works — it simply has no bearing, which is the right
answer for a front door or an arch into a building, and the map
will not invent one.

The exit is created as a child of #16 (GoExit). If DESTINATION
is provided as #N and links to a valid room, a return exit of
the same name is also created at the destination and linked
back — unless the /noret switch is used.

Switches:
    /noadd  - Do not place the exit in the room or list it among its
              exits. It goes nowhere, and is reachable only through a
              property that names it, such as <object>.behind_exit.
    /noret  - Do not create a return exit at the destination.

Examples:
    @gopen path to #42
    @gopen door east to #406
    @gopen stairs up to #406
    @gopen/noret archway to #100
    @gopen crack
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg('Usage: @gopen[/noret] <exit_name> [to <destination>]')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room to create an exit.")
    return

name = dobj.strip() if dobj else args.strip().split()[0]
if not name:
    pobj.msg("You must provide a name for the exit.")
    return

bearing_word = ''
if ' ' in name:
    head, _, tail = name.rpartition(' ')
    from moo.roommap import canonical_direction as _cd
    if head and _cd(tail):
        name, bearing_word = head.strip(), tail.strip()

dest = None
dest_str = iobj.strip() if iobj else ''
if dest_str and dest_str.startswith('#') and dest_str[1:].isdigit():
    try:
        dest = db.get_object(int(dest_str[1:]))
    except:
        pobj.msg("Invalid destination. Exit not linked.")
        dest = None
    if dest and not dest.is_room:
        pobj.msg("Destination is not a room. Exit not linked.")
        dest = None
elif dest_str:
    pobj.msg("Please supply a valid destination ID (#N). Exit not linked.")

parent = db.get_object(16)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room, dest=dest)

if 'noadd' in switches:
    room.exits = [n for n in (room.exits or []) if n != new_exit.objnum]
    room._mark_modified()
    new_exit.location = None

pobj.msg(f"You created a new exit &<245>#{new_exit.objnum}:{new_exit.name}&n.")
if 'noadd' in switches:
    pobj.msg("&<245>It is not in the room -- point something at it, e.g. @set #N.behind_exit = #%d&n" % new_exit.objnum)

from moo.roommap import canonical_direction, place_relative, _opposite

bearing = canonical_direction(bearing_word) if bearing_word else None
if bearing_word and not bearing:
    pobj.msg(f"'{bearing_word}' is not a direction; the exit has no bearing.")
if bearing:
    new_exit.add_property('direction', bearing, perms='rc')
    new_exit._mark_modified()

if dest:
    pobj.msg(f"Exit linked to: &<245>#{dest.objnum}:{dest.name}&n")

    if 'noret' not in switches:
        ret_exit = ou.make_exit(parent, db, pobj, noun=name,
                                room=dest, dest=room)

        new_exit.add_property('rexit', ret_exit.objnum, perms='rc')
        ret_exit.add_property('rexit', new_exit.objnum, perms='rc')
        new_exit._mark_modified()

        back = _opposite(bearing) if bearing else None
        if back:
            ret_exit.add_property('direction', back, perms='rc')
            ret_exit._mark_modified()

        pobj.msg(f"Return exit &<245>#{ret_exit.objnum}:{ret_exit.name}&n created at &<245>#{dest.objnum}:{dest.name}&n.")

    if bearing:
        changed, note = place_relative(room, bearing, dest, db)
        if note:
            pobj.msg(note)
else:
    pobj.msg("Exit not linked.")
