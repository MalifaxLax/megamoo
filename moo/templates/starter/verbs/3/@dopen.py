"""
Usage: @dopen[/noret] <exit_name> to <destination>

Creates a new closable (door-type) exit at your current location.
Closable exits can be opened, closed, locked, and unlocked by
players. Use these for gates, doors, hatches, portals, etc.

A DESTINATION is required. Unless the /noret switch is used,
a return exit of the same name is created at the destination,
linked back to your location, and cross-linked via the 'reverse'
property so that opening/closing/locking one side affects both.

Both exits start in the closed state.

The exit is created as a child of #17 (ClosableGoExit).

Switches:
    /noadd  - Do not place the exit in the room or list it among its
              exits. It goes nowhere, and is reachable only through a
              property that names it, such as <object>.behind_exit.
    /noret  - Do not create a return exit at the destination.

Examples:
    @dopen gate to #42
    @dopen/noret hatch to #100
"""
# Security: only execute for the player this verb is defined on
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return
# No arguments: show usage
if not args:
    pobj.msg('Usage: @dopen[/noret] <exit_name> to <destination>')
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

# Destination is required for closable exits
dest_str = iobj.strip() if iobj else ''
if not dest_str or not dest_str.startswith('#') or not dest_str[1:].isdigit():
    pobj.msg("A destination is required (#N).")
    return

try:
    dest = db.get_object(int(dest_str[1:]))
except:
    pobj.msg("Invalid destination.")
    return

if not dest.is_room:
    pobj.msg(f"&<245>{dest_str}&n is not a valid destination.")
    return

# Create the exit via make_exit
parent = db.get_object(17)
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

# Closable-exit-specific properties
new_exit.add_property('closed', 1, perms='rc')
new_exit.add_property('ropen', 'The &D opens.', perms='rc')
new_exit.add_property('rclose', 'The &D closes.', perms='rc')

pobj.msg(f"You created a new closable exit &<245>#{new_exit.objnum}:{new_exit.name}&n.")
if 'noadd' in switches:
    pobj.msg("&<245>It is not in the room -- point something at it, e.g. @set #N.behind_exit = #%d&n" % new_exit.objnum)
pobj.msg(f"Exit linked to: &<245>#{dest.objnum}:{dest.name}&n")

# Create return exit unless /noret switch is set
if 'noret' not in switches:
    ret_exit = ou.make_exit(parent, db, pobj, noun=name,
                            room=dest, dest=room)

    # Closable-exit-specific properties on return exit
    ret_exit.add_property('closed', 1, perms='rc')
    ret_exit.add_property('ropen', 'The &D opens.', perms='rc')
    ret_exit.add_property('rclose', 'The &D closes.', perms='rc')

    # Cross-link exits via reverse property (open/close/lock syncs both sides)
    new_exit.add_property('reverse', ret_exit, perms='rc')
    ret_exit.add_property('reverse', new_exit, perms='rc')

    # Cross-link exits via rxexit/rexit properties
    new_exit.add_property('rxexit', ret_exit, perms='rc')
    ret_exit.add_property('rexit', new_exit, perms='rc')
    new_exit._mark_modified()

    pobj.msg(f"Return exit &<245>#{ret_exit.objnum}:{ret_exit.name}&n created at &<245>#{dest.objnum}:{dest.name}&n.")
    pobj.msg("Both exits start closed.")
