"""
Creates a new climbable exit at your current location. Climbable
exits are for terrain that requires climbing -- slopes, rubble,
hills, walls, ladders, etc. They cannot be closed or locked.

Usage: @copen[/noret] <exit_name> [to <destination>]

Arguments:
    exit_name    - Name for the new exit (e.g. 'slope', 'ladder').
    destination  - Optional room ID (#N) to link the exit to.

Switches:
    /noadd  - Do not place the exit in the room or list it among its
              exits. It goes nowhere, and is reachable only through a
              property that names it, such as <object>.behind_exit.
    /noret  - Do not create a return exit at the destination.

Auth: gm2+ (auth_level 2)

Note: The exit is created as a child of #18 (ClimbableExit). If a
destination is provided, a return exit is also created at the
destination and cross-linked via the 'rexit' property.
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg('Usage: @copen[/noret] <exit_name> [to <destination>]')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room to create an exit.")
    return

# Parse exit name from dobj
name = dobj.strip() if dobj else args.strip().split()[0]
if not name:
    pobj.msg("You must provide a name for the exit.")
    return

# Parse destination if provided
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

# Create the exit via make_exit
parent = db.get_object(18)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room, dest=dest)

# /noadd -- an exit only something else can reach.
#
# make_exit does two things: it moves the exit into the room and it lists
# the objnum in room.exits.  Both have to be undone, because either one on
# its own still leaves the exit walkable by name.  room.exits is what
# match_exit searches, and it resolves those numbers straight to objects
# without ever looking at where they are -- an exit moved inside another
# object went on answering to `go <name>` exactly as before.  And #13 go
# falls back to matching room.contents when match_exit finds nothing, so
# an exit merely dropped from the list is still reachable if it is lying
# in the room.
#
# Out of both, the exit is reachable only from a property that names it:
# <object>.behind_exit and its in_/on_/under_/through_ siblings.  gmove
# only reads destination, so nowhere is a perfectly good place to be.
if 'noadd' in switches:
    room.exits = [n for n in (room.exits or []) if n != new_exit.objnum]
    room._mark_modified()
    new_exit.location = None

pobj.msg(f"You created a new climbable exit &<245>#{new_exit.objnum}:{new_exit.name}&n.")
if 'noadd' in switches:
    pobj.msg("&<245>It is not in the room -- point something at it, e.g. @set #N.behind_exit = #%d&n" % new_exit.objnum)

if dest:
    pobj.msg(f"Exit linked to: &<245>#{dest.objnum}:{dest.name}&n")

    # Create return exit unless /noret switch is set
    if 'noret' not in switches:
        ret_exit = ou.make_exit(parent, db, pobj, noun=name,
                                room=dest, dest=room)

        # Cross-link the exits via rexit property
        new_exit.add_property('rexit', ret_exit.objnum, perms='rc')
        ret_exit.add_property('rexit', new_exit.objnum, perms='rc')
        new_exit._mark_modified()

        pobj.msg(f"Return exit &<245>#{ret_exit.objnum}:{ret_exit.name}&n created at &<245>#{dest.objnum}:{dest.name}&n.")
else:
    pobj.msg("Exit not linked.")
