"""
Creates a new climbable exit at your current location. Climbable
exits are for terrain that requires climbing -- slopes, rubble,
hills, walls, ladders, etc. They cannot be closed or locked.

Usage: @copen[/noret] <exit_name> [to <destination>]

Arguments:
    exit_name    - Name for the new exit (e.g. 'slope', 'ladder').
    destination  - Optional room ID (#N) to link the exit to.

Switches:
    /noret  - Do not create a return exit at the destination.

Auth: gm2+ (auth_level 2)

Note: The exit is created as a child of #24 (ClimbableExit). If a
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
parent = db.get_object(24)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room, dest=dest)

pobj.msg(f"\nYou created a new climbable exit &<245>#{new_exit.objnum}:{new_exit.name}&n.")

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
