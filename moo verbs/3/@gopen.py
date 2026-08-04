"""
Usage: @gopen[/noret] <exit_name> [to <destination>]

Creates a new go-type exit at your current location. Go exits
are named passage objects (trails, arches, paths, openings,
cracks, portals, etc.) — as opposed to directional exits which
use compass directions.

The exit is created as a child of #22 (GoExit). If DESTINATION
is provided as #N and links to a valid room, a return exit of
the same name is also created at the destination and linked
back — unless the /noret switch is used.

Switches:
    /noret  - Do not create a return exit at the destination.

Examples:
    @gopen path to #42
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
parent = db.get_object(22)
new_exit = ou.make_exit(parent, db, pobj, noun=name, room=room, dest=dest)

pobj.msg(f"\nYou created a new exit %<245>#{new_exit.objnum}:{new_exit.name}%n.")

if dest:
    pobj.msg(f"Exit linked to: %<245>#{dest.objnum}:{dest.name}%n")

    # Create return exit unless /noret switch is set
    if 'noret' not in switches:
        ret_exit = ou.make_exit(parent, db, pobj, noun=name,
                                room=dest, dest=room)

        # Cross-link the exits via rexit property
        new_exit.add_property('rexit', ret_exit.objnum, perms='rc')
        ret_exit.add_property('rexit', new_exit.objnum, perms='rc')
        new_exit._mark_modified()

        pobj.msg(f"Return exit %<245>#{ret_exit.objnum}:{ret_exit.name}%n created at %<245>#{dest.objnum}:{dest.name}%n.")
else:
    pobj.msg("Exit not linked.")
