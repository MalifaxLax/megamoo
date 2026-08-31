"""
Usage: @jopen[/noret] <exit_name> [to <destination>]

Creates a new jumpable exit at your current location. Jumpable
exits are for terrain that requires jumping — gaps, chasms,
ledges, ravines, ditches, etc. They cannot be closed or locked.

The exit is created as a child of #19 (JumpableExit). If
DESTINATION is provided as #N and links to a valid room, a
return exit of the same name is also created at the destination
and linked back — unless the /noret switch is used.

Switches:
    /noadd  - Do not place the exit in the room or list it among its
              exits. It goes nowhere, and is reachable only through a
              property that names it, such as <object>.behind_exit.
    /noret  - Do not create a return exit at the destination.

Examples:
    @jopen gap to #42
    @jopen/noret ledge to #100
    @jopen chasm
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

if not args:
    pobj.msg('Usage: @jopen[/noret] <exit_name> [to <destination>]')
    return

room = pobj.location
if not room or not room.is_room:
    pobj.msg("You must be in a room to create an exit.")
    return

name = dobj.strip() if dobj else args.strip().split()[0]
if not name:
    pobj.msg("You must provide a name for the exit.")
    return

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

parent = db.get_object(19)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room, dest=dest)

if 'noadd' in switches:
    room.exits = [n for n in (room.exits or []) if n != new_exit.objnum]
    room._mark_modified()
    new_exit.location = None

pobj.msg(f"You created a new jumpable exit &<245>#{new_exit.objnum}:{new_exit.name}&n.")
if 'noadd' in switches:
    pobj.msg("&<245>It is not in the room -- point something at it, e.g. @set #N.behind_exit = #%d&n" % new_exit.objnum)

if dest:
    pobj.msg(f"Exit linked to: &<245>#{dest.objnum}:{dest.name}&n")

    if 'noret' not in switches:
        ret_exit = ou.make_exit(parent, db, pobj, noun=name,
                                room=dest, dest=room)

        new_exit.add_property('rexit', ret_exit.objnum, perms='rc')
        ret_exit.add_property('rexit', new_exit.objnum, perms='rc')
        new_exit._mark_modified()

        pobj.msg(f"Return exit &<245>#{ret_exit.objnum}:{ret_exit.name}&n created at &<245>#{dest.objnum}:{dest.name}&n.")
else:
    pobj.msg("Exit not linked.")
